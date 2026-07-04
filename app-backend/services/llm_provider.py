"""
大模型服务适配层 (LLM Provider Adapter Layer)

负责将具体的大模型 API 服务（如 OpenAI、DeepSeek、火山引擎、Claude 等）进行抽象和封装。
通过统一的接口，向上层业务模块提供：
1. 同步生成文本接口 (generate)
2. 异步生成文本接口 (generate_async)
3. 异步流式生成接口 (generate_stream_async)

本模块的设计遵循开闭原则 (OCP)，当未来接入其他非 OpenAI 协议的模型接口时，
只需继承 BaseLLMProvider 并实现相应方法，在 get_llm_provider() 工厂方法中配置即可，无需修改上层逻辑。
"""

import abc
from typing import Optional, Any, AsyncIterator
from openai import OpenAI, AsyncOpenAI
from core.config import settings


class BaseLLMProvider(abc.ABC):
    """
    大模型适配器抽象基类
    定义了上层服务所需要调用的核心文本/聊天接口，消除业务层对特定大模型 SDK 客户端实例的直接依赖。
    """

    @abc.abstractmethod
    def generate(self, model: str, messages: list, **kwargs) -> Any:
        """
        同步文本生成接口。
        
        Args:
            model: 模型名称或端点标识符。
            messages: 符合 ChatCompletion 格式的对话历史消息列表。
            **kwargs: 额外的可选大模型生成参数 (如 temperature, top_p, max_tokens, reasoning_effort 等)。
            
        Returns:
            标准的 ChatCompletion 响应对象或兼容的映射接口。
        """
        pass

    @abc.abstractmethod
    async def generate_async(self, model: str, messages: list, **kwargs) -> Any:
        """
        异步文本生成接口。
        
        Args:
            model: 模型名称或端点标识符。
            messages: 符合 ChatCompletion 格式的对话历史消息列表。
            **kwargs: 额外的可选大模型生成参数。
            
        Returns:
            标准的 ChatCompletion 响应对象或兼容的映射接口。
        """
        pass

    @abc.abstractmethod
    async def generate_stream_async(self, model: str, messages: list, **kwargs) -> Any:
        """
        异步流式文本生成接口。
        
        Args:
            model: 模型名称或端点标识符。
            messages: 符合 ChatCompletion 格式的对话历史消息列表。
            **kwargs: 额外的可选大模型生成参数。
            
        Returns:
            异步生成器，供流式推送 SSE chunks。
        """
        pass


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI 协议兼容模型的具体实现提供者。
    用于对接并封装 OpenAI, DeepSeek, 火山引擎 Ark, 零一万物等绝大多数标准 HTTP OpenAI-like API 格式。
    """

    def __init__(self):
        # 延迟初始化客户端实例，防止在系统启动初期 settings 尚未完全就绪时引发加载异常
        self._sync_client = None
        self._async_client = None

    @property
    def sync_client(self) -> OpenAI:
        """获取同步 OpenAI 兼容客户端单例"""
        if self._sync_client is None:
            self._sync_client = OpenAI(
                api_key=settings.CHAT_API_KEY,
                base_url=settings.CHAT_BASE_URL,
                timeout=settings.LLM_TIMEOUT
            )
        return self._sync_client

    @property
    def async_client(self) -> AsyncOpenAI:
        """获取异步 OpenAI 兼容客户端单例"""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=settings.CHAT_API_KEY,
                base_url=settings.CHAT_BASE_URL,
                timeout=settings.LLM_TIMEOUT
            )
        return self._async_client

    def generate(self, model: str, messages: list, **kwargs) -> Any:
        """
        调用同步客户端的 chat.completions.create 接口获取回复
        """
        return self.sync_client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )

    async def generate_async(self, model: str, messages: list, **kwargs) -> Any:
        """
        调用异步客户端的 chat.completions.create 接口获取回复
        """
        return await self.async_client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )

    async def generate_stream_async(self, model: str, messages: list, **kwargs) -> Any:
        """
        调用异步客户端开启 stream=True 的聊天流
        """
        kwargs["stream"] = True
        return await self.async_client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )


# 全局提供商单例对象
_global_provider = None


def get_llm_provider() -> BaseLLMProvider:
    """
    获取全局大模型提供商单例。
    
    目前系统默认注入 OpenAICompatibleProvider 实例以兼容标准接口。
    未来如果引入非标准大模型（如原生 Claude 接口或特定私有硬件加速接口），
    只需在此处根据 settings 配置规则，路由并生成不同的具体子类实例即可。
    """
    global _global_provider
    if _global_provider is None:
        _global_provider = OpenAICompatibleProvider()
    return _global_provider
