"""SLA scanner: raises escalation_level one step at a time per the ladders. Generic, no invoice logic.

Ladders come from core/settings.py, so a "this run only" or playbook change to `ladders.<kind>`
takes effect on the next scan. Hours are measured since task creation, except for kinds listed
in config `ladder_from_due` (measured since due_at).
"""
from datetime import timedelta

from sqlmodel import Session, select

from ..config import get_config
from ..models import Run, Task
from . import audit, clock, notify, settings

CHANNELS = {"email", "teams", "text"}


def _recipients(step: dict, task: Task) -> list[str]:
    cfg = get_config()
    out = []
    for to in step.get("to", []):
        role = {"assignee_role": task.role, "backup_approver": cfg["backup_approver_role"]}.get(to, to)
        if role not in out:
            out.append(role)
    return out


def scan(session: Session) -> int:
    """Returns how many tasks were escalated. Running it twice at the same time changes nothing."""
    now = clock.now()
    from_due = set(get_config().get("ladder_from_due", []))
    escalated = 0
    for task in session.exec(select(Task).where(Task.status == "open")).all():
        run = session.get(Run, task.run_id)
        if run is None:
            continue
        ladder = settings.effective(run.type, f"ladders.{task.kind}", run, default=[]) or []
        if task.escalation_level >= len(ladder):
            continue
        step = ladder[task.escalation_level]
        base = task.due_at if task.kind in from_due else task.created_at
        if now < base + timedelta(hours=float(step["after_h"])):
            continue
        task.escalation_level += 1
        task.last_escalated_at = now
        session.add(task)
        to_roles = _recipients(step, task)
        audit.log(session, "system", "task_escalated", run.id, {
            "task_id": task.id, "kind": task.kind, "level": task.escalation_level,
            "action": step["action"], "to": to_roles,
        })
        late = "is late" if now > task.due_at else "is still open"
        verb = "Reminder" if step["action"] == "remind" else "Alert"
        channel = task.via if task.via in CHANNELS else "teams"
        for role in to_roles:
            notify.send(session, run_id=run.id, channel=channel, to_role=role,
                        subject=f"{verb}: {task.title}",
                        body=f"'{task.title}' (assigned to {task.role.replace('_', ' ')}) {late}. "
                             f"Due {task.due_at:%b %d %H:%M}.")
        escalated += 1
    return escalated
