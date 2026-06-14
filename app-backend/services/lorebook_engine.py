import json
from typing import Optional
from core.config import settings

def process_lorebook(
    character,
    recent_history: Optional[list],
    user_message: Optional[str]
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
        
    embedded_entries = character_book.get("entries", [])
    if not isinstance(embedded_entries, list):
        embedded_entries = []
        
    # 2. 提取并合并绑定的独立世界书 entries
    independent_entries = []
    scan_depth = character_book.get("scan_depth")
    token_budget = character_book.get("token_budget")
    recursive_scanning = bool(character_book.get("recursive_scanning", False))
    
    if hasattr(character, "lorebooks") and character.lorebooks:
        for lb in character.lorebooks:
            # 合并 entries 条目
            if lb.entries:
                try:
                    lb_entries = json.loads(lb.entries)
                    if isinstance(lb_entries, list):
                        independent_entries.extend(lb_entries)
                except Exception as e:
                    print(f"[ERROR] Failed to load entries from independent lorebook '{lb.name}': {e}")
            
            # 合并检索深度配置（取最大值）
            if lb.scan_depth is not None and isinstance(lb.scan_depth, int):
                if scan_depth is None or lb.scan_depth > scan_depth:
                    scan_depth = lb.scan_depth
            # 合并 Token 预算配置（取最大值）
            if lb.token_budget is not None and isinstance(lb.token_budget, int):
                if token_budget is None or lb.token_budget > token_budget:
                    token_budget = lb.token_budget
            # 合并递归扫描开关
            if lb.recursive_scanning is not None:
                recursive_scanning = recursive_scanning or bool(lb.recursive_scanning)
                
    if scan_depth is None or not isinstance(scan_depth, int) or scan_depth < 0:
        scan_depth = settings.APP_LOREBOOK_SCAN_DEPTH
        
    if token_budget is None or not isinstance(token_budget, int) or token_budget <= 0:
        token_budget = settings.APP_LOREBOOK_TOKEN_BUDGET

    # 3. 合并所有 entries
    entries = []
    entries.extend(embedded_entries)
    entries.extend(independent_entries)
    
    if not entries:
        return {"before_char": [], "after_char": []}
    
    # 3. 构造基础扫描文本
    history_to_scan = recent_history[-scan_depth:] if scan_depth > 0 and recent_history else []
    scan_parts = []
    for msg in history_to_scan:
        scan_parts.append(msg.get("content", ""))
    if user_message:
        scan_parts.append(user_message)
    scan_text = "\n".join(scan_parts)
    
    # 4. 条目触发匹配 (支持递归扫描)
    # 4. 构建 Aho-Corasick 自动机 (仅构建一次以取得最优匹配性能)
    from services.ahocorasick import AhoCorasick
    
    ac_insensitive = AhoCorasick()
    ac_sensitive = AhoCorasick()
    
    has_insensitive = False
    has_sensitive = False
    
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue
        # 常驻条目不需要加入自动机，会在扫描时直接触发
        if bool(entry.get("constant", False)):
            continue
            
        case_sensitive = bool(entry.get("case_sensitive", False))
        
        # 提取 Keys 与 Secondary Keys
        keys = entry.get("keys", [])
        if not isinstance(keys, list):
            keys = [keys] if keys else []
        secondary_keys = entry.get("secondary_keys", [])
        if not isinstance(secondary_keys, list):
            secondary_keys = [secondary_keys] if secondary_keys else []
            
        if case_sensitive:
            for k in keys:
                if k:
                    ac_sensitive.add_keyword(str(k), (idx, "primary"))
                    has_sensitive = True
            for sk in secondary_keys:
                if sk:
                    ac_sensitive.add_keyword(str(sk), (idx, "secondary"))
                    has_sensitive = True
        else:
            for k in keys:
                if k:
                    ac_insensitive.add_keyword(str(k).lower(), (idx, "primary"))
                    has_insensitive = True
            for sk in secondary_keys:
                if sk:
                    ac_insensitive.add_keyword(str(sk).lower(), (idx, "secondary"))
                    has_insensitive = True
                    
    if has_insensitive:
        ac_insensitive.make_automaton()
    if has_sensitive:
        ac_sensitive.make_automaton()
        
    # 5. 条目触发匹配 (支持递归扫描)
    max_passes = settings.APP_LOREBOOK_MAX_RECURSIVE_PASSES if recursive_scanning else 1
    triggered_indexes = set()
    triggered_entries = []
    
    current_scan_text = scan_text
    
    for _ in range(max_passes):
        # Bug5修复：将 constant 条目的触发和关键词匹配的触发分离记录。
        # new_trigger_added 仅跟踪"是否有新关键词命中"，不受 constant 常驻触发影响，
        # 从而当只有常驻条目被识别时能尽早退出循环
        new_trigger_added = False
        
        # 首先：触发所有尚未触发的常驻条目 (Constant)
        for idx, entry in enumerate(entries):
            if idx in triggered_indexes:
                continue
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            if bool(entry.get("constant", False)):
                triggered_indexes.add(idx)
                triggered_entries.append(entry)
                # 常驻条目不更新 new_trigger_added，不干扰循环提前退出的判断
                content = entry.get("content", "")
                if content:
                    current_scan_text += "\n" + content
        
        # 记录本轮搜索中匹配到的关键词
        matched_primaries = {}
        matched_secondaries = {}
        
        # 匹配不区分大小写的关键词
        if has_insensitive:
            text_lower = current_scan_text.lower()
            for start, end, key, value in ac_insensitive.search_all(text_lower):
                idx, key_type = value
                if idx in triggered_indexes:
                    continue
                if key_type == "primary":
                    matched_primaries.setdefault(idx, set()).add(key)
                else:
                    matched_secondaries.setdefault(idx, set()).add(key)
                    
        # 匹配区分大小写的关键词
        if has_sensitive:
            for start, end, key, value in ac_sensitive.search_all(current_scan_text):
                idx, key_type = value
                if idx in triggered_indexes:
                    continue
                if key_type == "primary":
                    matched_primaries.setdefault(idx, set()).add(key)
                else:
                    matched_secondaries.setdefault(idx, set()).add(key)
                    
        # 评估触发条件
        for idx in (set(matched_primaries.keys()) | set(matched_secondaries.keys())):
            if idx in triggered_indexes:
                continue
                
            entry = entries[idx]
            selective = bool(entry.get("selective", False))
            
            keys = entry.get("keys", [])
            if not isinstance(keys, list):
                keys = [keys] if keys else []
            has_primary_keys = any(k for k in keys if k)
            
            secondary_keys = entry.get("secondary_keys", [])
            if not isinstance(secondary_keys, list):
                secondary_keys = [secondary_keys] if secondary_keys else []
            has_secondary_keys = any(sk for sk in secondary_keys if sk)
            
            primary_matched = (idx in matched_primaries) if has_primary_keys else False
            
            if selective:
                secondary_matched = (idx in matched_secondaries) if has_secondary_keys else False
                matched = primary_matched and secondary_matched
            else:
                matched = primary_matched
                
            if matched:
                triggered_indexes.add(idx)
                triggered_entries.append(entry)
                new_trigger_added = True  # 关键词命中才设为 True
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
