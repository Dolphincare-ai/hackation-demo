"""The bot: one generic tick. No invoice logic here, handlers come from workflows/registry.py.

One tick does, in order:
  1. read the inbox if it is due (every tick, or once a day, per the playbook) and offer each
     email to the registered workflows
  2. advance every open run through its workflow handler
  3. run the SLA scanner (escalations and backup alerts)
  4. let each workflow observe outside systems (e.g. the bank feed)

A tick is idempotent: with no new input it changes nothing. It never moves money.
"""
from datetime import datetime, time

from sqlmodel import Session, select

from ..connectors import get_connectors
from ..models import KV, Run
from ..workflows import registry
from . import audit, clock, settings, sla


def _kv_get(session: Session, key: str) -> str | None:
    row = session.get(KV, key)
    return row.value if row else None


def _kv_set(session: Session, key: str, value: str) -> None:
    row = session.get(KV, key)
    if row is None:
        session.add(KV(key=key, value=value))
    else:
        row.value = value
        session.add(row)


def _poll_due(session: Session, run_type: str) -> bool:
    cfg = settings.effective(run_type, "inbox_poll", default={}) or {}
    if cfg.get("mode", "every_tick") == "every_tick":
        return True
    # daily: due once the clock passes today's daily_at and we have not polled since then
    hh, mm = (cfg.get("daily_at") or "07:00").split(":")
    now = clock.now()
    slot = datetime.combine(now.date(), time(int(hh), int(mm)))
    if now < slot:
        return False
    last = _kv_get(session, f"last_inbox_poll:{run_type}")
    return last is None or datetime.fromisoformat(last) < slot


def poll_inbox(session: Session, force: bool = False) -> int:
    """Read the mailbox if any workflow is due (or force=True). Returns how many emails started a run."""
    handlers = registry.all_handlers()
    due = [h for h in handlers if force or _poll_due(session, h.run_type)]
    if not due:
        return 0
    now = clock.now().isoformat()
    for h in due:
        _kv_set(session, f"last_inbox_poll:{h.run_type}", now)
    emails = get_connectors().mailbox.poll()
    if emails or force:
        audit.log(session, "system", "inbox_checked", None, {"new_emails": len(emails), "forced": force})
    started = 0
    for email in emails:
        if any(h.on_email(session, email) for h in handlers):
            started += 1
        else:
            audit.log(session, "system", "email_ignored", None, {"email_id": email.id, "subject": email.subject})
    return started


def tick(session: Session, *, force_poll: bool = False) -> dict:
    started = poll_inbox(session, force=force_poll)
    for run in session.exec(select(Run).where(Run.closed_at == None)).all():  # noqa: E711
        handler = registry.get(run.type)
        if handler is not None:
            handler.advance(session, run)
    escalated = sla.scan(session)
    for handler in registry.all_handlers():
        handler.observe(session)
    session.commit()
    return {"runs_started": started, "escalated": escalated, "at": clock.now().isoformat()}
