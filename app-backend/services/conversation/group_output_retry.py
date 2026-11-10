"""有界校正尚未提交的输出和首条回应调度，调用与期限沿用整轮预算。"""
import inspect


async def validated_output(invoke, parameters, validate, attempts, *, retry_experience=False, repair_parameters=None):
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
            retry_codes = ('invalid_output', 'pending_response', 'unsupported_experience') if retry_experience else ('invalid_output', 'pending_response')
            if getattr(exc, "code", None) not in retry_codes or attempt + 1 == attempts:
                raise
            if repair_parameters is not None:
                repaired = repair_parameters(response, exc)
                if repaired is not None:
                    parameters = repaired
                    continue
            # 不把非法正文当作历史，也不允许它扩散到导演或其他成员输入。
            feedback = ('上次发言含缺乏本人可见依据的亲历表述，尚未提交。按原始来源重新生成；'
                        '听说改为明确转述，不确定就说明不确定，不补造本人见过或做过，也不要重演旧动作。'
                        '本次重写只写自己对本轮用户原话或动作的直接回应；'
                        '不要补写其他成员新的动作、表情、声音或心理，不声称他们刚才发生了什么。'
                        '不要新增回忆、既往对白或亲历断言。'
                        if getattr(exc, 'code', None) == 'unsupported_experience' else '')
            if getattr(exc, 'code', None) == 'pending_response':
                feedback = ('本轮尚无角色发言，仍有明确要求口头回答的用户请求。上次结束决定未提交。'
                            '请从 response_sources 的 user_request、reply_mode=speech 中选择对应成员及有效 basis，'
                            '返回 speak 决定；不要让其他成员代答，不要生成台词。')
            parameters = {**parameters, "messages": [*original_messages, {
                "role": "system",
                "content": (feedback + "上次响应未通过输出协议校验，尚未提交。请根据原始资料重新生成完整 JSON 对象；"
                            "逐项检查本阶段要求的必填字段、字段类型、取值和括号。"
                            "不得省略本阶段要求的字段，不混用其他阶段的字段。"
                            "不输出 Markdown、解释或额外字段。只完成当前步骤。")}]}
