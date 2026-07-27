import os
import re
import hashlib
import base64
import httpx
import threading
from core.config import settings

class TTSService:
    _instance = None
    _lock = threading.Lock()

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

    async def preprocess_roleplay_text_llm(self, text: str, character_name: str = None) -> str:
        """
        至臻 LLM 预处理器：
        使用快速的大模型（如 deepseek-v4-flash）进行语义分析，剔除纯物理动作/旁白/场景叙述，
        提取情感、语气和发声事件并转化为 MiMo v2.5 官方支持的 [风格/情绪/动作] 方括号控制标签，并合理嵌入到台词对白的不同位置。
        """
        if not text or not text.strip():
            return ""

        from services.infrastructure.llm_provider import get_llm_provider
        from core.config import settings

        target_info = f"当前目标发音人是：【{character_name}】。你必须仅提取【{character_name}】说出口的台词对白，把它们转换为规范的语音合成文本，并剔除其他角色的台词以及所有旁白叙述。" if character_name else "当前你需要提取主要说话人（或AI角色本身）说出口的台词对白，并把它们转换为规范的语音合成文本，剔除旁白和动作描述。"

        system_prompt = (
            "你是一个角色扮演对话的语音合成文本预处理器。你的任务是把一段混杂了动作描写、心理描写、场景叙述和多人对话的文本，整理并转换成专门用于小米 MiMo 语音合成（TTS）的规范文本。\n\n"
            "处理规则：\n"
            f"1. {target_info}\n"
            "   - 必须绝对剔除所有的纯物理动作、心理活动、场景叙述和对话前缀（例如：“她微微一笑说道：‘你好呀。’”中的“她微微一笑说道：”；或者“我走过去坐下。今天天气真好。”中的“我走过去坐下。”都必须被剔除）。\n"
            "   - 台词中原本就包含的口语语气发音词（例如“唉”、“哼”、“呜呜”、“哈哈”、“嘿”、“呀”、“啊”、“哦”等），绝对不能删除，必须在台词原样中保留！\n"
            "   - 如果有其他角色的台词（如“Reina: '...'”），而目标不是该角色，必须将其彻底舍弃。\n"
            "2. 在提取出的台词开头添加整体的情绪/风格标签，格式为 [风格] 待合成内容。支持同时设置多种风格，将多个风格置于同一个方括号内，如 [温柔 怅然] 或 [冷漠，低沉]。\n"
            "   推荐基础情绪风格：开心/悲伤/愤怒/恐惧/惊讶/兴奋/委屈/平静/冷漠/怅然/欣慰/无奈/愧疚/释然/温柔/高冷/活泼/严肃/慵懒/俏皮/深沉等。\n"
            "3. 如果台词中包含多种不同的心情、语气转变或声音特效，支持在文本的中间或任意位置插入细粒度方括号控制标签，格式为 [音频标签]。\n"
            "   推荐细粒度标签：吸气/深呼吸/叹气/长叹一口气/喘息/紧张/害怕/激动/疲惫/撒娇/颤抖/轻笑/大笑/抽泣/呜呜/小声/语速加快/提高音量等。\n"
            "   （如需体验唱歌，必须在歌词前加上 [唱歌] 或 [sing] 标签）。\n"
            "4. 保证输出连贯，只包含提取出的台词与相应的 [风格/控制] 方括号标签。不要添加任何其他解释、说明或 Markdown 代码块包裹（如 ```）。"
        )

        user_content = (
            "示例 1：\n"
            "输入：*叹了口气，有些伤心地低下头* 唉，今天在学校真的好累啊。 *轻声笑了笑* 不过，只要一见到你，我所有的疲惫就全部烟消云散啦！\n"
            "输出：[悲伤，叹气]唉，今天在学校真的好累啊。[开心，轻笑]不过，只要一见到你，我所有的疲惫就全部烟消云散啦！\n\n"
            "示例 2：\n"
            "输入：*她咬了紧下唇，有些委屈地撒娇* \"你...你昨天怎么没来找我嘛...\" *拉扯着你的衣袖*\n"
            "输出：[委屈，吸气]\"你...你昨天怎么没来找我嘛...\"\n\n"
            "示例 3：\n"
            "输入：我没事。（叹了口气）只是有点累了。\n"
            "输出：[温柔，疲惫]我没事。[长叹一口气]只是有点累了。\n\n"
            "示例 4：\n"
            "输入：【摸摸头】别伤心了，有我在呢。\n"
            "输出：[温柔]别伤心了，有我在呢。\n\n"
            "示例 5：\n"
            "输入：她微微一笑说道：“你终于来啦。”\n"
            "输出：[温柔，轻笑]“你终于来啦。”\n\n"
            "示例 6（目标角色为 Vera）：\n"
            "输入：Reina Kuroda sat behind a desk. Reina: \"Volkov movement near the eastern ports.\"\n"
            "Now, Vera stood in the shadow. She drew her sidearm and pointed it directly at your chest.\n"
            "Vera: \"This is the first time we work together. So listen carefully.\"\n"
            "Her voice was low, unhurried.\n"
            "Vera: \"Do not slow me down. Be useful, or I will kill you myself.\"\n"
            "输出：[高冷，严肃]“This is the first time we work together. So listen carefully。”[冷漠，低沉]“Do not slow me down. Be useful, or I will kill you myself。”\n\n"
            f"输入：{text}\n"
            "输出："
        )

        try:
            model = settings.CHAT_MODEL_NON_REASONING
            provider = get_llm_provider()
            response = await provider.generate_async(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.3,
                max_tokens=1024
            )
            result = response.choices[0].message.content.strip()
            if result.startswith("```"):
                result = re.sub(r"^```[a-zA-Z]*\n|```$", "", result).strip()
            
            # 兼容性处理：如果大模型依然输出了 <style>xxx</style>，转换为 [xxx] 格式
            result = self._normalize_style_tags(result)
            
            # Post-processing 双重清理过滤：
            # 1. 移去 "输出："、"处理后：" 等前缀词
            result = re.sub(r'^(?:输出|处理后|转换后|结果|整理后|规范文本|预处理结果|预处理后|清洗后)[:：\s]*', '', result)
            result = re.sub(r'^.*?如下[:：\s]*', '', result, flags=re.IGNORECASE)
            
            # 2. 规范化：统一把所有的（风格/发声）或 (风格/发声) 转换为 [风格/发声]
            def normalize_brackets(match):
                content = next((g for g in match.groups() if g is not None), "").strip()
                if content and len(content) <= 12:
                    return f"[{content}]"
                return match.group(0)
            
            result = re.sub(r'(?:（([^）]+)）|\(([^)]+)\)|［([^］]+)］|【([^】]+)】)', normalize_brackets, result)
            
            # 3. 提取并保护所有的方括号控制标签，用占位符替换以防被强力清理规则过滤
            tags = []
            def protect_tag(match):
                tags.append(match.group(0))
                return f"___TAG_{len(tags)-1}___"
            
            result_protected = re.sub(r'\[([^\]]+)\]', protect_tag, result)

            # 4. 强力防漏：剔除任何可能残留的 *动作* 以及非标签的肢体叙述（不匹配被保护的方括号，只剔除多余的圆括号、花括号、方头括号等）
            result_cleaned = re.sub(r'(?:\*[^*]+\*|（[^）]+）|\([^)]+\)|【[^】]+】|［[^］]+］|\{[^\}]+\}|｛[^｝]+｝)', '', result_protected)
            
            # 5. 还原所有的方括号控制标签
            for i, tag in enumerate(tags):
                result_cleaned = result_cleaned.replace(f"___TAG_{i}___", tag)
            
            result = re.sub(r'\s+', ' ', result_cleaned).strip()
            return result
        except Exception as e:
            import traceback
            print(f"[WARN] LLM 预处理失败，回退使用正则规则预处理器。详细报错原因:")
            traceback.print_exc()
            return self.preprocess_roleplay_text_rules(text)

    def preprocess_roleplay_text_llm_sync(self, text: str, character_name: str = None) -> str:
        """
        同步LLM 预处理器，供同步接口或测试调用。
        """
        if not text or not text.strip():
            return ""

        from services.infrastructure.llm_provider import get_llm_provider
        from core.config import settings

        target_info = f"当前目标发音人是：【{character_name}】。你必须仅提取【{character_name}】说出口的台词对白，把它们转换为规范的语音合成文本，并剔除其他角色的台词以及所有旁白叙述。" if character_name else "当前你需要提取主要说话人（或AI角色本身）说出口的台词对白，并把它们转换为规范的语音合成文本，剔除旁白和动作描述。"

        system_prompt = (
            "你是一个角色扮演对话的语音合成文本预处理器。你的任务是把一段混杂了动作描写、心理描写、场景叙述和多人对话的文本，整理并转换成专门用于小米 MiMo 语音合成（TTS）的规范文本。\n\n"
            "处理规则：\n"
            f"1. {target_info}\n"
            "   - 必须绝对剔除所有的纯物理动作、心理活动、场景叙述和对话前缀（例如：“她微微一笑说道：‘你好呀。’”中的“她微微一笑说道：”；或者“我走过去坐下。今天天气真好。”中的“我走过去坐下。”都必须被剔除）。\n"
            "   - 台词中原本就包含的口语语气发音词（例如“唉”、“哼”、“呜呜”、“哈哈”、“嘿”、“呀”、“啊”、“哦”等），绝对不能删除，必须在台词原样中保留！\n"
            "   - 如果有其他角色的台词（如“Reina: '...'”），而目标不是该角色，必须将其彻底舍弃。\n"
            "2. 在提取出的台词开头添加整体的情绪/风格标签，格式为 [风格] 待合成内容。支持同时设置多种风格，将多个风格置于同一个方括号内，如 [温柔 怅然] 或 [冷漠，低沉]。\n"
            "   推荐基础情绪风格：开心/悲伤/愤怒/恐惧/惊讶/兴奋/委屈/平静/冷漠/怅然/欣慰/无奈/愧疚/释然/温柔/高冷/活泼/严肃/慵懒/俏皮/深沉等。\n"
            "3. 如果台词中包含多种不同的心情、语气转变或声音特效，支持在文本的中间或任意位置插入细粒度方括号控制标签，格式为 [音频标签]。\n"
            "   推荐细粒度标签：吸气/深呼吸/叹气/长叹一口气/喘息/紧张/害怕/激动/疲惫/撒娇/颤抖/轻笑/大笑/抽泣/呜呜/小声/语速加快/提高音量等。\n"
            "   （如需体验唱歌，必须在歌词前加上 [唱歌] 或 [sing] 标签）。\n"
            "4. 保证输出连贯，只包含提取出的台词与相应的 [风格/控制] 方括号标签。不要添加任何其他解释、说明或 Markdown 代码块包裹（如 ```）。"
        )

        user_content = (
            "示例 1：\n"
            "输入：*叹了口气，有些伤心地低下头* 唉，今天在学校真的好累啊。 *轻声笑了笑* 不过，只要一见到你，我所有的疲惫就全部烟消云散啦！\n"
            "输出：[悲伤，叹气]唉，今天在学校真的好累啊。[开心，轻笑]不过，只要一见到你，我所有的疲惫就全部烟消云散啦！\n\n"
            "示例 2：\n"
            "输入：*她咬了玩下唇，有些委屈地撒娇* \"你...你昨天怎么没来找我嘛...\" *拉扯着你的衣袖*\n"
            "输出：[委屈，吸气]\"你...你昨天怎么没来找我嘛...\"\n\n"
            "示例 3：\n"
            "输入：我没事。（叹了口气）只是有点累了。\n"
            "输出：[温柔，疲惫]我没事。[长叹一口气]只是有点累了。\n\n"
            "示例 4：\n"
            "输入：【摸摸头】别伤心了，有我在呢。\n"
            "输出：[温柔]别伤心了，有我在呢。\n\n"
            "示例 5：\n"
            "输入：她微微一笑说道：“你终于来啦。”\n"
            "输出：[温柔，轻笑]“你终于来啦。”\n\n"
            "示例 6（目标角色为 Vera）：\n"
            "输入：Reina Kuroda sat behind a desk. Reina: \"Volkov movement near the eastern ports.\"\n"
            "Now, Vera stood in the shadow. She drew her sidearm and pointed it directly at your chest.\n"
            "Vera: \"This is the first time we work together. So listen carefully.\"\n"
            "Her voice was low, unhurried.\n"
            "Vera: \"Do not slow me down. Be useful, or I will kill you myself.\"\n"
            "输出：[高冷，严肃]“This is the first time we work together. So listen carefully。”[冷漠，低沉]“Do not slow me down. Be useful, or I will kill you myself。”\n\n"
            f"输入：{text}\n"
            "输出："
        )

        try:
            model = settings.CHAT_MODEL_NON_REASONING
            provider = get_llm_provider()
            response = provider.generate(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.3,
                max_tokens=1024
            )
            result = response.choices[0].message.content.strip()
            if result.startswith("```"):
                result = re.sub(r"^```[a-zA-Z]*\n|```$", "", result).strip()
            
            # 兼容性处理：如果大模型依然输出了 <style>xxx</style>，转换为 [xxx] 格式
            result = self._normalize_style_tags(result)
            
            # Post-processing 双重清理过滤：
            # 1. 移去 "输出："、"处理后：" 等前缀词
            result = re.sub(r'^(?:输出|处理后|转换后|结果|整理后|规范文本|预处理结果|预处理后|清洗后)[:：\s]*', '', result)
            result = re.sub(r'^.*?如下[:：\s]*', '', result, flags=re.IGNORECASE)
            
            # 2. 规范化：统一把所有的（风格/发声）或 (风格/发声) 转换为 [风格/发声]
            def normalize_brackets(match):
                content = next((g for g in match.groups() if g is not None), "").strip()
                if content and len(content) <= 12:
                    return f"[{content}]"
                return match.group(0)
            
            result = re.sub(r'(?:（([^）]+)）|\(([^)]+)\)|［([^］]+)］|【([^】]+)】)', normalize_brackets, result)
            
            # 3. 提取并保护所有的方括号控制标签，用占位符替换以防被强力清理规则过滤
            tags = []
            def protect_tag(match):
                tags.append(match.group(0))
                return f"___TAG_{len(tags)-1}___"
            
            result_protected = re.sub(r'\[([^\]]+)\]', protect_tag, result)

            # 4. 强力防漏：剔除任何可能残留的 *动作* 以及非标签的肢体叙述（不匹配被保护的方括号，只剔除多余的圆括号、花括号、方头括号等）
            result_cleaned = re.sub(r'(?:\*[^*]+\*|（[^）]+）|\([^)]+\)|【[^】]+】|［[^］]+］|\{[^\}]+\}|｛[^｝]+｝)', '', result_protected)
            
            # 5. 还原所有的方括号控制标签
            for i, tag in enumerate(tags):
                result_cleaned = result_cleaned.replace(f"___TAG_{i}___", tag)
            
            result = re.sub(r'\s+', ' ', result_cleaned).strip()
            return result
        except Exception as e:
            import traceback
            print(f"[WARN] (同步) LLM 预处理失败，回退使用正则规则预处理器。详细报错原因:")
            traceback.print_exc()
            return self.preprocess_roleplay_text_rules(text)

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

            # 命名为：msg_{message_id}_{voice}_{speed:.2f}.mp3
            filename = f"msg_{message_id}_{voice}_{speed:.2f}.mp3"
            filepath = os.path.join(cache_dir, filename)

            # 尝试获取说话的角色名字以过滤旁白
            try:
                session = db_message.session
                if session and session.persona and session.persona.character:
                    character_name = session.persona.character.name
            except Exception as e:
                print(f"[WARN] 获取角色名称失败: {e}")

            # 检查数据库中是否存在 audio_path 且为 mp3 文件，且物理文件确实存在
            if db_message.audio_path and db_message.audio_path.endswith(".mp3"):
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
            hash_input = f"{text.strip()}_{voice}_{speed:.2f}"
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
            text_clean = text.strip()

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

            filename = f"msg_{message_id}_{voice}_{speed:.2f}.mp3"
            filepath = os.path.join(cache_dir, filename)

            # 尝试获取说话的角色名字以过滤旁白
            try:
                session = db_message.session
                if session and session.persona and session.persona.character:
                    character_name = session.persona.character.name
            except Exception as e:
                print(f"[WARN] 获取角色名称失败: {e}")

            if db_message.audio_path and db_message.audio_path.endswith(".mp3"):
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
            hash_input = f"{text.strip()}_{voice}_{speed:.2f}"
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
            text_clean = text.strip()

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
