"""整理建议的保守边界、时间状态收敛与候选相关性预筛。"""

from collections import Counter
from datetime import date
import math
import re


_DATE = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]"
    r"|(?P<iso_year>\d{4})[-/](?P<iso_month>\d{1,2})[-/](?P<iso_day>\d{1,2})(?!\d)"
)
_YEAR = re.compile(r"(?<!\d)(\d{4})\s*年")
# 预约/承诺里的目标日期不是本次经历发生日，不能拿它划开本次经历。
_TARGET_DATE = re.compile(r"预约|约定|约好|约在|答应|计划|打算|准备|预计|定于|安排|复诊|下次|如果|若")
_NEGATION = re.compile(r"不(?:是|喜欢|愿意|能|会|想|要|爱|吃|喝|接受|希望|允许|习惯|支持|需要|可)|没有|没(?:去|见|吃|喝|做|搬|发生)|未(?:曾|能|经|去|做|搬|发生)|并非|从未|拒绝|讨厌|禁止")
_STOP_SPAN_RE = re.compile(r"用户|角色|本人|自己|他们|她们|两人|双方|一起|一次|那次|这次|目前|现在|曾经")


def event_date_anchor(content):
    """取第一个明确日期；未知年份保留 None，不以系统时间补全。

    只用于识别明确冲突，不推断“那次”、相对日期或隐含的事件身份。
    第一处日期若属于计划/预约目标，整张卡不提供发生日锚点。
    """
    match = _DATE.search(content)
    if match:
        if _TARGET_DATE.search(content[:match.start()]):
            return None
        year = match["year"] or match["iso_year"]
        year = int(year) if year else None
        month = int(match["month"] or match["iso_month"])
        day = int(match["day"] or match["iso_day"])
        try:
            date(year or 2000, month, day)
        except ValueError:
            return None
        return year, month, day
    match = _YEAR.search(content)
    if match and not _TARGET_DATE.search(content[:match.start()]):
        return int(match[1]), None, None
    return None


def has_conflicting_event_dates(sources):
    """只比较事件卡；明确跨日期时宁可保留原卡，不拼接两次经历。"""
    anchors = [event_date_anchor(source["content"]) for source in sources if source["memory_type"] == "event"]
    anchors = [anchor for anchor in anchors if anchor is not None]
    return any(
        any(a is not None and b is not None and a != b for a, b in zip(left, right))
        for index, left in enumerate(anchors) for right in anchors[index + 1:]
    )


def has_temporal_conflict(sources):
    """检查同组来源是否存在互斥的故事内时间状态或不同时间附注。

    允许补充细节卡的时间状态为 unknown 或省略 temporal_note，
    但 planned 必须全组一致，且不同明确状态或不同明确附注不可合并。
    """
    statuses = {source.get("temporal_status", "unknown") or "unknown" for source in sources}
    if "planned" in statuses and len(statuses) > 1:
        return True
    known_statuses = statuses - {"unknown"}
    if len(known_statuses) > 1:
        return True
    known_notes = {source.get("temporal_note") for source in sources if source.get("temporal_note")}
    if len(known_notes) > 1:
        return True
    return False


def resolve_group_temporal(sources):
    """从相容的同组来源中提取合并后的时间状态与时间附注。"""
    status = next(
        (
            source.get("temporal_status")
            for source in sources
            if source.get("temporal_status") and source.get("temporal_status") != "unknown"
        ),
        "unknown",
    )
    note = next((source.get("temporal_note") for source in sources if source.get("temporal_note")), None)
    return status, note


def has_source_conflict(kind, sources):
    if len({source["event_id"] for source in sources if source.get("event_id") is not None}) > 1:
        return True
    if has_temporal_conflict(sources):
        return True
    if has_conflicting_event_dates(sources):
        return True
    # 只挡明确否定标记不同的 duplicate，不对事件里不同动作的否定作比较。
    # 这是保守跳过规则，并不把没有匹配到标记等同于语义肯定。
    return kind == "duplicate" and len({bool(_NEGATION.search(source["content"])) for source in sources}) > 1


def filter_safe_groups(groups, sources):
    by_id = {source["id"]: source for source in sources}
    safe = []
    for group in groups:
        if not has_source_conflict(group["kind"], [by_id[source_id] for source_id in group["source_ids"]]):
            safe.append({**group, "id": len(safe)})
    return safe


def _content_terms(text: str) -> Counter:
    cleaned = _STOP_SPAN_RE.sub(" ", text or "")
    tokens = Counter(re.findall(r"[a-z0-9_]+", cleaned.casefold()))
    for span in re.findall(r"[\u3400-\u9fff]+", cleaned):
        tokens.update(span if len(span) == 1 else [span[i:i + 2] for i in range(len(span) - 1)])
    return tokens


def content_similarity(left_text: str, right_text: str) -> float:
    """计算去除通用角色称谓后的双字词项/英文词余弦相似度。"""
    left = _content_terms(left_text)
    right = _content_terms(right_text)
    norm = math.sqrt(sum(v * v for v in left.values()) * sum(v * v for v in right.values()))
    if not norm:
        return 0.0
    return sum(v * right.get(k, 0) for k, v in left.items()) / norm


def build_consolidation_hints(memory_type: str, sources: list[dict], max_groups: int = 12) -> list[list[int]]:
    """在大批卡片输入前生成高相关性候选簇 ID 提示，降低模型跨距漏检率。"""
    if len(sources) < 2 or max_groups <= 0:
        return []
    kind = "event" if memory_type == "event" else "duplicate"
    threshold = 0.30 if kind == "event" else 0.38
    scored_pairs = []
    for idx, left in enumerate(sources):
        for right in sources[idx + 1:]:
            if has_source_conflict(kind, [left, right]):
                continue
            sim = content_similarity(left["content"], right["content"])
            if kind == "event":
                l_end = left.get("source_message_id")
                r_start = right.get("source_start_message_id") or right.get("source_message_id")
                if type(l_end) is int and type(r_start) is int and abs(r_start - l_end) <= 6 and sim >= 0.20:
                    sim += 0.12
            if sim >= threshold:
                scored_pairs.append((sim, left["id"], right["id"]))
    if not scored_pairs:
        return []
    scored_pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    clusters: list[list[int]] = []
    card_to_cluster: dict[int, list[int]] = {}
    by_id = {source["id"]: source for source in sources}
    for _, left_id, right_id in scored_pairs:
        c_left = card_to_cluster.get(left_id)
        c_right = card_to_cluster.get(right_id)
        if c_left is None and c_right is None:
            if len(clusters) >= max_groups:
                continue
            cluster = [left_id, right_id]
            clusters.append(cluster)
            card_to_cluster[left_id] = cluster
            card_to_cluster[right_id] = cluster
        elif c_left is not None and c_right is None and len(c_left) < 6:
            candidate_ids = c_left + [right_id]
            if not has_source_conflict(kind, [by_id[cid] for cid in candidate_ids]):
                c_left.append(right_id)
                card_to_cluster[right_id] = c_left
        elif c_right is not None and c_left is None and len(c_right) < 6:
            candidate_ids = c_right + [left_id]
            if not has_source_conflict(kind, [by_id[cid] for cid in candidate_ids]):
                c_right.append(left_id)
                card_to_cluster[left_id] = c_right
    return [sorted(cluster) for cluster in clusters]
