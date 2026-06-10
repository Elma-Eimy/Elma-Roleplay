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
        2. 扫描动作描写中的情绪关键词，映射为 MiMo 原生支持的情感标签（如 <style>开心</style>）。
        3. 扫描动作描写中的声音事件关键词，转换为 MiMo 的声音标记（如 （叹气）、[inhale]）。
        4. 剔除所有纯肢体动作的描述（不发音），只保留人物对白以及情感和声音事件修饰，避免合成软件读出动作词。
        """
        if not text:
            return ""

        # 情绪关键词映射表 -> 对应 MiMo 风格标签
        emotions = {
            "悲伤": ["悲伤", "难过", "哭泣", "哀伤", "伤心", "委屈", "沮丧", "低落", "叹息"],
            "开心": ["开心", "高兴", "喜阅", "兴奋", "笑", "喜", "娇嗔", "快乐", "爽朗"],
            "愤怒": ["生气", "愤怒", "意难平", "脑火", "暴怒", "愤恨", "不满", "气愤", "咬牙"],
            "温柔": ["温柔", "体贴", "深情", "柔和", "宠溺", "轻声", "娇羞", "羞涩", "害羞"],
            "悄悄话": ["悄悄话", "耳语", "悄悄", "低语", "窃窃私语", "小声", "嘟囔"],
            "唱歌": ["唱歌", "哼歌", "唱"]
        }

        # 声音事件关键词映射表 -> 对应中文括号拟人事件
        sound_events = {
            "叹气": ["叹气", "叹了口气", "叹息", "唉"],
            "笑声": ["笑声", "笑", "微笑", "吃吃地笑", "咯咯", "呵呵", "哈哈"],
            "哭泣": ["哭泣", "哭", "抽泣", "呜咽", "流泪", "啜泣"],
            "咳嗽": ["咳嗽", "咳", "清了清嗓子"],
            "吸气": ["吸气", "深呼吸", "喘气", "呼吸", "倒戏口凉气"]
        }

        # 匹配星号、中英文圆/方/花括号
        pattern = r'(?:\*([^*]+)\*|（([^）]+)）|\(([^)]+)\)|【([^】]+)】|\[([^\]]+)\]|［([^］]+)］|\{([^\}]+)\}|｛([^｝]+)｝)'

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
                        detected_sound = "（叹气）"
                    elif sound == "笑声":
                        detected_sound = "（笑声）"
                    elif sound == "哭泣":
                        detected_sound = "（哭声）"
                    elif sound == "咳嗽":
                        detected_sound = "（咳嗽）"
                    elif sound == "吸气":
                        detected_sound = "[inhale]"
                    break

            result_parts = []
            if detected_style:
                result_parts.append(f"<style>{detected_style}</style>")
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
        将任何非标准 style 标签映射到 MiMo 支持的 6 个标准情感：
        开心、悲伤、愤怒、温柔、悄悄话、唱歌
        """
        if not text:
            return ""
            
        emotions_map = {
            "悲伤": ["悲伤", "难过", "哭", "哀", "伤心", "委屈", "沮", "低落", "叹", "伤感", "疲惫", "累"],
            "开心": ["开心", "高兴", "喜", "兴奋", "笑", "娇嗔", "快乐", "爽朗", "甜蜜", "激动"],
            "愤怒": ["生气", "愤怒", "意难平", "脑", "暴怒", "愤", "不满", "气", "咬牙"],
            "温柔": ["温柔", "体贴", "深情", "柔", "宠", "轻声", "娇羞", "羞", "害羞", "温暖", "欣慰", "平静"],
            "悄悄话": ["悄悄话", "耳语", "悄悄", "低语", "窃窃私语", "小声", "嘟囔"],
            "唱歌": ["唱歌", "哼歌", "唱"]
        }
        
        def replace_style(match):
            style_val = match.group(1).strip()
            # 寻找匹配的标准类别
            for std_style, keywords in emotions_map.items():
                if style_val == std_style or any(kw in style_val for kw in keywords):
                    return f"<style>{std_style}</style>"
            # 如果未找到任何匹配，默认转为温柔
            return "<style>温柔</style>"
            
        # 替换所有的 <style>...</style>
        return re.sub(r'<\s*style\s*>(.*?)</\s*style\s*>', replace_style, text, flags=re.IGNORECASE)

    async def preprocess_roleplay_text_llm(self, text: str) -> str:
        """
        至臻 LLM 预处理器：
        使用快速的大模型（如 deepseek-v4-flash）进行语义分析，剔除无关的肢体动作/心理描写，
        提取语气与声效并映射为 MiMo 原生支持的情感标签（如 <style>开心</style>）与声效标记（如 （叹气）、[inhale]）。
        """
        if not text or not text.strip():
            return ""

        # 避免循环引用，在方法内部动态引入
        from services.chat_engine import llm_client_async
        from core.config import settings

        system_prompt = (
            "你是一个角色扮演对话的语音合成文本预处理器。你的任务是把一段混杂了动作描写、心理描写、场景叙述和角色台词的文本，整理并转换成专门用于小米 MiMo 语音合成（TTS）的规范文本。\n\n"
            "处理规则：\n"
            "1. 仅保留角色说出口的台词对白。台词可能被双引号包裹，也可能没有符号包裹。必须绝对剔除所有的物理动作、心理活动、场景叙述和对话前缀（例如：“她微微一笑说道：‘你好呀。’”中的“她微微一笑说道：”；或者“我走过去坐下。今天天气真好。”中的“我走过去坐下。”都必须被剔除）。\n"
            "2. 不管这些动作描写、心理描写、旁白或叙述是用星号（*）、圆括号（()、（））、方括号（[]、［］、【】）包裹，还是没有任何包裹（直接作为普通文本写在句中），一律必须彻底删除，绝不能出现在输出结果中！\n"
            "3. 提取动作描述或台词本身的情绪与语气，使用以下 MiMo 原生支持的 XML 样式标签包裹对应的台词（或放在台词开头）：\n"
            "   - <style>开心</style>：适用于高兴、喜悦、兴奋、娇嗔、撒娇、笑等情绪。\n"
            "   - <style>悲伤</style>：适用于难过、哭泣、哀伤、伤心、委屈、沮丧、低落等情绪。\n"
            "   - <style>愤怒</style>：适用于生气、愤怒、意难平、脑火、暴怒、不满等情绪。\n"
            "   - <style>温柔</style>：适用于温柔、体贴、深情、柔和、宠溺、轻声、娇羞、害羞等语气或情绪。\n"
            "   - <style>悄悄话</style>：适用于耳语、低语、窃窃私语、小声、嘟囔等。\n"
            "   - <style>唱歌</style>：适用于唱歌、哼歌等。\n"
            "4. 提取台词中或动作中的声效/声音事件，并转换成以下原生声音标记插入到合适的位置：\n"
            "   - （叹气）\n"
            "   - （笑声）\n"
            "   - （哭声）\n"
            "   - （咳嗽）\n"
            "   - [inhale] (吸气/深呼吸)\n"
            "   注意：这些声音标记（如“（叹气）”等）应当只在原句中确实有叹气、笑声等发音事件时才保留，动作描写本身如“拍了拍你的肩”、“转过头去”等物理动作绝对不应保留。\n"
            "5. 保证输出连贯，只包含经过处理的台词与相应的 <style> 和声音标记。不要添加任何其他解释、说明或 Markdown 代码块包裹（如 ```）。如果输入文本包含台词，绝对不能输出为空白。"
        )

        user_content = (
            "示例 1：\n"
            "输入：*她咬了咬下唇，有些委屈地撒娇* \"你...你昨天怎么没来找我嘛...\" *拉扯着你的衣袖*\n"
            "输出：<style>悲伤</style>\"你...你昨天怎么没来找我嘛...\"\n\n"
            "示例 2：\n"
            "输入：我没事。（叹了口气）只是有点累了。\n"
            "输出：<style>温柔</style>我没事。（叹气）只是有点累了。\n\n"
            "示例 3：\n"
            "输入：我红着脸，有些不好意思地低下头。其实，我也很想你。\n"
            "输出：<style>温柔</style>其实，我也很想你。\n\n"
            "示例 4：\n"
            "输入：【摸摸头】别伤心了，有我在呢。\n"
            "输出：<style>温柔</style>别伤心了，有我在呢。\n\n"
            "示例 5：\n"
            "输入：她微微一笑说道：“你终于来啦。”\n"
            "输出：<style>温柔</style>“你终于来啦。”\n\n"
            f"输入：{text}\n"
            "输出："
        )

        try:
            model = settings.CHAT_MODEL_NON_REASONING
            response = await llm_client_async.chat.completions.create(
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
            # 情感标签标准化
            result = self._normalize_style_tags(result)
            
            # Post-processing 双重清理过滤：
            # 1. 移去 "输出："、"处理后："、"规范文本如下：" 等大模型前缀词
            result = re.sub(r'^(?:输出|处理后|转换后|结果|整理后|规范文本|预处理结果|预处理后|清洗后)[:：\s]*', '', result)
            result = re.sub(r'^.*?如下[:：\s]*', '', result, flags=re.IGNORECASE)
            
            # 保护声音标记：暂时替换为特有的占位符，避免被强力清理规则误杀
            result = result.replace("（叹气）", "___SIGH___")
            result = result.replace("（笑声）", "___LAUGH___")
            result = result.replace("（哭声）", "___CRY___")
            result = result.replace("（咳嗽）", "___COUGH___")
            result = result.replace("[inhale]", "___INHALE___")

            # 2. 强力防漏：剔除任何可能残留的 *动作*、(动作)、（动作）以及各类方括号、花括号内的肢体叙述
            result = re.sub(r'(?:\*[^*]+\*|（[^）]+）|\([^)]+\)|【[^】]+】|\[[^\]]+\]|［[^］]+］|\{[^\}]+\}|｛[^｝]+｝)', '', result)
            
            # 还原声音标记
            result = result.replace("___SIGH___", "（叹气）")
            result = result.replace("___LAUGH___", "（笑声）")
            result = result.replace("___CRY___", "（哭声）")
            result = result.replace("___COUGH___", "（咳嗽）")
            result = result.replace("___INHALE___", "[inhale]")
            
            result = re.sub(r'\s+', ' ', result).strip()

            print(f"[INFO] LLM 预处理成功：原文本='{text}' -> 预处理文本='{result}'")
            return result
        except Exception as e:
            print(f"[WARN] LLM 预处理失败: {e}，回退使用正则规则预处理器。")
            return self.preprocess_roleplay_text_rules(text)

    def preprocess_roleplay_text_llm_sync(self, text: str) -> str:
        """
        同步至臻 LLM 预处理器，供同步接口或测试调用。
        """
        if not text or not text.strip():
            return ""

        from services.chat_engine import llm_client
        from core.config import settings

        system_prompt = (
            "你是一个角色扮演对话的语音合成文本预处理器。你的任务是把一段混杂了动作描写、心理描写、场景叙述和角色台词的文本，整理并转换成专门用于小米 MiMo 语音合成（TTS）的规范文本。\n\n"
            "处理规则：\n"
            "1. 仅保留角色说出口的台词对白。台词可能被双引号包裹，也可能没有符号包裹。必须绝对剔除所有的物理动作、心理活动、场景叙述和对话前缀（例如：“她微微一笑说道：‘你好呀。’”中的“她微微一笑说道：”；或者“我走过去坐下。今天天气真好。”中的“我走过去坐下。”都必须被剔除）。\n"
            "2. 不管这些动作描写、心理描写、旁白或叙述是用星号（*）、圆括号（()、（））、方括号（[]、［］、【】）包裹，还是没有任何包裹（直接作为普通文本写在句中），一律必须彻底删除，绝不能出现在输出结果中！\n"
            "3. 提取动作描述或台词本身的情绪与语气，使用以下 MiMo 原生支持的 XML 样式标签包裹对应的台词（或放在台词开头）：\n"
            "   - <style>开心</style>：适用于高兴、喜悦、兴奋、娇嗔、撒娇、笑等情绪。\n"
            "   - <style>悲伤</style>：适用于难过、哭泣、哀伤、伤心、委屈、沮丧、低落等情绪。\n"
            "   - <style>愤怒</style>：适用于生气、愤怒、意难平、脑火、暴怒、不满等情绪。\n"
            "   - <style>温柔</style>：适用于温柔、体贴、深情、柔和、宠溺、轻声、娇羞、害羞等语气或情绪。\n"
            "   - <style>悄悄话</style>：适用于耳语、低语、窃窃私语、小声、嘟囔等。\n"
            "   - <style>唱歌</style>：适用于唱歌、哼歌等。\n"
            "4. 提取台词中或动作中的声效/声音事件，并转换成以下原生声音标记插入到合适的位置：\n"
            "   - （叹气）\n"
            "   - （笑声）\n"
            "   - （哭声）\n"
            "   - （咳嗽）\n"
            "   - [inhale] (吸气/深呼吸)\n"
            "   注意：这些声音标记（如“（叹气）”等）应当只在原句中确实有叹气、笑声等发音事件时才保留，动作描写本身如“拍了拍你的肩”、“转过头去”等物理动作绝对不应保留。\n"
            "5. 保证输出连贯，只包含经过处理的台词与相应的 <style> 和声音标记。不要添加任何其他解释、说明或 Markdown 代码块包裹（如 ```）。如果输入文本包含台词，绝对不能输出为空白。"
        )

        user_content = (
            "示例 1：\n"
            "输入：*她咬了咬下唇，有些委屈地撒娇* \"你...你昨天怎么没来找我嘛...\" *拉扯着你的衣袖*\n"
            "输出：<style>悲伤</style>\"你...你昨天怎么没来找我嘛...\"\n\n"
            "示例 2：\n"
            "输入：我没事。（叹了口气）只是有点累了。\n"
            "输出：<style>温柔</style>我没事。（叹气）只是有点累了。\n\n"
            "示例 3：\n"
            "输入：我红着脸，有些不好意思地低下头。其实，我也很想你。\n"
            "输出：<style>温柔</style>其实，我也很想你。\n\n"
            "示例 4：\n"
            "输入：【摸摸头】别伤心了，有我在呢。\n"
            "输出：<style>温柔</style>别伤心了，有我在呢。\n\n"
            "示例 5：\n"
            "输入：她微微一笑说道：“你终于来啦。”\n"
            "输出：<style>温柔</style>“你终于来啦。”\n\n"
            f"输入：{text}\n"
            "输出："
        )

        try:
            model = settings.CHAT_MODEL_NON_REASONING
            response = llm_client.chat.completions.create(
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
            # 情感标签标准化
            result = self._normalize_style_tags(result)
            
            # Post-processing 双重清理过滤：
            # 1. 移去 "输出："、"处理后："、"规范文本如下：" 等大模型前缀词
            result = re.sub(r'^(?:输出|处理后|转换后|结果|整理后|规范文本|预处理结果|预处理后|清洗后)[:：\s]*', '', result)
            result = re.sub(r'^.*?如下[:：\s]*', '', result, flags=re.IGNORECASE)
            
            # 保护声音标记：暂时替换为特有的占位符，避免被强力清理规则误杀
            result = result.replace("（叹气）", "___SIGH___")
            result = result.replace("（笑声）", "___LAUGH___")
            result = result.replace("（哭声）", "___CRY___")
            result = result.replace("（咳嗽）", "___COUGH___")
            result = result.replace("[inhale]", "___INHALE___")

            # 2. 强力防漏：剔除任何可能残留的 *动作*、(动作)、（动作）以及各类方括号、花括号内的肢体叙述
            result = re.sub(r'(?:\*[^*]+\*|（[^）]+）|\([^)]+\)|【[^】]+】|\[[^\]]+\]|［[^］]+］|\{[^\}]+\}|｛[^｝]+｝)', '', result)
            
            # 还原声音标记
            result = result.replace("___SIGH___", "（叹气）")
            result = result.replace("___LAUGH___", "（笑声）")
            result = result.replace("___CRY___", "（哭声）")
            result = result.replace("___COUGH___", "（咳嗽）")
            result = result.replace("___INHALE___", "[inhale]")
            
            result = re.sub(r'\s+', ' ', result).strip()

            print(f"[INFO] (同步) LLM 预处理成功：原文本='{text}' -> 预处理文本='{result}'")
            return result
        except Exception as e:
            print(f"[WARN] (同步) LLM 预处理失败: {e}，回退使用正则规则预处理器。")
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
        异步方法：合成文本为音频 WAV 文件，自动进行哈希缓存，并返回相对于静态路由的音频 URL 路径。
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

        if message_id is not None and db is not None:
            from core.models import ChatMessage
            db_message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
            if not db_message:
                raise ValueError(f"Message ID {message_id} 在数据库中不存在。")
            
            # 使用数据库中的 content，保证合成文本一致性
            text = db_message.content
            is_message_bound = True

            # 命名为：msg_{message_id}_{voice}_{speed:.2f}.wav
            filename = f"msg_{message_id}_{voice}_{speed:.2f}.wav"
            filepath = os.path.join(cache_dir, filename)

            # 检查数据库中是否存在 audio_path 且物理文件确实存在
            if db_message.audio_path:
                cached_filename = os.path.basename(db_message.audio_path)
                cached_filepath = os.path.join(cache_dir, cached_filename)
                if os.path.exists(cached_filepath) and os.path.getsize(cached_filepath) > 0:
                    print(f"[INFO] TTS (数据库绑定模式) 缓存命中: {cached_filepath}")
                    return db_message.audio_path
                else:
                    print(f"[WARN] TTS (数据库绑定模式) 物理文件已丢失: {cached_filepath}，触发被动重建...")
        else:
            if not text or not text.strip():
                raise ValueError("合成文本不能为空。")

        # 如果没有绑定消息ID，或者物理文件丢失需要重建/首次合成
        if not is_message_bound:
            # 普通文本模式：用原始 text 直接算 MD5
            # 注意：此处用 text 而不是 text_clean，能够 100% 避免重复播放时的 LLM 耗时及哈希抖动
            hash_input = f"{text.strip()}_{voice}_{speed:.2f}"
            md5_hash = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            filename = f"{md5_hash}.wav"
            filepath = os.path.join(cache_dir, filename)

            # 命中缓存，直接返回静态 URL
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"[INFO] TTS 缓存命中: {filepath}")
                return f"/audio/{filename}"

        # 敏感词或密钥检查
        if not settings.MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY，无法调用云端语音合成接口。")

        # 文本清洗与规范化 (只在缓存未命中时才触发，极其节省 LLM API 开销和时间！)
        text_clean = await self.preprocess_roleplay_text_llm(text)
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
                "format": "wav",
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

        if message_id is not None and db is not None:
            from core.models import ChatMessage
            db_message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
            if not db_message:
                raise ValueError(f"Message ID {message_id} 在数据库中不存在。")
            
            text = db_message.content
            is_message_bound = True

            filename = f"msg_{message_id}_{voice}_{speed:.2f}.wav"
            filepath = os.path.join(cache_dir, filename)

            if db_message.audio_path:
                cached_filename = os.path.basename(db_message.audio_path)
                cached_filepath = os.path.join(cache_dir, cached_filename)
                if os.path.exists(cached_filepath) and os.path.getsize(cached_filepath) > 0:
                    print(f"[INFO] (同步) TTS (数据库绑定模式) 缓存命中: {cached_filepath}")
                    return db_message.audio_path
                else:
                    print(f"[WARN] (同步) TTS (数据库绑定模式) 物理文件已丢失: {cached_filepath}，触发被动重建...")
        else:
            if not text or not text.strip():
                raise ValueError("合成文本不能为空。")

        if not is_message_bound:
            hash_input = f"{text.strip()}_{voice}_{speed:.2f}"
            md5_hash = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
            filename = f"{md5_hash}.wav"
            filepath = os.path.join(cache_dir, filename)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"[INFO] (同步) TTS 缓存命中: {filepath}")
                return f"/audio/{filename}"

        if not settings.MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY，无法调用云端语音合成接口。")

        text_clean = self.preprocess_roleplay_text_llm_sync(text)
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
                "format": "wav",
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

            # 获取目录下所有 wav 文件及其修改时间
            files = []
            for f in os.listdir(cache_dir):
                if f.endswith(".wav"):
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
