import os
import re
import json
import hashlib
import base64
import httpx
import threading
from core.config import settings
from services.infrastructure.model_capabilities import auxiliary_controls

class TTSService:
    _instance = None
    _lock = threading.Lock()
    PREPROCESSOR_VERSION = "2"
    LONG_TEXT_THRESHOLD = 800
    MAX_SPOKEN_CHARS = 500
    PREPROCESS_MAX_TOKENS = 1024

    _ALLOWED_TTS_TAGS = {
        "开心", "悲伤", "愤怒", "恐惧", "惊讶", "兴奋", "委屈", "平静",
        "冷漠", "怅然", "欣慰", "无奈", "愧疚", "释然", "温柔", "高冷",
        "活泼", "严肃", "慵懒", "俏皮", "深沉", "疲惫", "撒娇", "紧张",
        "害怕", "激动", "颤抖", "吸气", "深呼吸", "叹气", "长叹一口气",
        "喘息", "轻笑", "大笑", "笑声", "哭声", "抽泣", "呜呜", "小声",
        "低声", "低沉", "语速加快", "提高音量", "唱歌", "sing",
    }

    def __init__(self):
        self.client = None

    def preprocess_roleplay_text_rules(self, text: str) -> str:
        """
        规则/正则预处理器：
        1. 匹配提取并解析动作/心理描写（包括 *...*、(...)、（...）、[...]、【...】、［...］、{...}、｛...｝）。
        2. 扫描动作描写中的情绪关键词，映射为 MiMo 原生支持的情感标签（如 [开心]）。
        3. 扫描动作描写中的声音事件关键词，转换为 MiMo 的声音标记（如 [叹气]、[吸气]）。
        4. 剔除所有纯肢体动作的描述（不发音），只保留人物对白以及情感和声音事件修饰，避免合成软件读出动作词。
        """
        if not text:
            return ""

        # 0. 预清洗：移去前缀角色名（如 "Sora: " 或 "Sora："）与首尾的双引号/单引号
        text = re.sub(r'^[a-zA-Z0-9_\u4e00-\u9fa5\s]+[:：]\s*', '', text)
        text = text.strip()
        text = re.sub(r'^["\'“「”」\s]+|["\'“「”」\s]+$', '', text)

        # 情绪关键词映射表 -> 对应 MiMo 风格标签
        emotions = {
            "悲伤": ["悲伤", "难过", "哭泣", "哀伤", "伤心", "委屈", "沮丧", "低落", "叹息"],
            "开心": ["开心", "高兴", "喜阅", "兴奋", "笑", "喜", "娇嗔", "快乐", "爽朗"],
            "愤怒": ["生气", "愤怒", "意难平", "脑火", "暴怒", "愤恨", "不满", "气愤", "咬牙"],
            "温柔": ["温柔", "体贴", "深情", "柔和", "宠溺", "轻声", "娇羞", "羞涩", "害羞"],
            "悄悄话": ["悄悄话", "耳语", "悄悄", "低语", "窃窃私语", "小声", "嘟囔"],
            "唱歌": ["唱歌", "哼歌", "唱"]
        }

        # 声音事件关键词映射表 -> 对应中括号拟人事件
        sound_events = {
            "叹气": ["叹气", "叹了口气", "叹息", "唉"],
            "笑声": ["笑声", "笑", "微笑", "吃吃地笑", "咯咯", "呵呵", "哈哈"],
            "哭泣": ["哭泣", "哭", "抽泣", "呜咽", "流泪", "啜泣"],
            "咳嗽": ["咳嗽", "咳", "清了清嗓子"],
            "吸气": ["吸气", "深呼吸", "喘气", "呼吸", "倒吸口凉气"]
        }

        # 匹配星号、中英文圆/方/花括号
        pattern = r'(?:\*([^*]+)\*|（([^）]+)）|\(([^)]+)\)|【([^】]+)】|\[([^\]]+)\]|［([^］]+)］|\{[^\}]+\}|｛[^｝]+｝)'

        def replace_match(match):
            content = None
            for g in match.groups():
                if g is not None:
                    content = g
                    break
            if not content:
                return ""

            content_str = content.strip()

            # 1. 检测是否包含情感词
            detected_style = None
            for style, keywords in emotions.items():
                if any(kw in content_str for kw in keywords):
                    detected_style = style
                    break

            # 2. 检测是否包含声音事件词
            detected_sound = None
            for sound, keywords in sound_events.items():
                if any(kw in content_str for kw in keywords):
                    if sound == "叹气":
                        detected_sound = "[叹气]"
                    elif sound == "笑声":
                        detected_sound = "[笑声]"
                    elif sound == "哭泣":
                        detected_sound = "[哭声]"
                    elif sound == "咳嗽":
                        detected_sound = "[咳嗽]"
                    elif sound == "吸气":
                        detected_sound = "[吸气]"
                    break

            result_parts = []
            if detected_style:
                result_parts.append(f"[{detected_style}]")
            if detected_sound:
                result_parts.append(detected_sound)

            # 如果检测到任何声音表情修饰，返回修饰，否则返回空字符串（剔除无关动作描述）
            if result_parts:
                return " " + " ".join(result_parts) + " "
            return ""

        # 执行替换
        cleaned_text = re.sub(pattern, replace_match, text)

        # 净化连续空格，清理两端
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        return cleaned_text

    def _normalize_style_tags(self, text: str) -> str:
        """
        兼容性处理：如果大模型依然输出了 <style>xxx</style>，转换为 [xxx] 格式
        """
        if not text:
            return ""
        return re.sub(r'<\s*style\s*>(.*?)</\s*style\s*>', r'[\1]', text, flags=re.IGNORECASE)

    def _build_preprocess_messages(
        self,
        text: str,
        character_name: str = None,
        force_compress: bool = False,
    ) -> list[dict]:
        target = (
            f"目标发音人是 {character_name}，只保留 {character_name} 说出口的内容，"
            "删除其他角色台词。"
            if character_name
            else "只保留主要说话人或当前 AI 角色说出口的内容。"
        )
        is_long = len(text) > self.LONG_TEXT_THRESHOLD
        mode = "强制压缩" if force_compress else ("长文本压缩" if is_long else "短文本提取")
        length_rule = (
            f"输出 spoken_text 不得超过 {self.MAX_SPOKEN_CHARS} 个字符。"
            "保留人名、地点、数字、承诺、警告、问题、结论和剧情关键事实；"
            "合并重复表达，删除铺垫和不影响含义的细节，并保持角色直接说话的口吻。"
            if is_long or force_compress
            else "尽量保留原台词，不要无故改写或总结。"
        )
        system_prompt = f"""你是角色扮演文本的 TTS 台词提炼器。当前模式：{mode}。

规则：
1. {target}
2. 删除纯物理动作、心理活动、场景叙述、说话人前缀和未发音的说明。
3. 保持目标台词原本使用的语言，不要翻译；中英文混合台词也保持原语言分布。
4. {length_rule}
5. 可在 spoken_text 中使用少量方括号情绪或声音标签，例如 [温柔]、[叹气]、[冷漠，低沉]；不要把动作描写伪装成标签。
6. 如果输入没有任何可发音台词，status 必须为 no_speech，spoken_text 必须为空。
7. 只能返回一个 JSON 对象，不要输出 Markdown 或解释：
{{"status":"ok|no_speech","spoken_text":"...","was_compressed":true|false}}
"""
        user_prompt = f"""示例（短文本）：
输入：*她轻轻笑了笑* “你终于来啦。”
输出：{{"status":"ok","spoken_text":"[温柔，轻笑]你终于来啦。","was_compressed":false}}

示例（只有旁白）：
输入：她走到窗前，把信放在桌上，然后沉默地离开。
输出：{{"status":"no_speech","spoken_text":"","was_compressed":false}}

示例（长文本压缩）：
输入：我今天去了旧城区，见到了管理员……（重复解释经过）……仓库钥匙还在北门值班室。所以明天千万不要独自过去，一定等我一起行动。
输出：{{"status":"ok","spoken_text":"[认真，严肃]仓库钥匙还在北门值班室。明天不要独自过去，等我一起行动。","was_compressed":true}}

待处理输入：
{text}
"""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _model_kwargs(self, model: str) -> dict:
        kwargs = auxiliary_controls("tts", 0.1, model)
        kwargs["max_tokens"] = self.PREPROCESS_MAX_TOKENS
        return kwargs

    def _normalize_control_tags(self, text: str) -> str:
        def normalize(match):
            raw = match.group(1).strip()
            parts = [
                part for part in re.split(r"[，,、\s]+", raw) if part
            ]
            if parts and all(part in self._ALLOWED_TTS_TAGS for part in parts):
                return f"[{', '.join(parts)}]"
            return ""

        return re.sub(r"\[([^\]]+)\]", normalize, text)

    def _sanitize_spoken_text(self, text: str) -> str:
        if not text:
            return ""
        text = self._normalize_style_tags(text)
        text = re.sub(
            r"^(?:输出|处理后|转换后|结果|整理后|规范文本|预处理结果|预处理后|清洗后)[:：\s]*",
            "",
            text.strip(),
        )
        text = re.sub(
            r"(?:\*[^*]+\*|（[^）]+）|\([^)]+\)|【[^】]+】|［[^］]+］|"
            r"\{[^}]+\}|｛[^｝]+｝)",
            "",
            text,
        )
        text = self._normalize_control_tags(text)
        return re.sub(r"\s+", " ", text).strip().strip("` ")

    def _parse_preprocess_response(self, response, source_text: str) -> str:
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason and finish_reason != "stop":
            raise ValueError(f"TTS 预处理响应未完整结束: {finish_reason}")

        content = (getattr(choice.message, "content", None) or "").strip()
        if not content:
            raise ValueError("TTS 预处理模型返回空正文")
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()

        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("TTS 预处理结果不是 JSON 对象")
        status = payload.get("status")
        if status == "no_speech":
            return ""
        if status != "ok" or not isinstance(payload.get("spoken_text"), str):
            raise ValueError("TTS 预处理结果缺少有效 status/spoken_text")

        spoken_text = self._sanitize_spoken_text(payload["spoken_text"])
        if not spoken_text:
            raise ValueError("TTS 预处理结果清洗后为空")
        if (
            len(source_text) > self.LONG_TEXT_THRESHOLD
            and len(spoken_text) > self.MAX_SPOKEN_CHARS
        ):
            raise ValueError(
                f"TTS 长文本未有效压缩: {len(spoken_text)} > "
                f"{self.MAX_SPOKEN_CHARS}"
            )
        return spoken_text

    def _truncate_spoken_text(self, text: str) -> str:
        if len(text) <= self.MAX_SPOKEN_CHARS:
            return text
        prefix = text[:self.MAX_SPOKEN_CHARS]
        cut = max(
            prefix.rfind(mark)
            for mark in ("。", "！", "？", ".", "!", "?", ";", "；")
        )
        if cut >= self.MAX_SPOKEN_CHARS // 2:
            prefix = prefix[:cut + 1]
        return prefix.rstrip() + "…"

    def _safe_fallback_extract(
        self,
        text: str,
        character_name: str = None,
    ) -> str:
        candidates = []
        quote_pattern = re.compile(
            r'“([^”]+)”|「([^」]+)」|『([^』]+)』|"([^"\r\n]+)"'
        )
        if character_name:
            speaker_pattern = re.compile(
                rf"(?im)^\s*{re.escape(character_name)}\s*[:：]\s*(.+)$"
            )
            for match in speaker_pattern.finditer(text):
                value = match.group(1).strip()
                quoted = [
                    next((group for group in item.groups() if group), "").strip()
                    for item in quote_pattern.finditer(value)
                ]
                for spoken in quoted or [value]:
                    if spoken and spoken not in candidates:
                        candidates.append(spoken)

        if not candidates:
            for match in quote_pattern.finditer(text):
                value = next(
                    (group for group in match.groups() if group), ""
                ).strip()
                if value and value not in candidates:
                    candidates.append(value)

        if candidates:
            return self._truncate_spoken_text(
                self._sanitize_spoken_text(" ".join(candidates))
            )
        if len(text) <= self.LONG_TEXT_THRESHOLD:
            return self._sanitize_spoken_text(
                self.preprocess_roleplay_text_rules(text)
            )
        return ""

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
                errors.append(str(exc))
                # 只有模型返回了可重试的格式/质量问题才再次调用；网络或供应商
                # 故障直接进入本地安全回退，避免等待两次超时。
                if not isinstance(exc, ValueError):
                    break
        print(f"[WARN] TTS LLM 预处理失败，使用安全台词提取: {'; '.join(errors)}")
        return self._safe_fallback_extract(text, character_name)

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
                errors.append(str(exc))
                if not isinstance(exc, ValueError):
                    break
        print(f"[WARN] (同步) TTS LLM 预处理失败，使用安全台词提取: {'; '.join(errors)}")
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

    async def generate_speech_async(self, text: str, voice: str = None, speed: float = 1.0, message_id: int = None, db = None) -> str:
        """
        异步方法：合成文本为音频 MP3 文件，自动进行哈希缓存，并返回相对于静态路由的音频 URL 路径。
        """
        if not settings.TTS_ENABLED:
            raise ValueError("TTS 语音合成服务在配置中已被禁用。")

        # 默认音色处理
        if not voice:
            voice = settings.TTS_DEFAULT_VOICE

        cache_dir = settings.TTS_CACHE_DIR
        os.makedirs(cache_dir, exist_ok=True)

        is_message_bound = False
        db_message = None

        character_name = None
        if message_id is not None and db is not None:
            from core.models import ChatMessage
            db_message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
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
                print(f"[WARN] 获取角色名称失败: {e}")

            # 检查数据库中是否存在 audio_path 且为 mp3 文件，且物理文件确实存在
            if (
                db_message.audio_path
                and os.path.basename(db_message.audio_path) == filename
            ):
                cached_filename = os.path.basename(db_message.audio_path)
                cached_filepath = os.path.join(cache_dir, cached_filename)
                if os.path.exists(cached_filepath) and os.path.getsize(cached_filepath) > 0:
                    print(f"[INFO] TTS (数据库绑定模式) 缓存命中: {cached_filepath}")
                    return db_message.audio_path
                else:
                    print(f"[WARN] TTS (数据库绑定模式) 物理文件已丢失或格式不符: {cached_filepath}，触发被动重建...")
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
                print(f"[INFO] TTS 缓存命中: {filepath}")
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

        print(f"[INFO] 正在调用 MIMO API 请求语音合成: '{text_clean[:20]}...' (voice={voice}, speed={speed})")

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    print(f"[ERROR] MIMO API 错误响应 (HTTP {response.status_code}): {response.text}")
                response.raise_for_status()
            except Exception as e:
                print(f"[ERROR] MIMO API 请求失败: {e}")
                raise RuntimeError(f"调用云端语音 API 失败: {str(e)}")

            # 兼容两种返回格式：
            # 1. 代理转换后的直接音频流 (Content-Type: audio/...)
            content_type = response.headers.get("content-type", "").lower()
            if "audio" in content_type:
                audio_bytes = response.content
                print(f"[INFO] 收到直接音频二进制流，大小: {len(audio_bytes) / 1024:.2f} KB")
            else:
                # 2. 小米官方的标准 JSON 响应，包含 Base64 数据
                try:
                    res_json = response.json()
                    audio_data_base64 = res_json["choices"][0]["message"]["audio"]["data"]
                    audio_bytes = base64.b64decode(audio_data_base64)
                    print(f"[INFO] 解析 JSON 成功，收到 Base64 编码音频，解码后大小: {len(audio_bytes) / 1024:.2f} KB")
                except KeyError as e:
                    print(f"[ERROR] 响应 JSON 结构不符合 MiMo API 规范: {response.text[:200]}")
                    raise RuntimeError("云端语音 API 返回格式异常。")
                except Exception as e:
                    print(f"[ERROR] 解析 JSON/解码 Base64 失败: {e}")
                    raise RuntimeError(f"解析语音数据失败: {str(e)}")

            # 写入本地缓存文件
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            print(f"[SUCCESS] 本地语音文件已缓存: {filepath}")
            
            # 绑定消息ID模式下，回写到数据库
            audio_url = f"/audio/{filename}"
            if is_message_bound and db_message:
                db_message.audio_path = audio_url
                db.commit()
                db.refresh(db_message)
                print(f"[INFO] 数据库记录已更新，将 audio_path 设为: {audio_url}")
            
            # 触发异步后台缓存清理
            threading.Thread(target=self._prune_cache_background, daemon=True).start()

        return audio_url

    def generate_speech_sync(self, text: str, voice: str = None, speed: float = 1.0, message_id: int = None, db = None) -> str:
        """
        同步方法：供测试脚本或非异步上下文使用
        """
        if not settings.TTS_ENABLED:
            raise ValueError("TTS 语音合成服务在配置中已被禁用。")

        if not voice:
            voice = settings.TTS_DEFAULT_VOICE

        cache_dir = settings.TTS_CACHE_DIR
        os.makedirs(cache_dir, exist_ok=True)

        is_message_bound = False
        db_message = None

        character_name = None
        if message_id is not None and db is not None:
            from core.models import ChatMessage
            db_message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
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
                print(f"[WARN] 获取角色名称失败: {e}")

            if (
                db_message.audio_path
                and os.path.basename(db_message.audio_path) == filename
            ):
                cached_filename = os.path.basename(db_message.audio_path)
                cached_filepath = os.path.join(cache_dir, cached_filename)
                if os.path.exists(cached_filepath) and os.path.getsize(cached_filepath) > 0:
                    print(f"[INFO] (同步) TTS (数据库绑定模式) 缓存命中: {cached_filepath}")
                    return db_message.audio_path
                else:
                    print(f"[WARN] (同步) TTS (数据库绑定模式) 物理文件已丢失或格式不符: {cached_filepath}，触发被动重建...")
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
                print(f"[INFO] (同步) TTS 缓存命中: {filepath}")
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

        print(f"[INFO] (同步) 正在调用 MIMO API 请求语音合成: '{text_clean[:20]}...' (voice={voice})")

        client = self._get_client()
        try:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                print(f"[ERROR] (同步) MIMO API 错误响应 (HTTP {response.status_code}): {response.text}")
            response.raise_for_status()
        except Exception as e:
            print(f"[ERROR] (同步) MIMO API 请求失败: {e}")
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
                print(f"[ERROR] (同步) 解析/解码失败: {e}. 响应内容: {response.text[:200]}")
                raise RuntimeError("解析云端语音响应失败")

        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        print(f"[SUCCESS] (同步) 本地语音文件已缓存: {filepath}")
        
        audio_url = f"/audio/{filename}"
        if is_message_bound and db_message:
            db_message.audio_path = audio_url
            db.commit()
            db.refresh(db_message)
            print(f"[INFO] (同步) 数据库记录已更新，将 audio_path 设为: {audio_url}")

        threading.Thread(target=self._prune_cache_background, daemon=True).start()

        return audio_url

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

            print(f"[INFO] [LRU 清理线程] 缓存音频文件数 ({len(files)}) 超过上限 ({max_files})，开始清理...")

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
                    print(f"[WARN] [LRU 清理线程] 无法删除缓存文件 {path}: {e}")

            print(f"[SUCCESS] [LRU 清理线程] 清理完成，共删除 {deleted_count} 个老音频文件。")
        except Exception as e:
            print(f"[ERROR] [LRU 清理线程] 清理缓存发生异常: {e}")
