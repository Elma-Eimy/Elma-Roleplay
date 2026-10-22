"""隔离子进程中的实际服务验收；线上仅生成建议，检索固定为本地词项基线。"""

from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from .cases import contains_anchors


def terms(text):
    tokens = Counter(re.findall(r"[a-z0-9_]+", text.casefold()))
    for span in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.update(span if len(span) == 1 else [span[index:index + 2] for index in range(len(span) - 1)])
    return tokens


def cosine(left, right):
    norm = math.sqrt(sum(value * value for value in left.values()) * sum(value * value for value in right.values()))
    return sum(value * right.get(word, 0) for word, value in left.items()) / norm if norm else 0.0


def matches(metadata, condition):
    if "$and" in condition:
        return all(matches(metadata, item) for item in condition["$and"])
    for key, expected in condition.items():
        actual = metadata.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                return False
        elif actual != expected:
            return False
    return True


class LexicalCollection:
    """即时同步的向量库替身；沿用真实 SQLite 过滤和 retrieve_memories 精排。"""

    def __init__(self, db):
        self.db = db

    def count(self):
        from core.models import MemoryChunk
        return self.db.query(MemoryChunk).count()

    def query(self, *, query_texts, n_results, where, include, ids):
        from core.models import MemoryChunk
        from services.memory.memory_manager import _build_chroma_metadata
        allowed = set(ids)
        query_terms = terms(query_texts[0])
        rows = []
        for card in self.db.query(MemoryChunk).filter(MemoryChunk.chroma_doc_id.in_(allowed)).all():
            metadata = _build_chroma_metadata(card.persona_id, card.memory_type, card.importance_score,
                                             card.origin_session_id, card.created_at, card.source_message_id,
                                             card.source_start_message_id)
            if matches(metadata, where):
                rows.append((1 - cosine(query_terms, terms(card.content)), card, metadata))
        rows.sort(key=lambda row: (row[0], row[1].id))
        rows = rows[:n_results]
        return {"ids": [[row.chroma_doc_id for _, row, _ in rows]], "documents": [[row.content for _, row, _ in rows]],
                "metadatas": [[metadata for _, _, metadata in rows]], "distances": [[distance for distance, _, _ in rows]]}


class RecordedProvider:
    def __init__(self, case, key_ids, delegate=None):
        self.case, self.key_ids, self.delegate = case, key_ids, delegate
        self.raw_response = None
        self.controls = None
        self.prompt_hash = None

    def generate(self, model, messages, **kwargs):
        self.controls = {"model": model, **kwargs}
        system = "\n".join(message["content"] for message in messages if message["role"] == "system")
        self.prompt_hash = hashlib.sha256(system.encode()).hexdigest()
        if self.delegate:
            response = self.delegate.generate(model=model, messages=messages, **kwargs)
        else:
            groups = [{"kind": group["kind"], "source_ids": [self.key_ids[key] for key in group["source_keys"]],
                       "content": group["content"], "reason": group["reason"]} for group in self.case["replay_groups"]]
            response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"groups": groups}, ensure_ascii=False)))])
        self.raw_response = response.choices[0].message.content
        return response


def project(cards, ranked=False):
    rows = []
    for card in (cards if ranked else sorted(cards, key=lambda card: card["id"])):
        row = {key: card[key] for key in ("id", "content", "memory_type", "importance_score")}
        if ranked:
            row.update({key: round(card[key], 6) for key in ("distance", "final_score")})
        rows.append(row)
    return rows


def run_case(case, repeat, mode, db_path):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from core.models import Base, Character, Session, SessionPersona, ChatMessage, MessageRole, MemoryType, MemoryChunk, OutboxJob
    from services.memory import memory_consolidation_service as service, memory_manager
    from services.memory.session_memory_query_service import query_session_memories
    from services.conversation.session_service import create_session_service
    from services.infrastructure.llm_provider import get_llm_provider

    started = time.monotonic()
    engine = create_engine("sqlite:///" + Path(db_path).as_posix())
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    result = {"case_id": case["id"], "title": case["title"], "repeat": repeat, "expectations": case,
              "checks": [], "before": [], "after": [], "recall": [], "semantic_review": "unreviewed"}
    provider, stage = None, "setup"
    try:
        character = Character(name="林墨", description="虚构验收角色", first_mes="你好")
        story = Session(title=case["title"])
        db.add_all([character, story]); db.flush()
        persona = SessionPersona(session_id=story.id, character_id=character.id)
        db.add(persona); db.flush()
        key_ids = {}
        for card in case["cards"]:
            message = ChatMessage(session_id=story.id, role=MessageRole.user, content=card["content"], is_active=True)
            db.add(message); db.flush()
            chunk = memory_manager.add_memory_chunk(persona.id, character.id, card["content"], MemoryType(card["type"]),
                .7, story.id, message.id, db, source_start_message_id=message.id, auto_commit=False)
            key_ids[card["key"]] = chunk.id
        db.commit()
        last_message_id = message.id

        def active(session_id=story.id):
            return query_session_memories(session_id=session_id, q=None, scope="all", status="active", limit=100, offset=0, db=db)["items"]

        def fork():
            return create_session_service(character.id, story.id, "隔离分支探针", None, last_message_id, db)["session_id"]

        def check(name, passed):
            result["checks"].append({"name": name, "passed": bool(passed)})

        def recall():
            return [project(memory_manager.retrieve_memories(persona.id, character.id, question["text"], db), ranked=True)
                    for question in case["questions"]]

        result["before"] = project(active())
        before_branch = fork()
        before_branch_cards = project(active(before_branch))
        provider = RecordedProvider(case, key_ids, get_llm_provider() if mode == "online" else None)
        with patch.object(service, "get_llm_provider", return_value=provider), patch.object(
                memory_manager, "get_character_collection", return_value=LexicalCollection(db)):
            stage = "recall_before"
            before_recall = recall()
            stage = "preview"
            batch = service.preview(story.id, 0, db)
            result["preview"] = batch
            check("预览不修改原卡或增加向量任务", project(active()) == result["before"] and db.query(OutboxJob).count() == len(case["cards"]))
            check("本批覆盖全部输入原卡", batch["scanned_count"] == len(case["cards"]) and not batch["has_more"])
            allowed = [set(key_ids[key] for key in bucket) for bucket in case.get("allowed_groups", [])]
            check("建议未跨越样本允许的事件或事实分组", all(any(set(group["source_ids"]) <= bucket for bucket in allowed) for group in batch["groups"]))
            result["unmerged_opportunities"] = sum(not any(set(group["source_ids"]) == bucket for group in batch["groups"]) for bucket in allowed)
            stage = "apply"
            if batch["groups"]:
                service.apply(story.id, batch["id"], [group["id"] for group in batch["groups"]], db)
            result["after"] = project(active())
            covered = {card["id"] for card in result["after"] if card["id"] in key_ids.values()}
            for group in batch["groups"]:
                covered.update(group["source_ids"])
            check("全部原卡仍可通过有效原卡或整理来源追溯", covered == set(key_ids.values()) and
                  db.query(MemoryChunk).filter(MemoryChunk.id.in_(key_ids.values())).count() == len(key_ids))
            check("已有分支不受父故事应用影响", project(active(before_branch)) == before_branch_cards)
            stage = "recall_after"
            after_recall = recall()
            for question, before, after in zip(case["questions"], before_recall, after_recall):
                facts = [case["facts"][index] for index in question["fact_indices"]]
                result["recall"].append({"question": question["text"], "facts": [fact["description"] for fact in facts],
                    "before": before, "after": after,
                    "before_cue_hits": sum(any(contains_anchors(card["content"], fact) for card in before) for fact in facts),
                    "after_cue_hits": sum(any(contains_anchors(card["content"], fact) for card in after) for fact in facts)})
            result["fact_cues"] = [{"description": fact["description"],
                "before": any(contains_anchors(card["content"], fact) for card in result["before"]),
                "after": any(contains_anchors(card["content"], fact) for card in result["after"])} for fact in case["facts"]]
            stage = "undo"
            after_branch = fork()
            inherited_after = project(active(after_branch))
            if batch["groups"]:
                service.undo(story.id, batch["id"], db)
            check("撤销恢复当前故事原卡", project(active()) == result["before"])
            check("撤销不改变已继承整理的分支", project(active(after_branch)) == inherited_after)
        result["auto_passed"] = all(check["passed"] for check in result["checks"])
    except Exception as exc:
        db.rollback()
        result["auto_passed"] = False
        result["error"] = {"stage": stage, "type": type(exc).__name__, "message": "本场景执行失败，见阶段与异常类型；原始服务异常不写入报告。"}
    finally:
        result["raw_response"] = provider.raw_response if provider else None
        result["generation_controls"] = provider.controls if provider else None
        result["system_prompt_sha256"] = provider.prompt_hash if provider else None
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        db.close(); engine.dispose()
    return result


def comparison(report, baseline):
    if not baseline:
        return None
    comparable = (baseline.get("suite_hash") == report["suite_hash"] and baseline.get("mode") == report["mode"]
                  and baseline.get("retrieval") == report["retrieval"]
                  and {row["case_id"] for row in baseline["results"]} == {row["case_id"] for row in report["results"]})
    def metrics(results):
        buckets = {}
        for result in results:
            bucket = buckets.setdefault(result["case_id"], [])
            bucket.append(result)
        values = {}
        for key, rows in buckets.items():
            completed = [row for row in rows if not row.get("error")]
            failures = sum(not row.get("auto_passed", False) for row in rows)
            values[key] = {"runs": len(rows), "completed_runs": len(completed), "automatic_failures": failures,
                "automatic_failure_rate": round(failures / len(rows), 3),
                "mean_cards_after": round(sum(len(row.get("after", [])) for row in completed) / len(completed), 2) if completed else None,
                "mean_missing_cues": round(sum(sum(not cue["after"] for cue in row.get("fact_cues", [])) for row in completed) / len(completed), 2) if completed else None}
        return values
    return {"baseline_run_id": baseline.get("run_id"), "comparable": comparable,
            "note": "同样本同模式同检索参数才可直接比较；线索数和卡数不是语义质量分数。",
            "before": metrics(baseline["results"]), "after": metrics(report["results"])}


def stability(results):
    buckets = {}
    for result in results:
        bucket = buckets.setdefault(result["case_id"], {"runs": 0, "failed_runs": 0, "variants": set()})
        bucket["runs"] += 1
        if result.get("error"):
            bucket["failed_runs"] += 1
        else:
            signature = sorted((group["kind"], sorted(group["source_ids"]), " ".join(group["content"].split()))
                               for group in result.get("preview", {}).get("groups", []))
            bucket["variants"].add(json.dumps(signature, ensure_ascii=False))
    return {key: {**bucket, "variants": len(bucket["variants"])} for key, bucket in buckets.items()}


def main():
    workspace = Path(os.environ.get("MEMORY_QUALITY_WORKER_ROOT", "__not_an_eval_workspace__")).resolve()
    if Path.cwd().resolve() != workspace or Path(__file__).resolve().parents[2] != workspace:
        print("请通过 python -m scripts.memory_quality 启动隔离验收。", file=sys.stderr)
        return 2
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if request["mode"] == "offline":
        def deny_network(*args, **kwargs):
            raise RuntimeError("offline evaluation forbids network connections")
        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        socket.create_connection = deny_network
    # 包括导入期客户端在内的所有业务路径均位于启动器创建的临时目录。
    with redirect_stdout(io.StringIO()):
        from core.config import settings
        from core.database import run_migrations
        run_migrations()
        controls = {"top_k": settings.APP_RETRIEVAL_TOP_K, "max_distance": settings.APP_RETRIEVAL_MAX_DISTANCE,
                    "min_importance": settings.APP_RETRIEVAL_MIN_IMPORTANCE,
                    "weight_similarity": settings.APP_RETRIEVAL_WEIGHT_SIMILARITY,
                    "weight_importance": settings.APP_RETRIEVAL_WEIGHT_IMPORTANCE,
                    "weight_time": settings.APP_RETRIEVAL_WEIGHT_TIME,
                    "half_life_turns": settings.APP_RETRIEVAL_HALF_LIFE_TURNS,
                    "candidate_multiplier": settings.APP_RETRIEVAL_CANDIDATE_MULTIPLIER,
                    "ancestor_weight": settings.APP_RETRIEVAL_ANCESTOR_WEIGHT}
        report = {key: request[key] for key in ("run_id", "suite_hash", "mode", "model", "revision", "dirty", "code_sha256", "base_url")}
        report.update(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(), suite_version=request["suite"]["version"],
                      retrieval={"method": "deterministic_chinese_bigram_and_word_cosine", "controls": controls}, results=[])
        for repeat in range(1, request["repeat"] + 1):
            for case in request["suite"]["cases"]:
                path = Path("data") / f"{case['id']}-{repeat}.db"
                report["results"].append(run_case(case, repeat, request["mode"], path))
        report["summary"] = {"total": len(report["results"]), "auto_passed": sum(row["auto_passed"] for row in report["results"]),
                             "semantic_review": "unreviewed"}
        report["stability"] = stability(report["results"])
        report["comparison"] = comparison(report, request["baseline"])
        from .report import render_report
        destination = Path(request["destination"])
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "index.html").write_text(render_report(report), encoding="utf-8")
    return 0 if report["summary"]["auto_passed"] == report["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
