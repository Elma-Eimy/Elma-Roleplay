import re
from typing import Optional

def replace_placeholders(text: str, char_name: str, user_name: str) -> str:
    """
    替换文本中的 char/user 占位符。
    支持变体：
      - {{char}} / {{user}}
      - <char> / <character> / <user>
      - {$char} / {$character} / {$user}
    支持不区分大小写，且容忍大括号/尖括号内的空格。
    使用 lambda 函数避免用户昵称/角色名中的特殊字符 (如 \, $) 造成正则转义或捕获组错误。
    """
    if not text:
        return text

    # 1. 替换 {{char}} / {{user}}
    pattern_curly = re.compile(r'\{\{\s*(char|user)\s*\}\}', re.IGNORECASE)
    def _repl_curly(match):
        var = match.group(1).lower()
        if var == 'char':
            return char_name
        elif var == 'user':
            return user_name
        return match.group(0)
    text = pattern_curly.sub(_repl_curly, text)

    # 2. 替换 <char> / <character> / <user>
    pattern_angle = re.compile(r'<\s*(char|character|user)\s*>', re.IGNORECASE)
    def _repl_angle(match):
        var = match.group(1).lower()
        if var in ('char', 'character'):
            return char_name
        elif var == 'user':
            return user_name
        return match.group(0)
    text = pattern_angle.sub(_repl_angle, text)

    # 3. 替换 {$char} / {$character} / {$user}
    pattern_dollar = re.compile(r'\{\s*\$\s*(char|character|user)\s*\}', re.IGNORECASE)
    def _repl_dollar(match):
        var = match.group(1).lower()
        if var in ('char', 'character'):
            return char_name
        elif var == 'user':
            return user_name
        return match.group(0)
    text = pattern_dollar.sub(_repl_dollar, text)

    return text

def compile_prompt_templates(text: str, character, original_prompt: str) -> str:
    """
    编译系统提示词模板中的嵌套宏：
      - {{original}} -> 默认的介绍块 (description + personality)
      - {{personality}} / {{description}} / {{scenario}} / {{mesExamples}} -> 对应角色卡字段
    不区分大小写，且容忍空格。
    """
    if not text:
        return text

    # 1. 替换 {{original}}
    text = re.compile(r'\{\{\s*original\s*\}\}', re.IGNORECASE).sub(lambda m: original_prompt, text)

    # 2. 替换嵌套属性字段
    field_map = {
        "personality": character.personality or "",
        "description": character.description or "",
        "scenario": character.scenario or "",
        "mesexamples": character.mes_example or "",
        "mes_examples": character.mes_example or "",
        "mes_example": character.mes_example or "",
    }

    def _field_repl(match):
        field_name = match.group(1).lower().replace("_", "").replace(" ", "")
        return field_map.get(field_name, match.group(0))

    pattern_fields = re.compile(
        r'\{\{\s*(personality|description|scenario|mesexamples|mes_examples|mes_example)\s*\}\}',
        re.IGNORECASE
    )
    text = pattern_fields.sub(_field_repl, text)

    return text

def compile_system_prompt(character, persona, user_nickname: str = "用户") -> str:
    """
    静态 System Prompt 组装与编译。
    """
    char_name = character.name or "AI"
    user_name = user_nickname or "用户"

    # 1. 构造默认的 original prompt 模块
    default_prompt_parts = []
    if character.description:
        default_prompt_parts.append(f"【角色设定】\n{character.description}")
    if character.personality:
        default_prompt_parts.append(f"【性格特点】\n{character.personality}")
    original_prompt = "\n\n".join(default_prompt_parts)

    sections = []

    # 2. 核心人设编译
    if character.system_prompt_override:
        compiled_override = compile_prompt_templates(
            character.system_prompt_override, character, original_prompt
        )
        sections.append(compiled_override)
    else:
        if original_prompt:
            sections.append(original_prompt)

    # 3. 结构化输出指令 (静态)
    xml_instructions = """【重要：输出格式要求】
你必须且只能按照以下 XML 标签结构进行回复，绝对不要包含任何 markdown 代码块标记（如 ```xml 或 ```html）：
<reply>你的第一人称角色扮演回复文本（支持动作星号包裹与台词双引号包裹）</reply>
<status emotion="当前心情标签（例如：开心、平静、害羞等单个词语）" affection_change="好感度整数变化量（必须是整数，范围在 -5 到 5 之间）"/>"""
    sections.append(xml_instructions)

    # 4. 后置扮演规则编译
    post_instructions = character.post_history_instructions or None
    if post_instructions:
        compiled_post = compile_prompt_templates(
            post_instructions, character, original_prompt
        )
        sections.append(f"【扮演补充规则】\n{compiled_post}")

    # 5. 对话示例编译 (非子会话附加)
    if not (persona and persona.parent_persona_id):
        if character.mes_example and character.mes_example.strip():
            sections.append(f"【对话示例】\n{character.mes_example.strip()}")

    system_prompt = "\n\n".join(sections)

    # 6. 对生成的 System Prompt 整体进行最终的 char/user 占位符替换
    system_prompt = replace_placeholders(system_prompt, char_name, user_name)

    return system_prompt
