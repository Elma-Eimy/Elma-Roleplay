import json
import base64
import struct
import os
import zlib
import re
import html


def parse_character_card(file_path: str) -> dict:
    """
    解析角色卡片文件（支持 .json 和 .png 格式）
    返回一个包含符合 V2 规范角色数据的字典。
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.json':
        return _parse_json_card(file_path)
    elif ext == '.png':
        return _parse_png_card(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Only .json and .png are supported currently.")

def _parse_json_card(file_path: str) -> dict:
    """解析 JSON 格式的角色卡"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return _extract_v2_data(data)

def _parse_png_card(file_path: str) -> dict:
    """
    解析 SillyTavern PNG 角色卡 (无需第三方依赖)。
    角色数据通常以 base64 编码的 JSON 字符串形式存储在名为 'chara' 的 tEXt / zTXt / iTXt 数据块中。
    """
    with open(file_path, 'rb') as f:
        # 1. 验证 PNG 文件签名
        png_signature = b'\x89PNG\r\n\x1a\n'
        if f.read(len(png_signature)) != png_signature:
            raise ValueError("Not a valid PNG file.")

        # 2. 遍历 PNG 数据块 (Chunks)
        while True:
            length_bytes = f.read(4)
            if not length_bytes:
                break # 文件结束
            
            chunk_length = struct.unpack('>I', length_bytes)[0]
            chunk_type = f.read(4)
            chunk_data = f.read(chunk_length)
            f.read(4) # CRC32，跳过验证

            text_string = None

            # ── 2a. 解析 tEXt 块 (非压缩文本) ──
            if chunk_type == b'tEXt':
                try:
                    # tEXt 格式: Keyword (1-79 bytes) + \0 + Text string
                    decoded_text = chunk_data.decode('latin-1', errors='ignore') 
                    if '\0' in decoded_text:
                        keyword, content = decoded_text.split('\0', 1)
                        if keyword == 'chara':
                            text_string = content
                except Exception:
                    pass

            # ── 2b. 解析 zTXt 块 (Deflate 压缩文本) ──
            elif chunk_type == b'zTXt':
                try:
                    # zTXt 格式: Keyword (1-79 bytes) + \0 + Compression method (1 byte) + Compressed text
                    parts = chunk_data.split(b'\x00', 1)
                    if len(parts) == 2:
                        keyword = parts[0].decode('latin-1', errors='ignore')
                        if keyword == 'chara':
                            comp_data = parts[1]
                            if len(comp_data) > 1:
                                comp_method = comp_data[0]
                                compressed_text = comp_data[1:]
                                if comp_method == 0:  # 0 代表 zlib deflate
                                    decompressed = zlib.decompress(compressed_text)
                                    text_string = decompressed.decode('utf-8', errors='ignore')
                except Exception as e:
                    print(f"[WARN] Failed to decompress zTXt chunk: {e}")

            # ── 2c. 解析 iTXt 块 (国际 UTF-8 文本，支持压缩) ──
            elif chunk_type == b'iTXt':
                try:
                    # iTXt 格式: Keyword (1-79 bytes) + \0 + Compression flag (1 byte) + Compression method (1 byte) 
                    # + Language tag + \0 + Translated keyword + \0 + Text
                    idx1 = chunk_data.find(b'\x00')
                    if idx1 != -1:
                        keyword = chunk_data[:idx1].decode('latin-1', errors='ignore')
                        if keyword == 'chara':
                            comp_flag = chunk_data[idx1 + 1]
                            comp_method = chunk_data[idx1 + 2]
                            
                            # 查找 Language tag 结束的 \0
                            idx2 = chunk_data.find(b'\x00', idx1 + 3)
                            if idx2 != -1:
                                # 查找 Translated keyword 结束的 \0
                                idx3 = chunk_data.find(b'\x00', idx2 + 1)
                                if idx3 != -1:
                                    text_bytes = chunk_data[idx3 + 1:]
                                    if comp_flag == 1:
                                        if comp_method == 0:
                                            text_bytes = zlib.decompress(text_bytes)
                                    text_string = text_bytes.decode('utf-8', errors='ignore')
                except Exception as e:
                    print(f"[WARN] Failed to decode iTXt chunk: {e}")

            # 如果找到了 chara 关键字对应的内容，开始尝试解析
            if text_string is not None:
                # 尝试 base64 解码，失败则作为 raw JSON 解析
                try:
                    json_bytes = base64.b64decode(text_string)
                    json_str = json_bytes.decode('utf-8')
                    card_data = json.loads(json_str)
                    return _extract_v2_data(card_data)
                except Exception:
                    try:
                        card_data = json.loads(text_string)
                        return _extract_v2_data(card_data)
                    except Exception:
                        pass

    raise ValueError("No character data found in this PNG file.")

def _html_to_markdown(text: str) -> str:
    """
    将 HTML 标签自动转换为极简的 Markdown 格式，以节省 token 并避免干扰大模型。
    - 保留结构化标签 (加粗、斜体、删除线、列表、标题、分割线、换行) 对应的 Markdown 语法。
    - 剥离纯视觉修饰标签 (如 span style, div, mark 等)。
    - 解码 HTML 实体编码，并规范化连续的空行。
    """
    if not isinstance(text, str) or not text:
        return text

    # Protect placeholders like <char>, <user>, <character>, <player>, <bot> from being stripped as HTML tags
    placeholder_pattern = re.compile(r'<\s*(/?)\s*(char|character|user|player|bot)\s*>', re.IGNORECASE)
    placeholders_map = {}
    def protect(match):
        key = f"__PLACEHOLDER_{len(placeholders_map)}__"
        placeholders_map[key] = match.group(0)
        return key
    text = placeholder_pattern.sub(protect, text)

    # 1. 标题标签处理 (h1-h6 -> # 到 ######)
    text = re.sub(r'<h1\b[^>]*>', '\n# ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h2\b[^>]*>', '\n## ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h3\b[^>]*>', '\n### ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h4\b[^>]*>', '\n#### ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h5\b[^>]*>', '\n##### ', text, flags=re.IGNORECASE)
    text = re.sub(r'<h6\b[^>]*>', '\n###### ', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]\b[^>]*>', '\n', text, flags=re.IGNORECASE)

    # 2. 列表标签处理 (li -> - )
    text = re.sub(r'<li\b[^>]*>', '\n- ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li\b[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:ul|ol)\b[^>]*>', '\n', text, flags=re.IGNORECASE)

    # 3. 强调与排版样式转换 (加粗, 斜体, 删除线)
    text = re.sub(r'<(?:strong|b)\b[^>]*>', '**', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:strong|b)\b[^>]*>', '**', text, flags=re.IGNORECASE)
    text = re.sub(r'<(?:em|i)\b[^>]*>', '*', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:em|i)\b[^>]*>', '*', text, flags=re.IGNORECASE)
    text = re.sub(r'<(?:strike|s|del)\b[^>]*>', '~~', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:strike|s|del)\b[^>]*>', '~~', text, flags=re.IGNORECASE)

    # 4. 换行与分割线
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<hr\s*/?>', '\n---\n', text, flags=re.IGNORECASE)

    # 5. 常见分块标签换行
    text = re.sub(r'</?(?:p|div)\b[^>]*>', '\n', text, flags=re.IGNORECASE)

    # 6. 剔除所有其余无用 HTML 标签 (如 span, mark 等)
    cleaned = re.sub(r'<[^>]+>', '', text)

    # 7. 反转义 HTML 实体符号 (如 &quot; -> ", &amp; -> &)
    cleaned = html.unescape(cleaned)

    # Restore protected placeholders
    for key, original in placeholders_map.items():
        cleaned = cleaned.replace(key, original)

    # 8. 规范化连续的空行，避免过多的冗余空行
    lines = [line.strip() for line in cleaned.split('\n')]
    result_lines = []
    for line in lines:
        if line:
            result_lines.append(line)
        elif not result_lines or result_lines[-1] != "":
            result_lines.append("")

    return "\n".join(result_lines).strip()


def _normalize_prompt_text(text: str) -> str:
    """
    规范化角色卡中的 Prompt DSL，同时保留其原始语义结构。

    system prompt、Post-History Instructions、示例对话和世界书内容不是单纯的
    展示型 HTML。它们可能包含 ``{{original}}``、``<START>`` 或作者自定义的
    XML/伪 XML 标签，因此不能交给通用 HTML 清洗器删除尖括号结构。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _extract_v2_data(raw_data: dict) -> dict:
    """
    从原始 JSON 数据中提取符合 V2 规范的字段，并向后兼容 V1，确保输出字段的结构完全归一化。
    支持标准 chara_card_v2 结构以及 spec_v2 等变种。
    """
    # 提取主数据体（宽松匹配：只要有 data 字典，就直接认定为 V2 架构并下钻）
    data = raw_data
    if 'data' in raw_data and isinstance(raw_data['data'], dict):
        data = raw_data['data']

    # 映射旧字段或变种字段以兼容 V1 / 不同平台变种
    description = data.get("description", data.get("char_persona", ""))
    scenario = data.get("scenario", data.get("world_scenario", ""))
    first_mes = data.get("first_mes", data.get("greeting", ""))
    mes_example = data.get("mes_example", data.get("example_dialogue", ""))
    # 标准 V2 字段为 system_prompt；system_prompt_override 是本项目及部分平台
    # 使用的兼容别名。仅在别名具有非空内容时优先，避免空别名遮蔽标准字段。
    system_prompt = data.get("system_prompt_override") or data.get("system_prompt", "")

    # 融合 character_book (世界书/百科设定) 到 extensions 扩展中，实现零 schema 改动下的完美数据存储
    extensions = data.get("extensions", {})
    if not isinstance(extensions, dict):
        extensions = {}
    if 'character_book' in data and data['character_book']:
        extensions['character_book'] = data['character_book']

    # 清洗 alternate_greetings 列表中的 HTML 为 Markdown
    alt_greetings = []
    for g in data.get("alternate_greetings", []):
        if isinstance(g, str):
            alt_greetings.append(_html_to_markdown(g))
        else:
            alt_greetings.append(g)
            
    # 融合 alternate_greetings 到 extensions 以持久化存储
    extensions["alternate_greetings"] = alt_greetings

    # 世界书内容同样属于 Prompt DSL，保留作者定义的结构标签与宏。
    if 'character_book' in extensions and isinstance(extensions['character_book'], dict):
        char_book = extensions['character_book']
        if 'entries' in char_book and isinstance(char_book['entries'], list):
            for entry in char_book['entries']:
                if isinstance(entry, dict) and 'content' in entry:
                    entry['content'] = _normalize_prompt_text(entry['content'])

    # 归一化输出字段，包含完整的默认值以防 undefined 报错，并进行 HTML 到 Markdown 的格式清洗
    return {
        "name": _html_to_markdown(data.get("name", "")),
        "description": _html_to_markdown(description),
        "personality": _html_to_markdown(data.get("personality", "")),
        "scenario": _html_to_markdown(scenario),
        "first_mes": _html_to_markdown(first_mes),
        # 以下字段包含 SillyTavern Prompt DSL，不能删除 <START>、结构标签或宏。
        "mes_example": _normalize_prompt_text(mes_example),
        "creator_notes": _html_to_markdown(data.get("creator_notes", "")),
        "system_prompt_override": _normalize_prompt_text(system_prompt),
        "post_history_instructions": _normalize_prompt_text(data.get("post_history_instructions", "")),
        "tags": data.get("tags", []),
        "creator": _html_to_markdown(data.get("creator", "")),
        "character_version": data.get("character_version", ""),
        "alternate_greetings": alt_greetings,
        "extensions": extensions
    }


_REPLY_TAG_RE = re.compile(
    r"<\s*/?\s*(?:reply|replay)\s*>",
    re.IGNORECASE,
)
_MALFORMED_REPLY_CLOSE_RE = re.compile(
    r"</\s*(?:reply|replay)\s*(?=</|$)",
    re.IGNORECASE,
)
_STATUS_TAG_RE = re.compile(
    r"<\s*status\b([^>]*)/?>",
    re.IGNORECASE | re.DOTALL,
)
_STATUS_CLOSE_RE = re.compile(r"</\s*status\s*>", re.IGNORECASE)
_STATUS_ATTRIBUTE_RE = re.compile(
    r"\b(emotion|affection_change)\s*=\s*([\"'])(.*?)\2",
    re.IGNORECASE | re.DOTALL,
)
_STREAM_REPLY_END_RE = re.compile(
    r"</\s*(?:reply|replay)\s*>|<\s*status\b",
    re.IGNORECASE,
)


def extract_xml_block(text: str) -> dict:
    """容错解析模型的 ``reply/status`` 文本契约。

    模型输出不是可信 XML：它可能缺失开标签、重复包装、产生
    ``</reply</reply>``，或把 reply 拼成 replay。因此这里统一做宽松
    规范化，保证流式与非流式调用得到相同的纯正文，数据库中不残留包装
    标签。
    """
    if not text:
        return {"reply": "", "emotion_tag": "平静", "affection_change": 0}

    text = text.strip()
    status_match = _STATUS_TAG_RE.search(text)
    attributes = {}
    if status_match:
        attributes = {
            match.group(1).lower(): match.group(3).strip()
            for match in _STATUS_ATTRIBUTE_RE.finditer(status_match.group(1))
        }

    emotion_tag = attributes.get("emotion") or "平静"
    try:
        affection_change = int(attributes.get("affection_change") or 0)
    except (TypeError, ValueError):
        affection_change = 0

    # 删除所有外层或嵌套的 reply/replay 包装。与只截取首个闭标签相比，
    # 这种处理不会把嵌套开标签或残缺闭标签保存进正文。
    reply = _STATUS_TAG_RE.sub("", text)
    reply = _STATUS_CLOSE_RE.sub("", reply)
    reply = _REPLY_TAG_RE.sub("", reply)
    reply = _MALFORMED_REPLY_CLOSE_RE.sub("", reply)
    reply = reply.strip()

    return {
        "reply": reply,
        "emotion_tag": emotion_tag,
        "affection_change": affection_change,
    }


def extract_stream_reply_prefix(text: str) -> str:
    """解析当前流中可以视为正文的前缀，不让尾随 status 进入 SSE。

    未完整的控制标签由调用方的短尾部缓冲保护；一旦 reply 闭标签或 status
    起始完整可识别，就固定正文边界。
    """
    if not text:
        return ""
    end_match = _STREAM_REPLY_END_RE.search(text)
    reply_source = text[:end_match.start()] if end_match else text
    return extract_xml_block(reply_source)["reply"]


# 兼容性别名
_extract_xml_block = extract_xml_block
