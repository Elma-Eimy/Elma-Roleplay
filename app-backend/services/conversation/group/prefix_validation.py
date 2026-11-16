"""候选前缀与回应依据校验；供写入、恢复和只读预览共用。"""
from core.models import GroupContentItem
from . import dispatch_service as dispatches, legacy_protocol
from .turn_plan import _validate_basis, _sources


def saved_steps(candidate_id, db):
    return db.query(GroupContentItem).filter_by(candidate_id=candidate_id, kind="utterance").count()


def validate_prefix(round_, candidate, db):
    if candidate.dispatch_version == 1:
        return dispatches.validate_prefix(round_, candidate, db, resolve_basis=_validate_basis)
    return legacy_protocol.validate_prefix(round_, candidate, db,
        resolve_basis=_validate_basis, read_sources=_sources)
