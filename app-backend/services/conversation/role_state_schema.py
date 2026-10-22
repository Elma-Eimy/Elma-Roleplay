"""角色状态增量的纯校验；不接受模型自由扩展字段或猜测空值。"""

import copy
import json

ACTOR_FIELDS = {"posture", "clothing", "location"}
MAX_ACTORS = 8


def validate_patch(value, manual=False):
    if not isinstance(value, dict) or set(value) - {"scene", "characters"}:
        raise ValueError("状态只支持 scene 和 characters 字段")
    if len(json.dumps(value, ensure_ascii=False)) > 12000:
        raise ValueError("状态更新过长")

    def text(raw, limit):
        if manual and (raw is None or raw == ""):
            return None
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > limit:
            raise ValueError(f"状态字段必须是 1–{limit} 字的文本")
        if any(ord(char) < 32 and char not in "\n\t" for char in raw):
            raise ValueError("状态字段不能包含控制字符")
        return raw.strip()

    result = {}
    if "scene" in value:
        result["scene"] = text(value["scene"], 300)
    if "characters" in value:
        actors = value["characters"]
        if not isinstance(actors, dict) or len(actors) > (MAX_ACTORS * 2 if manual else MAX_ACTORS):
            raise ValueError("状态最多包含 8 名受控角色")
        result["characters"] = {}
        for name, fields in actors.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 50 or name != name.strip() or any(ord(char) < 32 for char in name):
                raise ValueError("角色名称必须是 1–50 字且不能有首尾空白")
            if not isinstance(fields, dict) or set(fields) - ACTOR_FIELDS:
                raise ValueError("角色状态只支持 posture、clothing、location")
            result["characters"][name] = {key: text(raw, 200) for key, raw in fields.items()}
    return result


def merge_state(state, patch, check_limit=True):
    result = copy.deepcopy(state)
    if "scene" in patch:
        # 手动清空后保持明确的未知，不能退回角色卡里的初始地点。
        result["scene"] = patch["scene"]
    actors = result.setdefault("characters", {})
    for name, fields in patch.get("characters", {}).items():
        actor = actors.setdefault(name, {})
        for key, value in fields.items():
            if value is None:
                actor.pop(key, None)
            else:
                actor[key] = value
        if not actor:
            actors.pop(name, None)
    if not actors:
        result.pop("characters", None)
    if check_limit and len(actors) > MAX_ACTORS:
        raise ValueError("当前状态最多保留 8 名受控角色，请先清除不再需要的人物状态")
    return result


def decode_state(value):
    return json.loads(value) if value else {}


def encode_state(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
