"""Workflow registry. A new scenario registers a handler here; the bot loop never changes.

A handler is an object with:
  run_type: str
  on_email(session, email) -> bool      # claim an email and start a run (True if claimed)
  advance(session, run) -> None         # idempotent: move one open run forward if it can
  observe(session) -> None              # watch outside systems (e.g. bank feed) for all runs
"""
from typing import Protocol

from sqlmodel import Session

from ..models import Run


class Handler(Protocol):
    run_type: str

    def on_email(self, session: Session, email) -> bool: ...
    def advance(self, session: Session, run: Run) -> None: ...
    def observe(self, session: Session) -> None: ...


_handlers: dict[str, Handler] = {}


def register(handler: Handler) -> None:
    _handlers[handler.run_type] = handler


def get(run_type: str) -> Handler | None:
    return _handlers.get(run_type)


def all_handlers() -> list[Handler]:
    return list(_handlers.values())


def _register_builtin() -> None:
    from .invoice_audit.flow import handler as invoice_audit

    register(invoice_audit)


_register_builtin()
