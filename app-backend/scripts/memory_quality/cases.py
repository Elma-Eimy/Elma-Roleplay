"""版本化的验收样本；预录模型响应与评价预期分别维护。"""

import hashlib
import json
import re
from pathlib import Path


def load_suite(path):
    raw = Path(path).read_bytes()
    suite = json.loads(raw.decode("utf-8-sig"))
    validate_suite(suite)
    return suite, hashlib.sha256(raw).hexdigest()


def validate_suite(suite):
    if not isinstance(suite, dict) or suite.get("version") != 1:
        raise ValueError("样本集 version 必须为 1")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("样本集须包含 1–50 个场景")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("场景必须是对象")
        case_id = case.get("id", "")
        if not isinstance(case_id, str) or not re.fullmatch(r"[a-z0-9_-]{1,60}", case_id) or case_id in seen:
            raise ValueError("场景 ID 必须唯一，且仅含小写字母、数字、下划线或短横线")
        seen.add(case_id)
        if not isinstance(case.get("title"), str) or not case["title"].strip():
            raise ValueError(f"{case_id}: 缺少标题")
        cards = case.get("cards")
        if not isinstance(cards, list) or not 2 <= len(cards) <= 100:
            raise ValueError(f"{case_id}: 须有 2–100 张原卡")
        keys = set()
        for card in cards:
            key = card.get("key") if isinstance(card, dict) else None
            if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,40}", key) or key in keys:
                raise ValueError(f"{case_id}: 原卡 key 无效或重复")
            keys.add(key)
            if not isinstance(card.get("content"), str) or not 4 <= len(card["content"]) <= 2000:
                raise ValueError(f"{case_id}: 原卡正文须为 4–2000 字符")
            if not isinstance(card.get("type"), str) or card["type"] not in {"fact", "event", "relationship", "emotion"}:
                raise ValueError(f"{case_id}: 记忆类型无效")
        allowed = case.get("allowed_groups")
        if not isinstance(allowed, list):
            raise ValueError(f"{case_id}: 缺少 allowed_groups")
        for bucket in allowed:
            if not isinstance(bucket, list) or len(bucket) < 2 or any(not isinstance(key, str) for key in bucket) or len(set(bucket)) != len(bucket) or not set(bucket) <= keys:
                raise ValueError(f"{case_id}: allowed_groups 来源无效")
        groups = case.get("replay_groups")
        if not isinstance(groups, list):
            raise ValueError(f"{case_id}: 缺少 replay_groups")
        for group in groups:
            if (not isinstance(group, dict) or not isinstance(group.get("source_keys"), list)
                    or not 2 <= len(group["source_keys"]) <= 12
                    or any(not isinstance(key, str) for key in group["source_keys"])
                    or len(set(group["source_keys"])) != len(group["source_keys"])
                    or not set(group["source_keys"]) <= keys
                    or not isinstance(group.get("kind"), str) or group["kind"] not in {"event", "duplicate"}
                    or not isinstance(group.get("content"), str) or not 4 <= len(group["content"].strip()) <= 500
                    or not isinstance(group.get("reason"), str) or not 1 <= len(group["reason"].strip()) <= 160):
                raise ValueError(f"{case_id}: 回放来源无效")
        facts = case.get("facts")
        if not isinstance(facts, list) or not facts:
            raise ValueError(f"{case_id}: 缺少保真审阅要点")
        for fact in facts:
            if not isinstance(fact, dict) or not isinstance(fact.get("description"), str):
                raise ValueError(f"{case_id}: 保真要点无效")
            anchors = fact.get("anchors")
            if not isinstance(anchors, list) or not anchors or any(
                not isinstance(options, list) or not options or any(not isinstance(word, str) or not word for word in options)
                for options in anchors
            ):
                raise ValueError(f"{case_id}: 字面线索须为非空的同义词分组")
        questions = case.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"{case_id}: 缺少回忆问题")
        for question in questions:
            if not isinstance(question, dict) or not isinstance(question.get("text"), str) or not question["text"]:
                raise ValueError(f"{case_id}: 回忆问题无效")
            indices = question.get("fact_indices")
            if not isinstance(indices, list) or not indices or any(type(i) is not int or not 0 <= i < len(facts) for i in indices):
                raise ValueError(f"{case_id}: 问题引用的保真要点无效")


def contains_anchors(text, fact):
    text = text.casefold()
    return all(any(word.casefold() in text for word in options) for options in fact["anchors"])
