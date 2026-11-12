import json

from sqlmodel import Session

from ..models import AuditLog
from . import clock


def log(session: Session, actor: str, action: str, run_id: int | None = None, detail: dict | None = None) -> AuditLog:
    """Write one audit row. Every state change, task change, AI call, notification and approval goes through here."""
    row = AuditLog(at=clock.now(), actor=actor, run_id=run_id, action=action, detail_json=json.dumps(detail or {}, default=str))
    session.add(row)
    session.flush()
    return row
