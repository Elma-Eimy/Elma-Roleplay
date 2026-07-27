import json
import random
import re
from typing import Optional
from core.config import settings
from services.lorebook.parse_lorebook import (
    normalize_lorebook_depth,
    normalize_lorebook_keys,
    normalize_lorebook_position,
    normalize_lorebook_role,
    normalize_probability,
    normalize_selective_logic,
)


LOREBOOK_INSERTION_POSITIONS = (
    "before_char",
    "after_char",
    "before_examples",
    "after_examples",
    "top_an",
    "bottom_an",
    "at_depth",
    "outlet",
)


def empty_lorebook_result() -> dict:
    """返回完整且彼此独立的世界书位置桶。"""
    return {position: [] for position in LOREBOOK_INSERTION_POSITIONS}


def _entry_extensions(entry: dict) -> dict:
    extensions = entry.get("extensions")
    return extensions if isinstance(extensions, dict) else {}


def _entry_value(entry: dict, *names: str, default=None):
    """按顶级字段优先、extensions 次之读取多种兼容字段名。"""
    extensions = _entry_extensions(entry)
    for source in (entry, extensions):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
    return default


def _entry_enabled(entry: dict) -> bool:
    if "enabled" in entry:
        return bool(entry["enabled"])
    return not bool(_entry_value(entry, "disable", default=False))


def _coerce_keys(raw_keys) -> list[str]:
    return normalize_lorebook_keys(raw_keys)


def _entry_keys(entry: dict, *, secondary: bool = False) -> list[str]:
    if secondary:
        raw_keys = _entry_value(
            entry,
            "secondary_keys",
            "keysecondary",
            "secondaryKeys",
            default=[],
        )
    else:
        raw_keys = _entry_value(entry, "keys", "key", default=[])
    return _coerce_keys(raw_keys)


def _compile_regex_key(
    raw_key: str,
    *,
    force_regex: bool,
    case_sensitive: bool,
) -> Optional[re.Pattern]:
    """把 JavaScript 风格 `/pattern/flags` 安全转换为 Python 正则。"""
    pattern_text = raw_key
    flags = 0 if case_sensitive else re.IGNORECASE
    is_delimited = False

    if raw_key.startswith("/") and len(raw_key) > 1:
        closing_slash = raw_key.rfind("/")
        if closing_slash > 0:
            is_delimited = True
            pattern_text = raw_key[1:closing_slash]
            raw_flags = raw_key[closing_slash + 1 :]
            # 显式 JavaScript flags 决定正则大小写；g/y/u/d/v 不影响 Python 搜索语义。
            flags = 0
            if "i" in raw_flags:
                flags |= re.IGNORECASE
            if "m" in raw_flags:
                flags |= re.MULTILINE
            if "s" in raw_flags:
                flags |= re.DOTALL

    if not force_regex and not is_delimited:
        return None
    try:
        return re.compile(pattern_text, flags)
    except re.error:
        # 无效正则不能中断整轮生成，也不回退为宽松的字面量误触发。
        return None


def _passes_probability(entry: dict) -> bool:
    use_probability = bool(
        _entry_value(
            entry,
            "use_probability",
            "useProbability",
            default=True,
        )
    )
    if not use_probability:
        return True
    probability = normalize_probability(
        _entry_value(entry, "probability", default=100)
    )
    if probability <= 0:
        return False
    if probability >= 100:
        return True
    return random.random() * 100 < probability


def _matches_optional_filter(
    entry: dict,
    matched_secondary_indexes: set[int],
) -> bool:
    """评估 SillyTavern Optional Filter 的四种组合逻辑。"""
    secondary_keys = _entry_keys(entry, secondary=True)
    if not bool(_entry_value(entry, "selective", default=False)):
        return True
    if not secondary_keys:
        # 官方语义：没有可选过滤关键词时忽略 Optional Filter。
        return True

    matched_count = len(matched_secondary_indexes)
    all_matched = matched_count >= len(secondary_keys)
    any_matched = matched_count > 0
    logic = normalize_selective_logic(
        _entry_value(
            entry,
            "selective_logic",
            "selectiveLogic",
            default=0,
        )
    )
    if logic == "and_all":
        return all_matched
    if logic == "not_any":
        return not any_matched
    if logic == "not_all":
        return not all_matched
    return any_matched


def _coerce_entry_list(raw_entries) -> list[dict]:
    if isinstance(raw_entries, list):
        return [entry for entry in raw_entries if isinstance(entry, dict)]
    if isinstance(raw_entries, dict):
        return [
            entry
            for entry in raw_entries.values()
            if isinstance(entry, dict)
        ]
    return []


def process_lorebook(
    character,
    recent_history: Optional[list],
    user_message: Optional[str]
) -> dict:
    """
    处理角色专属的世界书（Lorebook/CharacterBook）匹配与筛选。
    """
    if not recent_history and not user_message:
        return empty_lorebook_result()

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
        
    embedded_entries = _coerce_entry_list(character_book.get("entries", []))
        
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
                    independent_entries.extend(_coerce_entry_list(lb_entries))
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
        return empty_lorebook_result()
    
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
    from services.lorebook.ahocorasick import AhoCorasick
    
    ac_insensitive = AhoCorasick()
    ac_sensitive = AhoCorasick()
    
    has_insensitive = False
    has_sensitive = False
    regex_matchers = []
    
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict) or not _entry_enabled(entry):
            continue
        # 常驻条目不需要加入自动机，会在扫描时直接触发
        if bool(_entry_value(entry, "constant", "constant_activation", default=False)):
            continue
            
        case_sensitive = bool(
            _entry_value(
                entry,
                "case_sensitive",
                "caseSensitive",
                default=False,
            )
        )
        use_regex = bool(
            _entry_value(
                entry,
                "use_regex",
                "useRegex",
                default=False,
            )
        )
        
        # 提取 Keys 与 Secondary Keys
        keys = _entry_keys(entry)
        secondary_keys = _entry_keys(entry, secondary=True)

        for key_type, candidate_keys in (
            ("primary", keys),
            ("secondary", secondary_keys),
        ):
            for key_index, key in enumerate(candidate_keys):
                regex = _compile_regex_key(
                    key,
                    force_regex=use_regex,
                    case_sensitive=case_sensitive,
                )
                if regex is not None:
                    regex_matchers.append((idx, key_type, key_index, regex))
                elif use_regex or key.startswith("/"):
                    # 已声明为正则但编译失败的关键词不应回退为普通子串。
                    continue
                elif case_sensitive:
                    ac_sensitive.add_keyword(
                        key,
                        (idx, key_type, key_index),
                    )
                    has_sensitive = True
                else:
                    ac_insensitive.add_keyword(
                        key.lower(),
                        (idx, key_type, key_index),
                    )
                    has_insensitive = True
                    
    if has_insensitive:
        ac_insensitive.make_automaton()
    if has_sensitive:
        ac_sensitive.make_automaton()
        
    # 5. 条目触发匹配 (支持递归扫描)
    max_passes = settings.APP_LOREBOOK_MAX_RECURSIVE_PASSES if recursive_scanning else 1
    triggered_indexes = set()
    probability_rejected_indexes = set()
    triggered_entries = []
    
    current_scan_text = scan_text
    
    for _ in range(max_passes):
        # Bug5修复：将 constant 条目的触发和关键词匹配的触发分离记录。
        # new_trigger_added 仅跟踪"是否有新关键词命中"，不受 constant 常驻触发影响，
        # 从而当只有常驻条目被识别时能尽早退出循环
        new_trigger_added = False
        
        # 首先：触发所有尚未触发的常驻条目 (Constant)
        for idx, entry in enumerate(entries):
            if idx in triggered_indexes or idx in probability_rejected_indexes:
                continue
            if not isinstance(entry, dict) or not _entry_enabled(entry):
                continue
            if bool(_entry_value(entry, "constant", "constant_activation", default=False)):
                if not _passes_probability(entry):
                    probability_rejected_indexes.add(idx)
                    continue
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
                idx, key_type, key_index = value
                if idx in triggered_indexes or idx in probability_rejected_indexes:
                    continue
                if key_type == "primary":
                    matched_primaries.setdefault(idx, set()).add(key_index)
                else:
                    matched_secondaries.setdefault(idx, set()).add(key_index)
                    
        # 匹配区分大小写的关键词
        if has_sensitive:
            for start, end, key, value in ac_sensitive.search_all(current_scan_text):
                idx, key_type, key_index = value
                if idx in triggered_indexes or idx in probability_rejected_indexes:
                    continue
                if key_type == "primary":
                    matched_primaries.setdefault(idx, set()).add(key_index)
                else:
                    matched_secondaries.setdefault(idx, set()).add(key_index)

        # JavaScript 风格和 use_regex 条目走独立正则匹配路径；无效模式已在
        # 编译阶段跳过，不会影响其它世界书条目。
        for idx, key_type, key_index, regex in regex_matchers:
            if idx in triggered_indexes or idx in probability_rejected_indexes:
                continue
            if regex.search(current_scan_text):
                if key_type == "primary":
                    matched_primaries.setdefault(idx, set()).add(key_index)
                else:
                    matched_secondaries.setdefault(idx, set()).add(key_index)
                    
        # 评估触发条件
        for idx in sorted(
            set(matched_primaries.keys()) | set(matched_secondaries.keys())
        ):
            if idx in triggered_indexes or idx in probability_rejected_indexes:
                continue
                
            entry = entries[idx]
            primary_matched = bool(matched_primaries.get(idx))
            matched = primary_matched and _matches_optional_filter(
                entry,
                matched_secondaries.get(idx, set()),
            )
                
            if matched:
                if not _passes_probability(entry):
                    # 同一轮生成只掷一次概率，递归扫描不能反复重试。
                    probability_rejected_indexes.add(idx)
                    continue
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
            
    # 6. 分类位置归宿。这里不改变上面的预算筛选，只保留并归一化注入元数据。
    result = empty_lorebook_result()
    for entry in selected_entries:
        item_extensions = entry.get("extensions")
        if not isinstance(item_extensions, dict):
            item_extensions = {}

        raw_position = entry.get("position")
        if raw_position is None:
            raw_position = item_extensions.get("position")
        position = normalize_lorebook_position(raw_position)
        normalized_entry = dict(entry)
        normalized_entry["position"] = position
        raw_depth = entry.get("depth")
        if raw_depth is None:
            raw_depth = item_extensions.get("depth")
        normalized_entry["depth"] = normalize_lorebook_depth(
            raw_depth
        )
        raw_role = entry.get("role")
        if raw_role is None:
            raw_role = item_extensions.get("role")
        normalized_entry["role"] = normalize_lorebook_role(
            raw_role
        )
        result[position].append(normalized_entry)

    return result
