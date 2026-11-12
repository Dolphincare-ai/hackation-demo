from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.core import clock, tasks
from app.models import AuditLog, User


def test_clock_advance_and_freeze():
    clock.freeze(datetime(2026, 11, 10, 9, 0))
    assert clock.now() == datetime(2026, 11, 10, 9, 0)
    clock.advance(24)
    assert clock.now() == datetime(2026, 11, 11, 9, 0)


def test_users_seeded(session):
    roles = sorted(u.role for u in session.exec(select(User)))
    assert roles == ["administrator", "business_office_manager", "cfo", "don", "owner"]


@pytest.mark.parametrize("kind,role,hours", [
    ("manual_entry", "business_office_manager", 8),
    ("approval", "administrator", 24),
    ("funds_check", "cfo", 4),
])
def test_task_defaults_from_config(session, kind, role, hours):
    clock.freeze(datetime(2026, 11, 10, 9, 0))
    t = tasks.create_task(session, run_id=1, kind=kind, title="x")
    assert t.role == role
    assert t.due_at == datetime(2026, 11, 10, 9, 0) + timedelta(hours=hours)


def test_task_lateness_follows_clock(session):
    clock.freeze(datetime(2026, 11, 10, 9, 0))
    t = tasks.create_task(session, run_id=1, kind="approval", title="x")
    assert not tasks.is_late(t)
    clock.advance(25)
    assert tasks.is_late(t)


def test_complete_task_audits_and_cannot_repeat(session):
    t = tasks.create_task(session, run_id=1, kind="payment", title="x", role="business_office_manager", due_in_h=5)
    tasks.complete_task(session, t.id, by="system", source="system_observed")
    assert t.status == "done" and t.completion_source == "system_observed"
    actions = [a.action for a in session.exec(select(AuditLog))]
    assert actions == ["task_created", "task_completed"]
    with pytest.raises(ValueError):
        tasks.complete_task(session, t.id, by="system")


def test_unknown_kind_without_role_is_an_error(session):
    with pytest.raises(ValueError):
        tasks.create_task(session, run_id=1, kind="mystery", title="x")
