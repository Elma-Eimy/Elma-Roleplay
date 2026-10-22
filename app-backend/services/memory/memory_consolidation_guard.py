"""整理建议的保守边界：明确发生日期与重复事实的否定差异。"""

from datetime import date
import re


_DATE = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]"
    r"|(?P<iso_year>\d{4})[-/](?P<iso_month>\d{1,2})[-/](?P<iso_day>\d{1,2})(?!\d)"
)
_YEAR = re.compile(r"(?<!\d)(\d{4})\s*年")
# 预约/承诺里的目标日期不是本次经历发生日，不能拿它划开本次经历。
_TARGET_DATE = re.compile(r"预约|约定|约好|约在|答应|计划|打算|准备|预计|定于|安排|复诊|下次|如果|若")
_NEGATION = re.compile(r"不(?:是|喜欢|愿意|能|会|想|要|爱|吃|喝|接受|希望|允许|习惯|支持|需要|可)|没有|没(?:去|见|吃|喝|做|搬|发生)|未(?:曾|能|经|去|做|搬|发生)|并非|从未|拒绝|讨厌|禁止")


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


def has_source_conflict(kind, sources):
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
