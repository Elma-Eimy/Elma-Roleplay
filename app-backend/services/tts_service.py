import os
from dataclasses import dataclass
import httpx
import threading
import logging
from services.infrastructure.logging_context import diagnostic_task, log_event

logger = logging.getLogger(__name__)
from core.config import settings
from services.infrastructure.model_capabilities import auxiliary_controls
from services.infrastructure.tts_provider import build_speech_request, request_speech_async, request_speech_sync
from services.media.tts_text import TTSTextProcessor
from services.media.tts_cache import TTSAudioCache, prune_cache


@dataclass(frozen=True)
class _PreparedSpeech:
    text: str
    voice: str
    character_name: str | None
    cache: TTSAudioCache
    message: object = None
    cached_url: str | None = None


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
        prepared = self._prepare_speech(text, voice, speed, message_id, db)
        if prepared.cached_url is not None:
            return prepared.cached_url
        text, voice, character_name = prepared.text, prepared.voice, prepared.character_name

        # 敏感词或密钥检查
        if not settings.MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY，无法调用云端语音合成接口。")

        # 文本清洗与规范化 (只在缓存未命中时才触发，极其节省 LLM API 开销和时间！)
        text_clean = await self.preprocess_roleplay_text_llm(text, character_name=character_name)
        if not text_clean or not text_clean.strip():
            raise ValueError("未检测到可安全合成的目标角色台词。")

        # 缓存未命中，调用云端 MIMO API
        url, headers, payload = build_speech_request(
            text_clean, voice, speed, base_url=settings.TTS_MIMO_BASE_URL,
            api_key=settings.MIMO_API_KEY, model=settings.TTS_MIMO_MODEL,
        )

        log_event(logger, logging.INFO, "tts_provider_requested")

        async with httpx.AsyncClient(timeout=60.0) as client:
            audio_bytes = await request_speech_async(client, url, headers, payload, logger=logger)

            audio_url = self._save_speech(prepared, audio_bytes, message_id, db)

        return audio_url

    @diagnostic_task("tts")
    def generate_speech_sync(self, text: str, voice: str = None, speed: float = 1.0, message_id: int = None, db = None) -> str:
        """
        同步方法：供测试脚本或非异步上下文使用
        """
        prepared = self._prepare_speech(text, voice, speed, message_id, db)
        if prepared.cached_url is not None:
            return prepared.cached_url
        text, voice, character_name = prepared.text, prepared.voice, prepared.character_name

        if not settings.MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY，无法调用云端语音合成接口。")

        text_clean = self.preprocess_roleplay_text_llm_sync(text, character_name=character_name)
        if not text_clean or not text_clean.strip():
            raise ValueError("未检测到可安全合成的目标角色台词。")

        url, headers, payload = build_speech_request(
            text_clean, voice, speed, base_url=settings.TTS_MIMO_BASE_URL,
            api_key=settings.MIMO_API_KEY, model=settings.TTS_MIMO_MODEL,
        )

        log_event(logger, logging.INFO, "tts_provider_requested")

        client = self._get_client()
        audio_bytes = request_speech_sync(client, url, headers, payload, logger=logger)

        return self._save_speech(prepared, audio_bytes, message_id, db)

    def _prepare_speech(self, text, voice, speed, message_id, db):
        """共用消息读取与缓存判定；保留类型检查、禁用检查和缺失消息的先后顺序。"""
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

            cache = TTSAudioCache.for_message(
                cache_dir, message_id, self.PREPROCESSOR_VERSION, voice, speed,
            )

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
                and os.path.basename(db_message.audio_path) == cache.filename
            ):
                if cache.is_ready():
                    log_event(logger, logging.DEBUG, "tts_cache_hit")
                    return _PreparedSpeech(text, voice, character_name, cache, db_message, db_message.audio_path)
                else:
                    log_event(logger, logging.INFO, "tts_cache_rebuild")
        else:
            if not text or not text.strip():
                raise ValueError("合成文本不能为空。")

        if not is_message_bound:
            cache = TTSAudioCache.for_text(
                cache_dir, text, self.PREPROCESSOR_VERSION, voice, speed,
            )
            if cache.is_ready():
                log_event(logger, logging.DEBUG, "tts_cache_hit")
                return _PreparedSpeech(text, voice, character_name, cache, cached_url=cache.audio_url)

        return _PreparedSpeech(text, voice, character_name, cache, db_message)

    def _save_speech(self, prepared, audio_bytes, message_id, db):
        """先写文件再提交绑定；沿用调用方 Session，不另开事务或转交线程。"""
        prepared.cache.write(audio_bytes)
        log_event(logger, logging.INFO, "tts_audio_cached")
        audio_url = prepared.cache.audio_url
        if prepared.message:
            prepared.message.audio_path = audio_url
            db.commit()
            db.refresh(prepared.message)
            log_event(logger, logging.INFO, "tts_message_bound", message_id=message_id)
        threading.Thread(target=self._prune_cache_background, daemon=True).start()
        return audio_url

    @diagnostic_task("tts-cache")
    def _prune_cache_background(self):
        """保留后台清理入口，文件淘汰由缓存模块执行。"""
        try:
            prune_cache(settings.TTS_CACHE_DIR, settings.TTS_MAX_CACHE_FILES, logger=logger)
        except Exception as exc:
            log_event(logger, logging.ERROR, "tts_cache_prune_failed", error_type=type(exc).__name__)
