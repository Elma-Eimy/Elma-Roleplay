"""角色卡示例解析及无法结构化时的兼容回退。"""

import re
from .templates import replace_placeholders, _format_assistant_xml

EXAMPLE_MACRO_RE = re.compile(
    r"\{\{\s*(?:mesExamplesRaw|mesExamples|mes_examples|mes_example)\s*\}\}",
    re.IGNORECASE,
)


EXAMPLE_BLOCK_RE = re.compile(r"(?i)<START>")


_EXAMPLE_HEADER_RE = re.compile(
    r"(?im)^\s*(?:<START>|(?:#+\s*)?(?:Example|示例)\s*\d+(?:\s*[（(].*?[)）]|\s*[:：—-].*)?)\s*$"
)


_INLINE_SPEAKER_MACRO_RE = re.compile(
    r"(?<=\S)\s+(?=(?:"
    r"\{\{\s*(?:user|char|character)\s*\}\}|"
    r"<\s*(?:user|player|char|character|bot)\s*>|"
    r"\{\s*\$\s*(?:user|char|character)\s*\}"
    r")\s*[:：])",
    re.IGNORECASE,
)


EXAMPLE_CONTEXT_NOTE = (
    "【对话示例说明】\n"
    "以下示例仅用于参考说话方式、动作描写与互动节奏，不属于当前故事事实。"
)


EXAMPLE_END_NOTE = (
    "【对话示例结束】\n"
    "以上仅为角色卡风格示例，不属于当前故事历史；以下为真实聊天历史与本轮用户输入。"
)


def _prompt_embeds_dialogue_examples(character) -> bool:
    """角色卡显式使用示例宏时，禁止再次自动注入示例消息。"""
    prompt_fields = (
        character.system_prompt_override or "",
        character.post_history_instructions or "",
    )
    return any(EXAMPLE_MACRO_RE.search(text) for text in prompt_fields)


def _example_speaker_pattern(char_name: str, user_name: str) -> re.Pattern:
    """
    构造示例对话的发言者前缀匹配器。

    除标准 ``{{user}}:`` / ``{{char}}:`` 外，兼容角色卡中已经展开的昵称、
    常见英文别名、尖括号占位符和中文全角冒号。
    """
    user_labels = [
        r"\{\{\s*user\s*\}\}",
        r"<\s*user\s*>",
        r"<\s*player\s*>",
        re.escape(user_name),
        "user",
        "you",
        "player",
    ]
    char_labels = [
        r"\{\{\s*(?:char|character)\s*\}\}",
        r"<\s*(?:char|character|bot)\s*>",
        re.escape(char_name),
        "assistant",
        "character",
        "char",
        "bot",
        "ai",
    ]
    return re.compile(
        rf"^\s*(?:(?P<user>{'|'.join(user_labels)})|"
        rf"(?P<assistant>{'|'.join(char_labels)}))\s*[:：]\s*(?P<content>.*)$",
        re.IGNORECASE,
    )


def _split_example_blocks(raw_text: str) -> list[str]:
    """
    对齐 SillyTavern ``parseMesExamples`` 切分逻辑并扩展容错：
      1. 若文本不以 ``<START>`` 开头，保留首个 ``<START>`` 之前的非空隐式块（对齐 SillyTavern 自动前置 ``<START>`` 的行为）；
      2. 支持大小写不敏感的 ``<START>``（含同行 ``<START> {{user}}:``）切分；
      3. 额外支持独立行 ``Example 1（...）`` / ``示例 1`` 标题切分，防止标题串入上一轮消息。
    """
    blocks = []
    for part in EXAMPLE_BLOCK_RE.split(raw_text):
        for sub in _EXAMPLE_HEADER_RE.split(part):
            if sub.strip():
                blocks.append(sub)
    return blocks


def _parse_example_block(
    block: str,
    char_name: str,
    user_name: str,
) -> list[dict]:
    """把一个 ``<START>`` 示例块解析成 Chat Completion 消息。"""
    speaker_pattern = _example_speaker_pattern(char_name, user_name)
    normalized_block = _INLINE_SPEAKER_MACRO_RE.sub("\n", block)
    parsed_messages = []
    current_role = None
    current_lines = []

    def _flush_current_message() -> None:
        nonlocal current_role, current_lines
        if current_role is None:
            return
        content = "\n".join(current_lines).strip()
        if content:
            content = replace_placeholders(
                content,
                char_name,
                user_name,
            )
            if current_role == "assistant":
                content = _format_assistant_xml(content)
            parsed_messages.append(
                {
                    "role": current_role,
                    "content": content,
                }
            )
        current_role = None
        current_lines = []

    for line in normalized_block.splitlines():
        match = speaker_pattern.match(line)
        if match:
            _flush_current_message()
            current_role = "user" if match.group("user") else "assistant"
            current_lines = [match.group("content")]
        elif current_role is not None:
            current_lines.append(line)

    _flush_current_message()
    return parsed_messages


def compile_dialogue_examples(
    character,
    user_nickname: str = "用户",
) -> list[dict]:
    """
    将 SillyTavern ``mes_example`` 编译为独立的 user/assistant few-shot 消息。

    兼容策略：
      - 缺失、None、空字符串、纯空白和只有 <START> 的内容均返回空列表；
      - 非空且没有 <START> 时，按 SillyTavern 行为视为单个隐式示例块，同时支持
        独立 ``Example N`` / ``示例 N`` 标题切分与行内 ``{{char}}:`` / ``{{user}}:`` 自动换行；
      - 无法识别发言者前缀的非空块以 system 角色保守保留，避免静默丢数据。
    """
    raw_examples = getattr(character, "mes_example", None)
    if raw_examples is None:
        return []
    if not isinstance(raw_examples, str):
        raw_examples = str(raw_examples)
    raw_examples = raw_examples.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw_examples:
        return []

    blocks = _split_example_blocks(raw_examples)
    if not blocks:
        return []

    char_name = character.name or "AI"
    user_name = user_nickname or "用户"
    compiled_messages = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        parsed_block = _parse_example_block(block, char_name, user_name)
        if parsed_block:
            compiled_messages.extend(parsed_block)
        else:
            compiled_messages.append(
                {
                    "role": "system",
                    "content": (
                        "【未结构化对话示例】\n"
                        + replace_placeholders(block, char_name, user_name)
                    ),
                }
            )

    return compiled_messages
