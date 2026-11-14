"""v2 可见单元协议的纯校验；原文范围采用 Python Unicode 码点。"""
import json
from dataclasses import dataclass


class GroupUnitError(ValueError):
    def __init__(self, code="invalid_output"):
        self.code = code
        super().__init__("群聊单元未完成：" + code)


def load_object(raw, finish_reason="stop"):
    if finish_reason not in (None, "stop"):
        raise GroupUnitError("incomplete_output")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("invalid constant")
    try:
        if not isinstance(raw, str) or len(raw) > 16000:
            raise ValueError("invalid size")
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
        if not isinstance(value, dict):
            raise ValueError("invalid object")
        return value
    except (ValueError, TypeError, RecursionError):
        raise GroupUnitError() from None


@dataclass(frozen=True)
class ContentUnit:
    kind: str
    text: str | None = None
    start: int | None = None
    end: int | None = None
    meaning: str | None = None
    reply_mode: str | None = None


@dataclass(frozen=True)
class UnitPlan:
    units: tuple[ContentUnit, ...]
    audiences: tuple[tuple[int, ...], ...]
    request_targets: tuple[tuple[int, ...], ...] = ()
    review: str | None = None
    request_result: str | None = None

    def decision(self, members):
        rows = []
        for index, (unit, visible) in enumerate(zip(self.units, self.audiences)):
            row = {"unit_index": index, "recipients": [
                {"persona_id": pid, "decision": "visible" if pid in visible else "hidden"} for pid in sorted(members)]}
            if unit.kind == "user":
                row.update(start=unit.start, end=unit.end)
                if unit.meaning is not None:
                    row.update(meaning=unit.meaning, request_to=list(self.request_targets[index]))
            if unit.reply_mode:
                row["reply_mode"] = unit.reply_mode
            rows.append(row)
        return {"units": rows, **({"review": self.review} if self.review else {}),
                **({"request_result": self.request_result} if self.request_result else {})}


def recipients(rows, members, author=None):
    if (not isinstance(members, tuple) or not 2 <= len(members) <= 3
            or any(type(pid) is not int or pid < 1 for pid in members) or len(set(members)) != len(members)
            or not isinstance(rows, list)):
        raise GroupUnitError()
    result = {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"persona_id", "decision"}
                or type(row["persona_id"]) is not int or row["persona_id"] not in members
                or row["persona_id"] in result or row["decision"] not in ("visible", "hidden")):
            raise GroupUnitError()
        result[row["persona_id"]] = row["decision"]
    if set(result) != set(members) or (author is not None and result.get(author) != "visible"):
        raise GroupUnitError()
    return tuple(pid for pid in members if result[pid] == "visible")


def parse_user_units(raw, content, members, *, finish_reason="stop", require_meaning=False, require_reply_mode=None):
    value = load_object(raw, finish_reason)
    if set(value) != {"units"} or not isinstance(value["units"], list) or not 1 <= len(value["units"]) <= 8:
        raise GroupUnitError()
    units, audiences, requests, cursor = [], [], [], 0
    for row in value["units"]:
        if (not isinstance(row, dict) or set(row) not in ({"start", "end", "recipients"},
                {"start", "end", "recipients", "meaning", "request_to"},
                {"start", "end", "recipients", "meaning", "request_to", "reply_mode"})
                or type(row["start"]) is not int or type(row["end"]) is not int
                or row["start"] != cursor or not cursor < row["end"] <= len(content)):
            raise GroupUnitError()
        meaning = row.get("meaning")
        visible = recipients(row["recipients"], members)
        targets = row.get("request_to", [])
        if ((require_meaning or "meaning" in row) and meaning not in ("fact", "speech", "request", "private", "uncertain")
                or not isinstance(targets, list) or any(type(pid) is not int or pid not in members for pid in targets)
                or len(set(targets)) != len(targets) or (meaning != "request" and targets)
                or (meaning == "private" and visible)):
            raise GroupUnitError()
        mode = row.get("reply_mode")
        if "reply_mode" in row:
            if meaning != "request" or mode not in ("speech", "action", "either") or require_reply_mode is False:
                raise GroupUnitError()
        elif require_reply_mode and meaning == "request":
            raise GroupUnitError()
        units.append(ContentUnit("user", start=cursor, end=row["end"], meaning=meaning, reply_mode=mode))
        audiences.append(visible)
        requests.append(tuple(targets))
        cursor = row["end"]
    if cursor != len(content):
        raise GroupUnitError()
    return UnitPlan(tuple(units), tuple(audiences), tuple(requests) if any(unit.meaning for unit in units) else ())


def parse_role_units(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise GroupUnitError()
    units = []
    for row in value:
        if (not isinstance(row, dict) or set(row) != {"kind", "text"}
                or row["kind"] not in ("speech", "action", "thought")
                or not isinstance(row["text"], str) or not row["text"].strip()):
            raise GroupUnitError()
        units.append(ContentUnit(row["kind"], row["text"]))
    return tuple(units)


def parse_unit_visibility(raw, units, members, author, *, finish_reason="stop", require_review=False, reply_mode=None):
    value = load_object(raw, finish_reason)
    fields = set(value)
    if reply_mode is not None:
        fields.discard("request_result")
    if (fields not in ({"units"}, {"units", "review"}) or not isinstance(value["units"], list)
            or len(value["units"]) != len(units)):
        raise GroupUnitError()
    review = value.get("review")
    if require_review or "review" in value:
        if review not in ("ok", "agency_conflict", "unsupported_history"):
            raise GroupUnitError()
        if review != "ok":
            raise GroupUnitError(review)
    audiences = []
    for index, row in enumerate(value["units"]):
        if (not isinstance(row, dict) or set(row) != {"unit_index", "recipients"}
                or type(row["unit_index"]) is not int or row["unit_index"] != index):
            raise GroupUnitError()
        visible = recipients(row["recipients"], members, author)
        if units[index].kind == "thought" and set(visible) != {author}:
            raise GroupUnitError()
        audiences.append(visible)
    outcome = value.get("request_result")
    if reply_mode is not None:
        if outcome not in ("fulfilled", "declined", "pending"):
            raise GroupUnitError()
        kinds = {unit.kind for unit in units}
        observable = kinds & {"action", "speech"}
        if not observable or (outcome == "fulfilled" and reply_mode != "either" and reply_mode not in kinds):
            outcome = "pending"
    return UnitPlan(units, tuple(audiences), review=review, request_result=outcome)
