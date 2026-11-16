"""TTS 文本策略：提示词、清洗、响应校验与安全回退，不访问模型或文件。"""
import json
import re


class TTSTextProcessor:
    LONG_TEXT_THRESHOLD = 800

    MAX_SPOKEN_CHARS = 500

    _ALLOWED_TTS_TAGS = {
        "开心", "悲伤", "愤怒", "恐惧", "惊讶", "兴奋", "委屈", "平静",
        "冷漠", "怅然", "欣慰", "无奈", "愧疚", "释然", "温柔", "高冷",
        "活泼", "严肃", "慵懒", "俏皮", "深沉", "疲惫", "撒娇", "紧张",
        "害怕", "激动", "颤抖", "吸气", "深呼吸", "叹气", "长叹一口气",
        "喘息", "轻笑", "大笑", "笑声", "哭声", "抽泣", "呜呜", "小声",
        "低声", "低沉", "语速加快", "提高音量", "唱歌", "sing",
    }

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
