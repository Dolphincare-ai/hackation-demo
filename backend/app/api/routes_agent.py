from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from ..ai import chat as chat_mod
from ..models import AuditLog, Task
from .serialize import j
from .deps import acting_user, session_dep, x_user

router = APIRouter()


class ChatBody(BaseModel):
    user_id: str | None = None
    message: str
    run_id: int | None = None
    conversation_id: int | None = None


@router.post("/agent/chat")
def post_chat(body: ChatBody, session=Depends(session_dep), x_user_id=Depends(x_user)):
    user = acting_user(session, body.user_id, x_user_id)
    try:
        out = chat_mod.chat(session, user.id if user else "", body.message.strip()[:2000], body.run_id, body.conversation_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return out


@router.get("/agent/chat/history")
def get_history(user_id: str | None = None, limit: int = 50, run_id: int | None = None,
                conversation_id: int | None = None,
                session=Depends(session_dep), x_user_id=Depends(x_user)):
    """conversation_id: only that conversation. run_id omitted: every message. run_id=0: only general. run_id=N: that workflow."""
    user = acting_user(session, user_id, x_user_id)
    if not user:
        return []
    rows = chat_mod.history(session, user.id, 200, conversation_id)
    if run_id is not None:
        rows = [m for m in rows if (m["run_id"] or 0) == run_id]
    return rows[-min(limit, 200):]


@router.get("/agent/conversations")
def get_conversations(user_id: str | None = None, session=Depends(session_dep), x_user_id=Depends(x_user)):
    user = acting_user(session, user_id, x_user_id)
    return chat_mod.conversations(session, user.id) if user else []


def _sentence(session, a, detail) -> tuple[str, dict]:
    """One audit row -> (plain sentence, extra fields). Empty sentence = not worth showing in the chat."""
    d = detail
    act = a.action
    if act == "inbox_checked":
        n = d.get("new_emails", 0)
        return (f"I checked the inbox and found {n} new email{'s' if n != 1 else ''}." if n else "I checked the inbox. Nothing new."), {}
    if act == "email_ignored":
        return f"I skipped an email that is not an invoice: \"{d.get('subject', '')}\".", {}
    if act == "run_started":
        return "I found an invoice email and started a workflow for it.", {}
    if act == "state_changed":
        return f"Workflow moved to {str(d.get('to', '')).replace('_', ' ').lower()}.", {}
    if act == "checks_run":
        parts = ", ".join(f"{v} {k}" for k, v in d.items() if isinstance(v, int))
        return "I ran the automatic checks" + (f": {parts}." if parts else "."), {}
    if act == "task_created":
        t = session.get(Task, d.get("task_id"))
        if t is None:
            return "", {}
        return f"New task for {t.role.replace('_', ' ')}: {t.title}", {"task_id": t.id, "kind": t.kind, "role": t.role, "run_id": t.run_id}
    if act == "task_completed":
        who = "the bank feed" if d.get("source") == "system_observed" else (a.actor or "someone")
        return f"A {str(d.get('kind', '')).replace('_', ' ')} task was closed by {who}.", {}
    if act == "task_escalated":
        return f"A {str(d.get('kind', '')).replace('_', ' ')} task is late. I escalated it to level {d.get('level')} and alerted {', '.join(d.get('to') or []) or 'the backup'}.", {}
    if act == "finding_resolved":
        return f"{d.get('check', 'A')} check was resolved by hand: {str(d.get('response', '')).replace('_', ' ')}.", {}
    if act == "funds_ok":
        return "The bank balance covers the payment. I created the payment task.", {}
    if act == "funds_insufficient":
        return "Not enough funds after the reserve. I created a funds task and will retry.", {}
    if act == "payment_matched":
        return "I saw the payment on the bank feed and closed the payment task.", {}
    if act == "payment_mismatch":
        return "A bank transaction looked like this payment but the amount is different. I left it open.", {}
    if act == "reply_sent":
        return "I replied on the original email thread.", {}
    if act == "notification_sent":
        return f"I notified {str(d.get('to_role') or ', '.join(d.get('to') or [])).replace('_', ' ')}: {d.get('subject', '')}", {}
    return "", {}


@router.get("/agent/activity")
def get_activity(user_id: str | None = None, after_id: int = 0, run_id: int | None = None,
                 session=Depends(session_dep), x_user_id=Depends(x_user)):
    """What the bot has done since `after_id`, in plain words. after_id=-1 returns only the cursor (start listening now).
    `mine` is true when a new task is for the caller's role, so the chat can pop up."""
    user = acting_user(session, user_id, x_user_id)
    last = session.exec(select(AuditLog).order_by(AuditLog.id.desc())).first()
    cursor = last.id if last else 0
    if after_id < 0:
        return {"cursor": cursor, "events": []}
    # Only runs this user started from the chat (chat_run_watched) are narrated here.
    # Everything the bot does on its own is shown in the Workflows tab, not in the chat.
    watched = {a.run_id for a in session.exec(select(AuditLog).where(AuditLog.action == "chat_run_watched")).all()
               if user and j(a.detail_json, {}).get("user") == user.id}
    q = select(AuditLog).where(AuditLog.id > after_id).order_by(AuditLog.id)
    if run_id:
        q = q.where(AuditLog.run_id == run_id)
    events = []
    for a in session.exec(q).all():
        if a.run_id not in watched:
            continue
        text, extra = _sentence(session, a, j(a.detail_json, {}))
        if not text:
            continue
        events.append({"id": a.id, "at": a.at, "run_id": a.run_id, "action": a.action, "text": text,
                       "mine": bool(user and extra.get("role") == user.role), **extra})
    return {"cursor": cursor, "events": events}
