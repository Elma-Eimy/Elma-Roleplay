import json
import base64
import struct
import os
import zlib
import re
import html
from copy import deepcopy


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
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        return _extract_v2_data(json.load(f))


def read_png_card_payloads(file_path: str) -> list[dict]:
    """读取所有有效 chara 元数据，保留顺序与原始字段，供导入和无损导出复用。"""
    payloads = []
    with open(file_path, 'rb') as f:
        if f.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError("不是有效的 PNG 文件。")
        while True:
            header = f.read(8)
            if not header:
                break
            if len(header) != 8:
                raise ValueError("PNG 数据块头不完整。")
            length, kind = struct.unpack('>I4s', header)
            # 防止损坏的长度声明触发巨大读取。
            if length > os.fstat(f.fileno()).st_size - f.tell() - 4:
                raise ValueError("PNG 数据块不完整。")
            content = f.read(length)
            crc = f.read(4)
            if len(crc) != 4:
                raise ValueError("PNG 校验字段不完整。")
            if kind == b'IEND':
                break
            if kind not in (b'tEXt', b'zTXt', b'iTXt'):
                continue
            keyword, separator, text = content.partition(b'\0')
            if keyword != b'chara' or not separator:
                continue
            try:
                if kind == b'zTXt':
                    if not text or text[0] != 0:
                        continue
                    text = _decompress_card_text(text[1:])
                elif kind == b'iTXt':
                    if len(text) < 2 or text[0] not in (0, 1) or text[1] != 0:
                        continue
                    compressed = text[0]
                    _, sep, rest = text[2:].partition(b'\0')
                    _, sep2, text = rest.partition(b'\0')
                    if not sep or not sep2:
                        continue
                    if compressed:
                        text = _decompress_card_text(text)
                try:
                    raw = json.loads(base64.b64decode(b''.join(text.split()), validate=True).decode('utf-8-sig'))
                except (ValueError, UnicodeError):
                    raw = json.loads(text.decode('utf-8-sig'))
                # 仅识别角色对象，避免误导入任意 JSON；失败块不遮蔽后续有效块。
                _validate_card_object(raw)
                payloads.append(raw)
            except (ValueError, UnicodeError, zlib.error):
                continue
    if not payloads:
        raise ValueError("PNG 中未找到有效的 chara 角色数据，请选择原始角色卡 PNG 或 JSON。")
    return payloads


def _decompress_card_text(data: bytes) -> bytes:
    decoder = zlib.decompressobj()
    text = decoder.decompress(data, 16 * 1024 * 1024 + 1)
    if len(text) > 16 * 1024 * 1024 or not decoder.eof:
        raise ValueError("角色卡文本损坏或解压后超过 16 MB。")
    return text


def _validate_card_object(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("角色卡 JSON 必须是对象。")
    data = raw.get('data', raw)
    if not isinstance(data, dict):
        raise ValueError("角色卡 data 必须是对象。")
    if not isinstance(data.get('name'), str) or not data['name'].strip():
        raise ValueError("角色卡缺少有效的 name 字段。")
    for key in ('description', 'personality', 'scenario', 'first_mes', 'mes_example',
                'creator_notes', 'system_prompt', 'system_prompt_override',
                'post_history_instructions', 'char_persona', 'world_scenario',
                'greeting', 'example_dialogue'):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError(f"角色卡 {key} 必须是文本。")
    for key in ('tags', 'alternate_greetings'):
        value = data.get(key)
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ValueError(f"角色卡 {key} 必须是字符串数组。")
    return data


def _parse_png_card(file_path: str) -> dict:
    # 同一 PNG 可有多个 chara 块：沿用首个有效块，不能让后续旧副本覆盖世界书。
    return _extract_v2_data(read_png_card_payloads(file_path)[0])


def _html_to_markdown(text: str) -> str:
    """
    将 HTML 标签自动转换为极简的 Markdown 格式，以节省 token 并避免干扰大模型。
    - 保留结构化标签 (加粗、斜体、删除线、列表、标题、分割线、换行) 对应的 Markdown 语法。
    - 剥离纯视觉修饰标签 (如 span style, div, mark 等)。
    - 解码 HTML 实体编码，并规范化连续的空行。
    """
    if text is None:
        return ""
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
    # 后续规范化不修改原始卡或第三方扩展。
    data = deepcopy(_validate_card_object(raw_data))

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
    # 作者信息随 extensions 持久化，不需要改变现有数据库结构。
    metadata = extensions.get("ai_roleplay_card")
    if metadata is None or isinstance(metadata, dict):
        metadata = dict(metadata or {})
        for key in ("creator", "character_version"):
            if isinstance(data.get(key), str):
                metadata[key] = data[key]
        for key in ("spec", "spec_version"):
            if isinstance(raw_data.get(key), str):
                metadata[key] = raw_data[key]
        if metadata:
            extensions["ai_roleplay_card"] = metadata
    if 'character_book' in data and data['character_book']:
        extensions['character_book'] = data['character_book']

    # 清洗 alternate_greetings 列表中的 HTML 为 Markdown
    alt_greetings = []
    for g in data.get("alternate_greetings", extensions.get("alternate_greetings", [])) or []:
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
        "tags": data.get("tags") or [],
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
