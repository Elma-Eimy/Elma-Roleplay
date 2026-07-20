import json
from typing import Dict, List, Any

def parse_sillytavern_lorebook(raw_data: dict) -> dict:
    """
    解析 SillyTavern 格式的世界书 JSON 字典，将其清洗并归一化为本系统的标准格式。
    """
    # 提取顶级字段
    name = raw_data.get("name", "未命名世界书")
    description = raw_data.get("description", "")
    
    # 获取检索配置参数
    scan_depth = raw_data.get("scan_depth")
    if scan_depth is not None:
        try:
            scan_depth = int(scan_depth)
        except (ValueError, TypeError):
            scan_depth = None
            
    token_budget = raw_data.get("token_budget")
    if token_budget is not None:
        try:
            token_budget = int(token_budget)
        except (ValueError, TypeError):
            token_budget = None
            
    recursive_scanning = raw_data.get("recursive_scanning")
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
        if isinstance(keys, str):
            # 如果是逗号分隔的字符串，拆分为列表
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        elif isinstance(keys, list):
            keys = [str(k).strip() for k in keys if k]
        else:
            keys = []
            
        # 2. 提取联合过滤关键字 secondary_keys
        sec_keys = item.get("secondary_keys", [])
        if isinstance(sec_keys, str):
            sec_keys = [k.strip() for k in sec_keys.split(",") if k.strip()]
        elif isinstance(sec_keys, list):
            sec_keys = [str(k).strip() for k in sec_keys if k]
        else:
            sec_keys = []
            
        # 3. 提取内容 content / entry / value
        content = item.get("content", item.get("entry", item.get("value", "")))
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        
        # 如果条目内容为空，跳过
        if not content:
            continue
            
        # 4. 其它开关参数
        enabled = bool(item.get("enabled", True))
        constant = bool(item.get("constant", item.get("constant_activation", False)))
        case_sensitive = bool(item.get("case_sensitive", False))
        selective = bool(item.get("selective", False))
        
        # 5. 优先级/插入顺序
        priority = item.get("priority", item.get("insertion_order", item.get("order")))
        if priority is not None:
            try:
                priority = int(priority)
            except (ValueError, TypeError):
                priority = 100
        else:
            priority = 100
            
        # 6. 插入位置映射
        # SillyTavern extensions.position 常用映射: 0=before_char, 1=after_char, 2=before_story, 3=after_story
        # 默认位置设为 "after_char"
        pos = "after_char"
        raw_pos = item.get("position")
        if raw_pos is None and "extensions" in item and isinstance(item["extensions"], dict):
            raw_pos = item["extensions"].get("position")
            
        if isinstance(raw_pos, int):
            if raw_pos == 0:
                pos = "before_char"
            elif raw_pos == 1:
                pos = "after_char"
            else:
                pos = "after_char"
        elif isinstance(raw_pos, str):
            raw_pos_lower = raw_pos.lower()
            if "before_char" in raw_pos_lower or "beforechar" in raw_pos_lower:
                pos = "before_char"
            elif "after_char" in raw_pos_lower or "afterchar" in raw_pos_lower:
                pos = "after_char"
                
        parsed_entries.append({
            "keys": keys,
            "content": content,
            "enabled": enabled,
            "constant": constant,
            "case_sensitive": case_sensitive,
            "selective": selective,
            "secondary_keys": sec_keys,
            "position": pos,
            "insertion_order": priority
        })
        
    return {
        "name": name,
        "description": description,
        "scan_depth": scan_depth,
        "token_budget": token_budget,
        "recursive_scanning": recursive_scanning,
        "entries": parsed_entries
    }
