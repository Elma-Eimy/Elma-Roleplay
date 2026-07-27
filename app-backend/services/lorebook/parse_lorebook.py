import re
from typing import Any


LOREBOOK_POSITION_BY_ID = {
    0: "before_char",
    1: "after_char",
    2: "top_an",
    3: "bottom_an",
    4: "at_depth",
    5: "before_examples",
    6: "after_examples",
    7: "outlet",
}
LOREBOOK_ROLE_BY_ID = {
    0: "system",
    1: "user",
    2: "assistant",
}
SELECTIVE_LOGIC_BY_ID = {
    0: "and_any",
    1: "not_all",
    2: "not_any",
    3: "and_all",
}


def normalize_lorebook_position(raw_position: Any) -> str:
    """归一化 SillyTavern 世界书条目的插入位置。"""
    if isinstance(raw_position, bool):
        return "after_char"
    if isinstance(raw_position, int):
        return LOREBOOK_POSITION_BY_ID.get(raw_position, "after_char")
    if isinstance(raw_position, str):
        value = re.sub(r"[\s_-]+", "", raw_position.strip().lower())
        aliases = {
            "beforechar": "before_char",
            "beforechardefs": "before_char",
            "beforecharacter": "before_char",
            "afterchar": "after_char",
            "afterchardefs": "after_char",
            "aftercharacter": "after_char",
            "topan": "top_an",
            "topauthorsnote": "top_an",
            "bottoman": "bottom_an",
            "bottomauthorsnote": "bottom_an",
            "atdepth": "at_depth",
            "inchat": "at_depth",
            "inchatatdepth": "at_depth",
            "beforeexamples": "before_examples",
            "beforeexamplemessages": "before_examples",
            "topexamples": "before_examples",
            "afterexamples": "after_examples",
            "afterexamplemessages": "after_examples",
            "bottomexamples": "after_examples",
            "outlet": "outlet",
        }
        if value.isdigit():
            return LOREBOOK_POSITION_BY_ID.get(int(value), "after_char")
        return aliases.get(value, "after_char")
    return "after_char"


def normalize_lorebook_role(raw_role: Any) -> str:
    """归一化 @ Depth 条目的 Chat Completion 消息角色。"""
    if isinstance(raw_role, bool):
        return "system"
    if isinstance(raw_role, int):
        return LOREBOOK_ROLE_BY_ID.get(raw_role, "system")
    if isinstance(raw_role, str):
        value = raw_role.strip().lower()
        if value.isdigit():
            return LOREBOOK_ROLE_BY_ID.get(int(value), "system")
        aliases = {
            "system": "system",
            "sys": "system",
            "user": "user",
            "human": "user",
            "assistant": "assistant",
            "ai": "assistant",
            "char": "assistant",
            "character": "assistant",
        }
        return aliases.get(value, "system")
    return "system"


def normalize_lorebook_depth(raw_depth: Any) -> int:
    """将 @ Depth 深度限制为 SillyTavern 支持的非负整数范围。"""
    try:
        depth = int(raw_depth)
    except (ValueError, TypeError):
        depth = 4
    return max(0, min(depth, 999))


def normalize_selective_logic(raw_logic: Any) -> str:
    """归一化 SillyTavern Optional Filter 的四种组合逻辑。"""
    if isinstance(raw_logic, bool):
        return "and_any"
    if isinstance(raw_logic, int):
        return SELECTIVE_LOGIC_BY_ID.get(raw_logic, "and_any")
    if isinstance(raw_logic, str):
        value = re.sub(r"[\s_-]+", "", raw_logic.strip().lower())
        if value.isdigit():
            return SELECTIVE_LOGIC_BY_ID.get(int(value), "and_any")
        aliases = {
            "andany": "and_any",
            "any": "and_any",
            "notall": "not_all",
            "notany": "not_any",
            "andall": "and_all",
            "all": "and_all",
        }
        return aliases.get(value, "and_any")
    return "and_any"


def normalize_probability(raw_probability: Any) -> int:
    """把触发概率约束为 0–100 的整数百分比。"""
    try:
        probability = int(float(raw_probability))
    except (ValueError, TypeError):
        probability = 100
    return max(0, min(probability, 100))


def normalize_lorebook_keys(raw_keys: Any) -> list[str]:
    """兼容列表、逗号文本和内部含逗号的 `/pattern/flags`。"""
    if isinstance(raw_keys, str):
        value = raw_keys.strip()
        if not value:
            return []
        if value.startswith("/") and value.rfind("/") > 0:
            return [value]
        return [key.strip() for key in value.split(",") if key.strip()]
    if isinstance(raw_keys, list):
        return [
            str(key).strip()
            for key in raw_keys
            if key is not None and str(key).strip()
        ]
    return [str(raw_keys).strip()] if raw_keys else []


def parse_sillytavern_lorebook(raw_data: dict) -> dict:
    """
    解析 SillyTavern 格式的世界书 JSON 字典，将其清洗并归一化为本系统的标准格式。
    """
    # 提取顶级字段
    name = raw_data.get("name", "未命名世界书")
    description = raw_data.get("description", "")
    
    # 获取检索配置参数
    scan_depth = raw_data.get("scan_depth", raw_data.get("scanDepth"))
    if scan_depth is not None:
        try:
            scan_depth = int(scan_depth)
        except (ValueError, TypeError):
            scan_depth = None
            
    token_budget = raw_data.get("token_budget", raw_data.get("tokenBudget"))
    if token_budget is not None:
        try:
            token_budget = int(token_budget)
        except (ValueError, TypeError):
            token_budget = None
            
    recursive_scanning = raw_data.get(
        "recursive_scanning",
        raw_data.get("recursiveScanning"),
    )
    if recursive_scanning is not None:
        recursive_scanning = bool(recursive_scanning)

    # 解析 entries
    raw_entries = raw_data.get("entries", [])
    parsed_entries = []
    
    # 兼容 entries 是字典（{"0": {...}, "1": {...}}）和列表（[...]）两种格式
    entries_list = []
    if isinstance(raw_entries, dict):
        # 按键（通常是数字字符串）排序后遍历，以保持原始顺序
        try:
            sorted_keys = sorted(raw_entries.keys(), key=lambda x: int(x) if x.isdigit() else x)
        except Exception:
            sorted_keys = raw_entries.keys()
        for k in sorted_keys:
            entries_list.append(raw_entries[k])
    elif isinstance(raw_entries, list):
        entries_list = raw_entries
        
    for item in entries_list:
        if not isinstance(item, dict):
            continue
            
        # 1. 提取匹配关键字 keys / key
        keys = item.get("keys", item.get("key", []))
        keys = normalize_lorebook_keys(keys)
            
        # 2. 提取联合过滤关键字 secondary_keys
        sec_keys = item.get(
            "secondary_keys",
            item.get("keysecondary", item.get("secondaryKeys", [])),
        )
        sec_keys = normalize_lorebook_keys(sec_keys)
            
        # 3. 提取内容 content / entry / value
        content = item.get("content", item.get("entry", item.get("value", "")))
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        
        # 如果条目内容为空，跳过
        if not content:
            continue
            
        # 4. 其它开关参数
        enabled = bool(item.get("enabled", not bool(item.get("disable", False))))
        constant = bool(item.get("constant", item.get("constant_activation", False)))
        case_sensitive = bool(item.get("case_sensitive", item.get("caseSensitive", False)))
        selective = bool(item.get("selective", False))

        item_extensions = item.get("extensions")
        if not isinstance(item_extensions, dict):
            item_extensions = {}

        raw_selective_logic = item.get(
            "selective_logic",
            item.get(
                "selectiveLogic",
                item_extensions.get("selectiveLogic"),
            ),
        )
        selective_logic = normalize_selective_logic(raw_selective_logic)
        use_regex = bool(
            item.get(
                "use_regex",
                item.get(
                    "useRegex",
                    item_extensions.get(
                        "use_regex",
                        item_extensions.get("useRegex", False),
                    ),
                ),
            )
        )
        raw_probability = item.get(
            "probability",
            item_extensions.get("probability", 100),
        )
        probability = normalize_probability(raw_probability)
        use_probability = bool(
            item.get(
                "use_probability",
                item.get(
                    "useProbability",
                    item_extensions.get("useProbability", True),
                ),
            )
        )
        
        # 5. 优先级/插入顺序
        priority = item.get("priority", item.get("insertion_order", item.get("order")))
        if priority is not None:
            try:
                priority = int(priority)
            except (ValueError, TypeError):
                priority = 100
        else:
            priority = 100
            
        # 6. 插入位置、@ Depth 深度和消息角色。
        # SillyTavern 数字位置：0/1=角色定义前后，2/3=作者注释顶部/底部，
        # 4=聊天深度，5/6=示例消息前后，7=Outlet。
        raw_pos = item.get("position")
        if raw_pos is None:
            raw_pos = item_extensions.get("position")
        pos = normalize_lorebook_position(raw_pos)

        raw_depth = item.get("depth")
        if raw_depth is None:
            raw_depth = item_extensions.get("depth")
        depth = normalize_lorebook_depth(raw_depth)

        raw_role = item.get("role")
        if raw_role is None:
            raw_role = item_extensions.get("role")
        role = normalize_lorebook_role(raw_role)

        outlet = item.get(
            "outlet",
            item.get(
                "outlet_name",
                item_extensions.get("outlet", item_extensions.get("outlet_name", "")),
            ),
        )
        outlet = str(outlet).strip() if outlet is not None else ""
                
        parsed_entries.append({
            "keys": keys,
            "content": content,
            "enabled": enabled,
            "constant": constant,
            "case_sensitive": case_sensitive,
            "selective": selective,
            "selective_logic": selective_logic,
            "secondary_keys": sec_keys,
            "use_regex": use_regex,
            "probability": probability,
            "use_probability": use_probability,
            "position": pos,
            "insertion_order": priority,
            "depth": depth,
            "role": role,
            "outlet": outlet,
        })
        
    return {
        "name": name,
        "description": description,
        "scan_depth": scan_depth,
        "token_budget": token_budget,
        "recursive_scanning": recursive_scanning,
        "entries": parsed_entries
    }
