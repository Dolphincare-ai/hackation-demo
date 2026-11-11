"""Notifications: written to the notifications table (the fake Teams / text / email feed). Generic."""
from sqlmodel import Session, select

from ..models import Notification, User
from . import audit, clock


def recipients_for_role(session: Session, role: str) -> list[User]:
    return list(session.exec(select(User).where(User.role == role)))


def send(session: Session, *, run_id: int | None, channel: str, to_role: str, subject: str, body: str,
         thread_ref: str | None = None, actor: str = "system") -> list[Notification]:
    users = recipients_for_role(session, to_role)
    targets = [u.id for u in users] or [to_role]
    out = []
    for to in targets:
        n = Notification(run_id=run_id, channel=channel, to=to, subject=subject, body=body,
                         thread_ref=thread_ref, sent_at=clock.now())
        session.add(n)
        out.append(n)
    session.flush()
    audit.log(session, actor, "notification_sent", run_id,
              {"channel": channel, "to_role": to_role, "to": targets, "subject": subject})
    return out
