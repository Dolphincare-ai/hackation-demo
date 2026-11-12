from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from ..models import Task, User
from ..workflows.invoice_audit import flow
from .deps import acting_user, session_dep, x_user
from .serialize import task_out

router = APIRouter()


@router.get("/tasks")
def list_tasks(role: str | None = None, user_id: str | None = None, status: str = "open", session=Depends(session_dep)):
    if user_id and not role:
        u = session.get(User, user_id)
        role = u.role if u else None
    q = select(Task).where(Task.status == status).order_by(Task.due_at)
    return [task_out(t) for t in session.exec(q) if role is None or t.role == role]


class ResolveBody(BaseModel):
    user_id: str | None = None
    response: str
    note: str | None = None


@router.post("/tasks/{task_id}/resolve")
def resolve(task_id: int, body: ResolveBody, session=Depends(session_dep), x_user_id=Depends(x_user)):
    user = acting_user(session, body.user_id, x_user_id)
    try:
        run = flow.resolve_task(session, user, task_id, body.response, body.note)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"ok": True, "run_id": run.id, "state": run.state}
