import json
from core.config import settings

def process_lorebook(
    character,
    recent_history: list[dict] | None,
    user_message: str | None
) -> dict:
    """
    处理角色专属的世界书（Lorebook/CharacterBook）匹配与筛选。
    """
    if not recent_history and not user_message:
        return {"before_char": [], "after_char": []}

    # 1. 安全解析 extensions
    extensions_dict = {}
    if character.extensions:
        if isinstance(character.extensions, str):
            try:
                extensions_dict = json.loads(character.extensions)
            except Exception:
                pass
        elif isinstance(character.extensions, dict):
            extensions_dict = character.extensions
            
    character_book = extensions_dict.get("character_book", {}) if isinstance(extensions_dict, dict) else {}
    if not isinstance(character_book, dict):
        character_book = {}
        
    entries = character_book.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return {"before_char": [], "after_char": []}
        
    # 2. 提取配置（支持 YAML 可配置回退）
    scan_depth = character_book.get("scan_depth")
    if scan_depth is None or not isinstance(scan_depth, int) or scan_depth < 0:
        scan_depth = settings.APP_LOREBOOK_SCAN_DEPTH
        
    token_budget = character_book.get("token_budget")
    if token_budget is None or not isinstance(token_budget, int) or token_budget <= 0:
        token_budget = settings.APP_LOREBOOK_TOKEN_BUDGET
        
    recursive_scanning = bool(character_book.get("recursive_scanning", False))
    
    # 3. 构造基础扫描文本
    history_to_scan = recent_history[-scan_depth:] if scan_depth > 0 and recent_history else []
    scan_parts = []
    for msg in history_to_scan:
        scan_parts.append(msg.get("content", ""))
    if user_message:
        scan_parts.append(user_message)
    scan_text = "\n".join(scan_parts)
    
    # 4. 条目触发匹配 (支持递归扫描)
    max_passes = settings.APP_LOREBOOK_MAX_RECURSIVE_PASSES if recursive_scanning else 1
    triggered_indexes = set()
    triggered_entries = []
    
    current_scan_text = scan_text
    
    for _ in range(max_passes):
        new_trigger_added = False
        for idx, entry in enumerate(entries):
            if idx in triggered_indexes:
                continue
                
            if not isinstance(entry, dict):
                continue
                
            if not entry.get("enabled", True):
                continue
                
            constant = bool(entry.get("constant", False))
            if constant:
                triggered_indexes.add(idx)
                triggered_entries.append(entry)
                new_trigger_added = True
                content = entry.get("content", "")
                if content:
                    current_scan_text += "\n" + content
                continue
                
            keys = entry.get("keys", [])
            secondary_keys = entry.get("secondary_keys", [])
            selective = bool(entry.get("selective", False))
            case_sensitive = bool(entry.get("case_sensitive", False))
            
            if not isinstance(keys, list):
                keys = [keys] if keys else []
            if not isinstance(secondary_keys, list):
                secondary_keys = [secondary_keys] if secondary_keys else []
                
            if not case_sensitive:
                text_to_search = current_scan_text.lower()
                keys_to_search = [str(k).lower() for k in keys if k]
                secondary_keys_to_search = [str(k).lower() for k in secondary_keys if k]
            else:
                text_to_search = current_scan_text
                keys_to_search = [str(k) for k in keys if k]
                secondary_keys_to_search = [str(k) for k in secondary_keys if k]
                
            primary_matched = any(k in text_to_search for k in keys_to_search) if keys_to_search else False
            if selective:
                secondary_matched = any(k in text_to_search for k in secondary_keys_to_search) if secondary_keys_to_search else False
                matched = primary_matched and secondary_matched
            else:
                matched = primary_matched
                
            if matched:
                triggered_indexes.add(idx)
                triggered_entries.append(entry)
                new_trigger_added = True
                content = entry.get("content", "")
                if content:
                    current_scan_text += "\n" + content
                    
        if not new_trigger_added:
            break
            
    # 5. 预算控制与排序
    triggered_entries.sort(key=lambda e: (
        int(e.get("insertion_order", 100)),
        int(e.get("priority", 100))
    ))
    
    budget_used = 0
    selected_entries = []
    for entry in triggered_entries:
        content = entry.get("content", "").strip()
        if not content:
            continue
        content_len = len(content)
        if budget_used + content_len <= token_budget:
            selected_entries.append(entry)
            budget_used += content_len
            
    # 6. 分类位置归宿
    before_char = []
    after_char = []
    for entry in selected_entries:
        pos = entry.get("position", "after_char")
        if pos == "before_char":
            before_char.append(entry)
        else:
            after_char.append(entry)
            
    return {
        "before_char": before_char,
        "after_char": after_char
    }
