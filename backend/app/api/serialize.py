import json

from ..core import tasks as task_engine


def j(s, default=None):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def task_out(t) -> dict:
    return {"id": t.id, "run_id": t.run_id, "kind": t.kind, "title": t.title, "role": t.role, "status": t.status,
            "assignee_id": t.assignee_id, "created_at": t.created_at, "due_at": t.due_at,
            "late": task_engine.is_late(t), "escalation_level": t.escalation_level, "via": t.via,
            "payload": j(t.payload_json, {}), "blocks": j(t.blocks_json, []), "completed_at": t.completed_at,
            "completed_by": t.completed_by, "completion_source": t.completion_source}


def finding_out(f) -> dict:
    d = f.model_dump()
    d["evidence"] = j(d.pop("evidence_json"), {})
    return d
