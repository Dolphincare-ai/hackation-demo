import threading

from fastapi import Header

from ..db import get_session
from ..models import User

_lock = threading.Lock()  # one writer at a time: the scheduler loop and API calls share SQLite


def session_dep():
    with _lock, get_session() as s:
        yield s


def acting_user(session, user_id: str | None, header: str | None) -> User | None:
    return session.get(User, user_id or header) if (user_id or header) else None


def x_user(x_user_id: str | None = Header(default=None)):
    return x_user_id


def run_tick(force_poll: bool = False) -> dict:
    from ..core import bot
    with _lock, get_session() as s:
        return bot.tick(s, force_poll=force_poll)
