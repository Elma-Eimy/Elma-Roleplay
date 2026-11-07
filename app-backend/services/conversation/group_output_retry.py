"""只重试尚未提交的格式无效响应，调用与期限仍由整轮执行器计费。"""
import inspect


async def validated_output(invoke, parameters, validate, attempts, *, retry_experience=False):
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError("输出尝试次数需要在 1–3 之间")
    original_messages = parameters["messages"]
    for attempt in range(attempts):
        response = await invoke(parameters)
        try:
            value = validate(response.choices[0])
            if inspect.isawaitable(value):
                value = await value
            return response, value
        except (ValueError, RuntimeError) as exc:
            retry_codes = ('invalid_output', 'unsupported_experience') if retry_experience else ('invalid_output',)
            if getattr(exc, "code", None) not in retry_codes or attempt + 1 == attempts:
                raise
            # 不把非法正文当作历史，也不允许它扩散到导演或其他成员输入。
            feedback = ('上次发言含缺乏本人可见依据的亲历表述，尚未提交。按原始来源重新生成；'
                        '听说改为明确转述，不确定就说明不确定，不补造本人见过或做过，也不要重演旧动作。'
                        if getattr(exc, 'code', None) == 'unsupported_experience' else '')
            parameters = {**parameters, "messages": [*original_messages, {
                "role": "system",
                "content": (feedback + "上次响应未通过输出协议校验，尚未提交。请根据原始资料重新生成完整 JSON 对象；"
                            "逐项检查本阶段要求的必填字段、字段类型、取值和括号。"
                            "不得省略本阶段要求的字段，不混用其他阶段的字段。"
                            "不输出 Markdown、解释或额外字段。只完成当前步骤。")}]}
