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

    # 8. 规范化连续的空行，避免过多的冗余空行
    lines = [line.strip() for line in cleaned.split('\n')]
    result_lines = []
    for line in lines:
        if line:
            result_lines.append(line)
        elif not result_lines or result_lines[-1] != "":
            result_lines.append("")

    return "\n".join(result_lines).strip()

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
    system_prompt = data.get("system_prompt_override", data.get("system_prompt", ""))

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

    # 清洗 extensions 内的世界书 entries 的内容为 Markdown
    if 'character_book' in extensions and isinstance(extensions['character_book'], dict):
        char_book = extensions['character_book']
        if 'entries' in char_book and isinstance(char_book['entries'], list):
            for entry in char_book['entries']:
                if isinstance(entry, dict) and 'content' in entry:
                    entry['content'] = _html_to_markdown(entry['content'])

    # 归一化输出字段，包含完整的默认值以防 undefined 报错，并进行 HTML 到 Markdown 的格式清洗
    return {
        "name": _html_to_markdown(data.get("name", "")),
        "description": _html_to_markdown(description),
        "personality": _html_to_markdown(data.get("personality", "")),
        "scenario": _html_to_markdown(scenario),
        "first_mes": _html_to_markdown(first_mes),
        "mes_example": _html_to_markdown(mes_example),
        "creator_notes": _html_to_markdown(data.get("creator_notes", "")),
        "system_prompt_override": _html_to_markdown(system_prompt),
        "post_history_instructions": _html_to_markdown(data.get("post_history_instructions", "")),
        "tags": data.get("tags", []),
        "creator": _html_to_markdown(data.get("creator", "")),
        "character_version": data.get("character_version", ""),
        "alternate_greetings": alt_greetings,
        "extensions": extensions
    }
