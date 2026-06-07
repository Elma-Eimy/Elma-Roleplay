import json
import hashlib
import os
from typing import Optional
from core.config import settings
from services.chat_engine import chroma_client, openai_ef

def sync_lorebook_collection(character_id: int, entries: list) -> bool:
    """
    自愈式世界书索引同步：
    通过计算 entries 的内容 Hash 存入一个特殊的 document_id = "__hash__"，
    并在每次匹配前进行比对。如果发生任何变更或不存在，则清空重建该 collection 的索引，
    实现无感升级与配置同步。
    """
    collection_name = f"lorebook_{character_id}"
    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=openai_ef
    )
    
    # 仅对启用且非全局常驻 (non-constant) 的条目进行向量表示及相似度匹配
    vector_entries = [
        e for e in entries 
        if isinstance(e, dict) and e.get("enabled", True) and not e.get("constant", False)
    ]
    
    # 构建内容 Payload Hash 串
    hash_payload = json.dumps(vector_entries, sort_keys=True)
    current_hash = hashlib.md5(hash_payload.encode('utf-8')).hexdigest()
    
    # 检查已存哈希
    needs_reindex = True
    try:
        stored_hash_doc = collection.get(ids=["__hash__"])
        if stored_hash_doc and stored_hash_doc.get("documents"):
            stored_hash = stored_hash_doc["documents"][0]
            if stored_hash == current_hash:
                needs_reindex = False
    except Exception:
        pass
        
    if needs_reindex:
        print(f"[INFO] Lorebook: 检测到角色 {character_id} 的世界书发生变化，正在重构向量索引...")
        # 1. 清空原 collection 所有条目
        try:
            all_docs = collection.get(include=[])
            if all_docs and all_docs.get("ids"):
                collection.delete(ids=all_docs["ids"])
        except Exception as e:
            print(f"[WARN] 清空旧世界书索引失败: {e}")
            
        # 2. 批量构建新增条目
        ids = []
        documents = []
        metadatas = []
        
        # 写入版本特征哈希，标识此 collection 已就绪
        ids.append("__hash__")
        documents.append(current_hash)
        metadatas.append({"entry_idx": -1, "position": "", "priority": 0, "insertion_order": 0, "is_hash": True})
        
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            if bool(entry.get("constant", False)):
                continue
                
            content = entry.get("content", "").strip()
            if not content:
                continue
                
            ids.append(f"entry_{idx}")
            documents.append(content)
            metadatas.append({
                "entry_idx": idx,
                "position": str(entry.get("position", "after_char")),
                "priority": int(entry.get("priority", 100)),
                "insertion_order": int(entry.get("insertion_order", 100)),
                "is_hash": False
            })
            
        if len(ids) > 1:
            try:
                collection.add(ids=ids, documents=documents, metadatas=metadatas)
                print(f"[INFO] Lorebook: 角色 {character_id} 成功向量化了 {len(ids)-1} 条世界书背景条目。")
            except Exception as e:
                print(f"[ERROR] 角色 {character_id} 向量化世界书失败: {e}")
                return False
    return True


def process_lorebook(
    character,
    recent_history: Optional[list],
    user_message: Optional[str]
) -> dict:
    """
    处理角色专属的世界书（Lorebook/CharacterBook）匹配与筛选。
    支持：
      1. 常驻条目 (constant=True) 自动使能。
      2. 关键词匹配 (Aho-Corasick) 状态触发。
      3. 向量语义匹配 (Semantic Similarity) 状态触发。
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
    
    triggered_indexes = set()
    triggered_entries = []

    # 4. Aho-Corasick 精准关键词触发分支
    # 构建 Aho-Corasick 自动机 (仅构建一次以取得最优匹配性能)
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
    current_scan_text = scan_text
    
    for _ in range(max_passes):
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
                new_trigger_added = True
                content = entry.get("content", "")
                if content:
                    current_scan_text += "\n" + content
                    
        if not new_trigger_added:
            break

    # 6. ChromaDB 向量语义模糊匹配分支
    if settings.APP_LOREBOOK_SEMANTIC_ENABLED:
        try:
            # 6.1 同步构建/更新 Chroma 索引
            if sync_lorebook_collection(character.id, entries):
                # 6.2 查询 collection
                collection_name = f"lorebook_{character.id}"
                collection = chroma_client.get_collection(
                    name=collection_name,
                    embedding_function=openai_ef
                )
                
                # 6.3 用最新消息做检索 query
                semantic_query = user_message if user_message else scan_text
                
                # 查询匹配的条目
                query_res = collection.query(
                    query_texts=[semantic_query],
                    n_results=settings.APP_LOREBOOK_SEMANTIC_TOP_K,
                    where={"is_hash": False}, # 排除哈希条目
                    include=["metadatas", "distances"]
                )
                
                if query_res and query_res.get("metadatas") and query_res["metadatas"][0]:
                    metas = query_res["metadatas"][0]
                    dists = query_res["distances"][0] if query_res.get("distances") else [0.0] * len(metas)
                    
                    for meta, dist in zip(metas, dists):
                        if dist <= settings.APP_LOREBOOK_SEMANTIC_MAX_DISTANCE:
                            idx = int(meta["entry_idx"])
                            if idx not in triggered_indexes and idx < len(entries):
                                entry = entries[idx]
                                # 对于 selective (选择性触发) 条目，影响面较广，保留原来的硬性匹配逻辑
                                selective = bool(entry.get("selective", False))
                                if selective:
                                    continue
                                
                                triggered_indexes.add(idx)
                                triggered_entries.append(entry)
                                print(f"[INFO] Lorebook: 向量检索召回了世界书条目 #{idx} (距离: {dist:.3f})")
        except Exception as e:
            print(f"[WARN] Lorebook: 向量检索世界书失败 (已忽略): {e}")

    # 7. 预算控制与排序
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
            
    # 8. 分类位置归宿
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
