import chromadb
from openai import OpenAI, AsyncOpenAI
from chromadb.utils import embedding_functions
from core.config import settings

# ChromaDB 持久化客户端
CHROMA_DATA_PATH = settings.STORAGE_CHROMA_DB_PATH
chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)

# OpenAI Compatible Robust Embedding Function
class RobustOpenAIEmbeddingFunction(embedding_functions.OpenAIEmbeddingFunction):
    # Static class member to cache vector dimension
    _cached_dim = None

    def __call__(self, input):
        import urllib.request
        import json

        model_name = getattr(self, "model_name", "") or settings.LLM_EMBEDDING_MODEL
        is_vision = "vision" in model_name.lower()
        base_url = (self.api_base or settings.EMBEDDING_BASE_URL).rstrip("/")
        
        # 检测是否为火山引擎的 Multimodal 专属 API（例如火山引擎的 Embedding Base URL 包含 volcengine 或 volces）
        is_volcengine_multimodal = is_vision and ("volcengine" in base_url.lower() or "volces" in base_url.lower())

        if is_volcengine_multimodal:
            try:
                # Multimodal API endpoint: /api/v3/embeddings/multimodal
                url = f"{base_url}/embeddings/multimodal"
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key or settings.EMBEDDING_API_KEY}"
                }
                
                # Format input for Volcengine multimodal schema
                multimodal_input = [{"type": "text", "text": doc} for doc in input]
                
                payload = {
                    "model": model_name,
                    "encoding_format": "float",
                    "input": multimodal_input
                }
                
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                
                # 设置 30 秒的合理超时时间
                with urllib.request.urlopen(req, timeout=30.0) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    
                if not isinstance(res_data, dict):
                    raise ValueError(f"API returned non-dictionary response: {res_data}")
                    
                if "error" in res_data:
                    raise ValueError(f"API returned error: {res_data['error']}")
                
                data_field = res_data.get("data", [])
                
                # Extract embeddings
                embeddings = []
                if isinstance(data_field, dict):
                    # Single dictionary format support: {"embedding": [...]}
                    embedding = data_field.get("embedding")
                    if isinstance(embedding, list):
                        embeddings.append(embedding)
                    else:
                        raise ValueError(f"Expected list for 'embedding' inside data dict: {data_field}")
                elif isinstance(data_field, list):
                    # Standard list format support: [{"embedding": [...]}, ...]
                    for item in data_field:
                        if isinstance(item, dict) and "embedding" in item:
                            embeddings.append(item["embedding"])
                        elif isinstance(item, list):
                            embeddings.append(item)
                        else:
                            raise ValueError(f"Unexpected item format in data list: {item}")
                else:
                    raise ValueError(f"API returned unexpected data field type: {type(data_field)}")
                        
                if embeddings and len(embeddings) > 0:
                    self.__class__._cached_dim = len(embeddings[0])
                return embeddings
            except Exception as e:
                print(f"==========================================")
                print(f"[WARNING] Multimodal Embedding API call failed: {e}")
                
                dim = self.__class__._cached_dim
                if dim is None:
                    dim = 2048  # Match the real model's default dimension of 2048
                print(f"[INFO] Falling back to zero-vector mock embeddings of dimension {dim}.")
                print(f"==========================================")
                return [[0.0] * dim for _ in input]
        else:
            # Standard Text API endpoint
            try:
                # 动态拦截并预初始化基础 OpenAI 客户端，配置超时时间（30.0s）
                if not hasattr(self, "_client"):
                    import openai
                    self._client = openai.OpenAI(
                        api_key=self.api_key or settings.EMBEDDING_API_KEY,
                        base_url=self.api_base or settings.EMBEDDING_BASE_URL,
                        timeout=30.0  # 稍微长一点的合理超时时间
                    )
                embeddings = super().__call__(input)
                if embeddings and len(embeddings) > 0:
                    self.__class__._cached_dim = len(embeddings[0])
                return embeddings
            except Exception as e:
                print(f"==========================================")
                print(f"[WARNING] Embedding API call failed: {e}")
                
                dim = self.__class__._cached_dim
                if dim is None:
                    model_lower = model_name.lower()
                    if "3-large" in model_lower:
                        dim = 3072
                    elif "ada-002" in model_lower or "3-small" in model_lower:
                        dim = 1536
                    elif "bge-large" in model_lower or "doubao" in model_lower:
                        dim = 1024
                    else:
                        dim = 1536
                
                print(f"[INFO] Falling back to zero-vector mock embeddings of dimension {dim}.")
                print(f"==========================================")
                return [[0.0] * dim for _ in input]

openai_ef = RobustOpenAIEmbeddingFunction(
    api_key=settings.EMBEDDING_API_KEY,
    api_base=settings.EMBEDDING_BASE_URL,
    model_name=settings.LLM_EMBEDDING_MODEL
)

# ── 大模型适配提供商兼容性代理 ──
# 作用：保持系统其他辅助模块（如 cognition_service、tts_service）的历史导入接口兼容
from services.llm_provider import get_llm_provider

class CompatibilitySyncLLMClient:
    @property
    def chat(self):
        provider = get_llm_provider()
        if hasattr(provider, "sync_client"):
            return provider.sync_client.chat
        raise AttributeError("The active LLM provider does not expose a standard sync client.")

class CompatibilityAsyncLLMClient:
    @property
    def chat(self):
        provider = get_llm_provider()
        if hasattr(provider, "async_client"):
            return provider.async_client.chat
        raise AttributeError("The active LLM provider does not expose a standard async client.")

llm_client = CompatibilitySyncLLMClient()
llm_client_async = CompatibilityAsyncLLMClient()

# LLM_MODEL 保留为全局默认值
LLM_MODEL = settings.ACTIVE_CHAT_MODEL
