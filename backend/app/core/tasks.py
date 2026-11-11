"""Generic task engine. Every wait is a task with a due time. No invoice logic here."""
import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from ..config import get_config
from ..models import Task
from . import audit, clock


def create_task(
    session: Session,
    *,
    run_id: int,
    kind: str,
    title: str,
    role: str | None = None,
    due_at: datetime | None = None,
    due_in_h: float | None = None,
    assignee_id: str | None = None,
    via: str = "email",
    payload: dict | None = None,
    blocks: list | None = None,
    actor: str = "system",
) -> Task:
    """Role and due time fall back to config.yaml `task_defaults` for the kind."""
    defaults = get_config()["task_defaults"].get(kind, {})
    role = role or defaults.get("role")
    if role is None:
        raise ValueError(f"No role given and no default for task kind {kind!r}")
    now = clock.now()
    if due_at is None:
        hours = due_in_h if due_in_h is not None else defaults.get("due_h")
        if hours is None:
            raise ValueError(f"No due time given and no default for task kind {kind!r}")
        due_at = now + timedelta(hours=hours)
    task = Task(
        run_id=run_id, kind=kind, title=title, role=role, assignee_id=assignee_id, created_at=now, due_at=due_at,
        via=via, payload_json=json.dumps(payload or {}, default=str), blocks_json=json.dumps(blocks or [], default=str),
    )
    session.add(task)
    session.flush()
    audit.log(session, actor, "task_created", run_id, {"task_id": task.id, "kind": kind, "role": role, "due_at": due_at})
    return task


def complete_task(session: Session, task_id: int, by: str, source: str = "user", note: str | None = None) -> Task:
    """source is `user` or `system_observed` (closed by watching another system)."""
    task = session.get(Task, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    if task.status != "open":
        raise ValueError(f"Task {task_id} is already {task.status}")
    task.status = "done"
    task.completed_at = clock.now()
    task.completed_by = by
    task.completion_source = source
    session.add(task)
    audit.log(session, by, "task_completed", task.run_id, {"task_id": task_id, "kind": task.kind, "source": source, "note": note})
    return task


def cancel_task(session: Session, task_id: int, actor: str = "system", reason: str | None = None) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    if task.status == "open":
        task.status = "cancelled"
        session.add(task)
        audit.log(session, actor, "task_cancelled", task.run_id, {"task_id": task_id, "kind": task.kind, "reason": reason})
    return task


def is_late(task: Task) -> bool:
    return task.status == "open" and task.due_at < clock.now()


def open_tasks(session: Session, run_id: int | None = None, role: str | None = None, kind: str | None = None) -> list[Task]:
    q = select(Task).where(Task.status == "open")
    if run_id is not None:
        q = q.where(Task.run_id == run_id)
    if role is not None:
        q = q.where(Task.role == role)
    if kind is not None:
        q = q.where(Task.kind == kind)
    return list(session.exec(q.order_by(Task.due_at)))
