"""独占进程运行权后才能将上次中断的群聊候选标为失败。"""
from contextlib import contextmanager
from pathlib import Path
import os

from sqlalchemy import text

from core.database import engine
from core.models import GroupRoundCandidate
from sqlalchemy.orm import Session


class _RuntimeOwner:
    def __init__(self, db_engine):
        self.engine = db_engine
        self.active = True


@contextmanager
def group_runtime(db_engine=engine):
    # 与 SQLite 文件绑定，避免另一个 Worker 将仍在执行的候选误标中断。
    database = db_engine.url.database
    if not database or database == ":memory:":
        raise RuntimeError("群聊运行权需要独立的 SQLite 文件")
    path = Path(database).resolve().with_suffix(Path(database).suffix + ".runtime.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    owner = None
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise RuntimeError("同一数据库仅支持一个应用进程，请使用单 Worker 部署") from exc
        owner = _RuntimeOwner(db_engine)
        yield owner
    finally:
        if owner is not None:
            owner.active = False
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def fail_interrupted_group_candidates(owner):
    """仅由持有 group_runtime 的启动流程调用，不恢复或重发模型请求。"""
    if not isinstance(owner, _RuntimeOwner) or not owner.active:
        raise RuntimeError("恢复中断候选前必须持有数据库运行权")
    with Session(owner.engine) as db:
        db.execute(text("BEGIN IMMEDIATE"))
        db.query(GroupRoundCandidate).filter_by(status="generating").update({
            "status": "failed", "error_code": "process_interrupted",
            "revision": GroupRoundCandidate.revision + 1,
        }, synchronize_session=False)
        db.commit()
