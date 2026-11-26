"""模型回复、状态增量和流式正文前缀的容错解析。"""
import json
import re


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
    r"</\s*(?:reply|replay)\s*>|<\s*(?:status|state_update)\b",
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
    # 无论状态 JSON 是否有效，都不能让附属协议进入正文或音频。
    state_match = re.search(r"<\s*state_update\b[^>]*>(.*?)</\s*state_update\s*>", text, re.IGNORECASE | re.DOTALL)
    state_patch = None
    if state_match:
        try:
            from services.conversation.role_state_schema import validate_patch
            state_patch = validate_patch(json.loads(state_match.group(1)))
        except (ValueError, TypeError):
            pass
    state_start = re.search(r"<\s*state_update\b", text, re.IGNORECASE)
    if state_start:
        # 增量只允许位于正文/status 之后。即使模型错误地提前关闭标签，
        # 其后残余 JSON 也不能回流为正文。
        text = text[:state_start.start()]
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

    result = {
        "reply": reply,
        "emotion_tag": emotion_tag,
        "affection_change": affection_change,
    }
    if state_patch is not None:
        result["role_state_patch"] = state_patch
    return result


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
