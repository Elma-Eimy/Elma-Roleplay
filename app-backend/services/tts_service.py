import os
import hashlib
import base64
import httpx
import threading
import logging
from services.infrastructure.logging_context import diagnostic_task, log_event

logger = logging.getLogger(__name__)
from core.config import settings
from services.infrastructure.model_capabilities import auxiliary_controls
from services.media.tts_text import TTSTextProcessor

class TTSService(TTSTextProcessor):
    _instance = None
    _lock = threading.Lock()
    PREPROCESSOR_VERSION = "2"
    PREPROCESS_MAX_TOKENS = 1024

    def __init__(self):
        self.client = None

    def _model_kwargs(self, model: str) -> dict:
        kwargs = auxiliary_controls("tts", 0.1, model)
        kwargs["max_tokens"] = self.PREPROCESS_MAX_TOKENS
        return kwargs

    @diagnostic_task("tts-preprocess")
    async def preprocess_roleplay_text_llm(self, text: str, character_name: str = None) -> str:
        """异步提取 TTS 台词；长文本压缩，失败时安全降级。"""
        if not text or not text.strip():
            return ""

        from services.infrastructure.llm_provider import get_llm_provider
        model = settings.LLM_TTS_PREPROCESS_MODEL
        provider = get_llm_provider()
        errors = []
        for force_compress in (False, True):
            try:
                response = await provider.generate_async(
                    model=model,
                    messages=self._build_preprocess_messages(
                        text, character_name, force_compress
                    ),
                    **self._model_kwargs(model),
                )
                return self._parse_preprocess_response(response, text)
            except Exception as exc:
                errors.append(type(exc).__name__)
                # 只有模型返回了可重试的格式/质量问题才再次调用；网络或供应商
                # 故障直接进入本地安全回退，避免等待两次超时。
                if not isinstance(exc, ValueError):
                    break
        log_event(logger, logging.WARNING, "tts_preprocess_fallback", error_types=",".join(errors))
        return self._safe_fallback_extract(text, character_name)

    @diagnostic_task("tts-preprocess")
    def preprocess_roleplay_text_llm_sync(self, text: str, character_name: str = None) -> str:
        """同步提取 TTS 台词；与异步路径共用提示词、解析和回退规则。"""
        if not text or not text.strip():
            return ""

        from services.infrastructure.llm_provider import get_llm_provider
        model = settings.LLM_TTS_PREPROCESS_MODEL
        provider = get_llm_provider()
        errors = []
        for force_compress in (False, True):
            try:
                response = provider.generate(
                    model=model,
                    messages=self._build_preprocess_messages(
                        text, character_name, force_compress
                    ),
                    **self._model_kwargs(model),
                )
                return self._parse_preprocess_response(response, text)
            except Exception as exc:
                errors.append(type(exc).__name__)
                if not isinstance(exc, ValueError):
                    break
        log_event(logger, logging.WARNING, "tts_preprocess_fallback", error_types=",".join(errors))
        return self._safe_fallback_extract(text, character_name)

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = cls()
        return cls._instance

    def _get_client(self) -> httpx.Client:
        """获取同步 HTTP 客户端（仅用于非异步测试或回退逻辑）"""
        if not self.client:
            self.client = httpx.Client(timeout=60.0)
        return self.client

    @diagnostic_task("tts")
    async def generate_speech_async(self, text: str, voice: str = None, speed: float = 1.0, message_id: int = None, db = None) -> str:
        """
        异步方法：合成文本为音频 MP3 文件，自动进行哈希缓存，并返回相对于静态路由的音频 URL 路径。
        """
        db_message = None
        if message_id is not None and db is not None:
            from services.conversation.session_access import get_single_message
            db_message = get_single_message(message_id, db)

        if not settings.TTS_ENABLED:
            raise ValueError("TTS 语音合成服务在配置中已被禁用。")

        # 默认音色处理
        if not voice:
            voice = settings.TTS_DEFAULT_VOICE

        cache_dir = settings.TTS_CACHE_DIR
        os.makedirs(cache_dir, exist_ok=True)

        is_message_bound = False

        character_name = None
        if message_id is not None and db is not None:
            if not db_message:
                raise ValueError(f"Message ID {message_id} 在数据库中不存在。")
            
            # 使用数据库中的 content，保证合成文本一致性
            text = db_message.content
            is_message_bound = True

            # 预处理器升级时自动使用新缓存，避免继续播放旧版原文音频。
            filename = (
                f"msg_{message_id}_p{self.PREPROCESSOR_VERSION}_"
                f"{voice}_{speed:.2f}.mp3"
            )
            filepath = os.path.join(cache_dir, filename)

            # 尝试获取说话的角色名字以过滤旁白
            try:
                session = db_message.session
                if session and session.persona and session.persona.character:
                    character_name = session.persona.character.name
            except Exception as e:
                log_event(logger, logging.WARNING, "tts_character_lookup_failed", error_type=type(e).__name__)

            # 检查数据库中是否存在 audio_path 且为 mp3 文件，且物理文件确实存在
            if (
                db_message.audio_path
                and os.path.basename(db_message.audio_path) == filename
            ):
                cached_filename = os.path.basename(db_message.audio_path)
                cached_filepath = os.path.join(cache_dir, cached_filename)
                if os.path.exists(cached_filepath) and os.path.getsize(cached_filepath) > 0:
                    log_event(logger, logging.DEBUG, "tts_cache_hit")
                    return db_message.audio_path
                else:
                    log_event(logger, logging.INFO, "tts_cache_rebuild")
        else:
            if not text or not text.strip():
                raise ValueError("合成文本不能为空。")

        # 如果没有绑定消息ID，或者物理文件丢失需要重建/首次合成
        if not is_message_bound:
            # 普通文本模式：用原始 text 直接算 MD5
            # 注意：此处用 text 而不是 text_clean，能够 100% 避免重复播放时的 LLM 耗时及哈希抖动
            hash_input = (
                f"p{self.PREPROCESSOR_VERSION}_"
                f"{text.strip()}_{voice}_{speed:.2f}"
            )
            md5_hash = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            filename = f"{md5_hash}.mp3"
            filepath = os.path.join(cache_dir, filename)

            # 命中缓存，直接返回静态 URL
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                log_event(logger, logging.DEBUG, "tts_cache_hit")
                return f"/audio/{filename}"

        # 敏感词或密钥检查
        if not settings.MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY，无法调用云端语音合成接口。")

        # 文本清洗与规范化 (只在缓存未命中时才触发，极其节省 LLM API 开销和时间！)
        text_clean = await self.preprocess_roleplay_text_llm(text, character_name=character_name)
        if not text_clean or not text_clean.strip():
            raise ValueError("未检测到可安全合成的目标角色台词。")

        # 缓存未命中，调用云端 MIMO API
        url = f"{settings.TTS_MIMO_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.MIMO_API_KEY}",
            "Content-Type": "application/json"
        }

        # 准备 payload 结构，兼容 MiMo API 规格
        payload = {
            "model": settings.TTS_MIMO_MODEL,
            "messages": [
                {
                    "role": "assistant",
                    "content": text_clean
                }
            ],
            "audio": {
                "format": "mp3",
                "voice": voice
            }
        }
        
        # 如果语速不等于默认 1.0，则设置语速参数
        if speed != 1.0:
            payload["audio"]["speed"] = speed

        log_event(logger, logging.INFO, "tts_provider_requested")

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    log_event(logger, logging.ERROR, "tts_provider_rejected", status_code=response.status_code)
                response.raise_for_status()
            except Exception as e:
                log_event(logger, logging.ERROR, "tts_provider_failed", error_type=type(e).__name__)
                raise RuntimeError(f"调用云端语音 API 失败: {str(e)}")

            # 兼容两种返回格式：
            # 1. 代理转换后的直接音频流 (Content-Type: audio/...)
            content_type = response.headers.get("content-type", "").lower()
            if "audio" in content_type:
                audio_bytes = response.content
                log_event(logger, logging.DEBUG, "tts_audio_received", size_bytes=len(audio_bytes))
            else:
                # 2. 小米官方的标准 JSON 响应，包含 Base64 数据
                try:
                    res_json = response.json()
                    audio_data_base64 = res_json["choices"][0]["message"]["audio"]["data"]
                    audio_bytes = base64.b64decode(audio_data_base64)
                    log_event(logger, logging.DEBUG, "tts_audio_received", size_bytes=len(audio_bytes))
                except KeyError as e:
                    log_event(logger, logging.ERROR, "tts_response_invalid", phase="structure")
                    raise RuntimeError("云端语音 API 返回格式异常。")
                except Exception as e:
                    log_event(logger, logging.ERROR, "tts_response_invalid", phase="decode", error_type=type(e).__name__)
                    raise RuntimeError(f"解析语音数据失败: {str(e)}")

            # 写入本地缓存文件
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            log_event(logger, logging.INFO, "tts_audio_cached")
            
            # 绑定消息ID模式下，回写到数据库
            audio_url = f"/audio/{filename}"
            if is_message_bound and db_message:
                db_message.audio_path = audio_url
                db.commit()
                db.refresh(db_message)
                log_event(logger, logging.INFO, "tts_message_bound", message_id=message_id)
            
            # 触发异步后台缓存清理
            threading.Thread(target=self._prune_cache_background, daemon=True).start()

        return audio_url

    @diagnostic_task("tts")
    def generate_speech_sync(self, text: str, voice: str = None, speed: float = 1.0, message_id: int = None, db = None) -> str:
        """
        同步方法：供测试脚本或非异步上下文使用
        """
        db_message = None
        if message_id is not None and db is not None:
            from services.conversation.session_access import get_single_message
            db_message = get_single_message(message_id, db)

        if not settings.TTS_ENABLED:
            raise ValueError("TTS 语音合成服务在配置中已被禁用。")

        if not voice:
            voice = settings.TTS_DEFAULT_VOICE

        cache_dir = settings.TTS_CACHE_DIR
        os.makedirs(cache_dir, exist_ok=True)

        is_message_bound = False

        character_name = None
        if message_id is not None and db is not None:
            if not db_message:
                raise ValueError(f"Message ID {message_id} 在数据库中不存在。")
            
            text = db_message.content
            is_message_bound = True

            filename = (
                f"msg_{message_id}_p{self.PREPROCESSOR_VERSION}_"
                f"{voice}_{speed:.2f}.mp3"
            )
            filepath = os.path.join(cache_dir, filename)

            # 尝试获取说话的角色名字以过滤旁白
            try:
                session = db_message.session
                if session and session.persona and session.persona.character:
                    character_name = session.persona.character.name
            except Exception as e:
                log_event(logger, logging.WARNING, "tts_character_lookup_failed", error_type=type(e).__name__)

            if (
                db_message.audio_path
                and os.path.basename(db_message.audio_path) == filename
            ):
                cached_filename = os.path.basename(db_message.audio_path)
                cached_filepath = os.path.join(cache_dir, cached_filename)
                if os.path.exists(cached_filepath) and os.path.getsize(cached_filepath) > 0:
                    log_event(logger, logging.DEBUG, "tts_cache_hit")
                    return db_message.audio_path
                else:
                    log_event(logger, logging.INFO, "tts_cache_rebuild")
        else:
            if not text or not text.strip():
                raise ValueError("合成文本不能为空。")

        if not is_message_bound:
            hash_input = (
                f"p{self.PREPROCESSOR_VERSION}_"
                f"{text.strip()}_{voice}_{speed:.2f}"
            )
            md5_hash = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            filename = f"{md5_hash}.mp3"
            filepath = os.path.join(cache_dir, filename)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                log_event(logger, logging.DEBUG, "tts_cache_hit")
                return f"/audio/{filename}"

        if not settings.MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY，无法调用云端语音合成接口。")

        text_clean = self.preprocess_roleplay_text_llm_sync(text, character_name=character_name)
        if not text_clean or not text_clean.strip():
            raise ValueError("未检测到可安全合成的目标角色台词。")

        url = f"{settings.TTS_MIMO_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.MIMO_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": settings.TTS_MIMO_MODEL,
            "messages": [
                {
                    "role": "assistant",
                    "content": text_clean
                }
            ],
            "audio": {
                "format": "mp3",
                "voice": voice
            }
        }
        
        if speed != 1.0:
            payload["audio"]["speed"] = speed

        log_event(logger, logging.INFO, "tts_provider_requested")

        client = self._get_client()
        try:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                log_event(logger, logging.ERROR, "tts_provider_rejected", status_code=response.status_code)
            response.raise_for_status()
        except Exception as e:
            log_event(logger, logging.ERROR, "tts_provider_failed", error_type=type(e).__name__)
            raise RuntimeError(f"调用云端语音 API 失败: {str(e)}")

        content_type = response.headers.get("content-type", "").lower()
        if "audio" in content_type:
            audio_bytes = response.content
        else:
            try:
                res_json = response.json()
                audio_data_base64 = res_json["choices"][0]["message"]["audio"]["data"]
                audio_bytes = base64.b64decode(audio_data_base64)
            except Exception as e:
                log_event(logger, logging.ERROR, "tts_response_invalid", phase="decode", error_type=type(e).__name__)
                raise RuntimeError("解析云端语音响应失败")

        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        log_event(logger, logging.INFO, "tts_audio_cached")
        
        audio_url = f"/audio/{filename}"
        if is_message_bound and db_message:
            db_message.audio_path = audio_url
            db.commit()
            db.refresh(db_message)
            log_event(logger, logging.INFO, "tts_message_bound", message_id=message_id)

        threading.Thread(target=self._prune_cache_background, daemon=True).start()

        return audio_url

    @diagnostic_task("tts-cache")
    def _prune_cache_background(self):
        """
        后台线程：检查缓存目录中的文件数量，如果超过设定的最大值，
        则根据文件的最后修改时间（mtime）从小到大排序，删除最老的文件，
        实现 LRU (Least Recently Used) 淘汰机制。
        """
        try:
            cache_dir = settings.TTS_CACHE_DIR
            max_files = settings.TTS_MAX_CACHE_FILES

            if not os.path.exists(cache_dir):
                return

            # 获取目录下所有 mp3 文件及其修改时间
            files = []
            for f in os.listdir(cache_dir):
                if f.endswith(".mp3"):
                    p = os.path.join(cache_dir, f)
                    try:
                        files.append((p, os.path.getmtime(p)))
                    except OSError:
                        continue

            # 如果文件总数未超限，直接返回
            if len(files) <= max_files:
                return

            log_event(logger, logging.INFO, "tts_cache_prune_started", count=len(files), max_files=max_files)

            # 按照修改时间排序（从旧到新）
            files.sort(key=lambda x: x[1])

            # 需要删除的文件数量
            to_delete_count = len(files) - max_files
            files_to_delete = files[:to_delete_count]

            deleted_count = 0
            for path, _ in files_to_delete:
                try:
                    os.remove(path)
                    deleted_count += 1
                except OSError as e:
                    log_event(logger, logging.WARNING, "tts_cache_delete_failed", error_type=type(e).__name__)

            log_event(logger, logging.INFO, "tts_cache_prune_completed", count=deleted_count)
        except Exception as e:
            log_event(logger, logging.ERROR, "tts_cache_prune_failed", error_type=type(e).__name__)
