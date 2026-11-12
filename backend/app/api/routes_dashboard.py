import sys
from collections import Counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from ..config import ROOT, get_config, mock_world_dir
from ..connectors import get_connectors
from ..core import clock, tasks as task_engine
from ..models import Payment, Run, Task
from ..workflows.invoice_audit import packet as packet_mod
from ..workflows.invoice_audit import state
from .deps import run_tick, session_dep

router = APIRouter()


@router.get("/connectors/health")
def connectors_health():
    return get_connectors().health()


@router.get("/dashboard")
def dashboard(session=Depends(session_dep)):
    runs = session.exec(select(Run)).all()
    at_risk = verified = 0.0
    for r in runs:
        inv = state.invoice_of(session, r)
        if inv and r.closed_at is None:
            t = packet_mod.build(session, inv)["totals"]
            at_risk += t["at_risk"]
            verified += t["verified"]
    open_tasks = session.exec(select(Task).where(Task.status == "open")).all()
    paid = sum(p.amount for p in session.exec(select(Payment).where(Payment.status == "matched")))
    return {"invoices_by_state": dict(Counter(r.state for r in runs)), "dollars_at_risk": round(at_risk, 2),
            "dollars_verified": round(verified, 2), "dollars_paid": round(paid, 2),
            "late_tasks": sum(task_engine.is_late(t) for t in open_tasks),
            "open_tasks_by_role": dict(Counter(t.role for t in open_tasks))}


# ---- demo controls ----
class EmailBody(BaseModel):
    template: str


class BankPost(BaseModel):
    account_id: str
    payee: str
    amount: float
    reference: str


class BalanceBody(BaseModel):
    account_id: str
    balance: float


class AdvanceBody(BaseModel):
    hours: float


@router.post("/mock/email")
def mock_email(body: EmailBody):
    eid = get_connectors().mailbox.drop_template(body.template)
    return {"email_id": eid, **run_tick(force_poll=True)}  # read the inbox right away (it is a demo)


@router.post("/mock/bank/post")
def mock_bank_post(body: BankPost):
    txn = get_connectors().bank.post_transaction(body.account_id, body.payee, body.amount, body.reference)
    return {"txn": txn, **run_tick()}


@router.post("/mock/bank/balance")
def mock_bank_balance(body: BalanceBody):
    get_connectors().bank.set_balance(body.account_id, body.balance)
    return {"ok": True, **run_tick()}


@router.post("/mock/advance")
def mock_advance(body: AdvanceBody):
    now = clock.advance(body.hours)
    return {"now": now.isoformat(), **run_tick()}


@router.post("/mock/tick")
def mock_tick():
    return run_tick()


@router.post("/mock/inbox/check")
def mock_inbox_check():
    """The demo bar's 'Check inbox' button: read the mailbox now, whatever the poll schedule says."""
    return run_tick(force_poll=True)


@router.post("/mock/reset")
def mock_reset():
    """Reset runs, tasks, the mock world and the clock. The live playbook (data/playbooks) is left alone."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from seed import build_mock_world
    from ..db import reset_db
    from .deps import _lock
    with _lock:
        build_mock_world(mock_world_dir())
        reset_db()
        clock.reset()
        mb = get_connectors().mailbox
        if hasattr(mb, "forget_seen"):  # real inbox: unread mail is picked up again after a reset
            mb.forget_seen()
    return {"ok": True}
