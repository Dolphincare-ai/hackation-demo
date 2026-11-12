"""Small helpers shared by the invoice-audit modules: run context, state changes, lookups."""
import json
from datetime import datetime

from sqlmodel import Session, select

from ...core import audit, clock
from ...models import Finding, Invoice, InvoiceLine, Payment, Run, Task

RUN_TYPE = "invoice_audit"
CLOSING = {"CLOSED", "REJECTED"}


def ctx(run: Run) -> dict:
    return json.loads(run.context_json or "{}")


def set_ctx(run: Run, **values) -> None:
    c = ctx(run)
    c.update(values)
    run.context_json = json.dumps(c, default=str)


def transition(session: Session, run: Run, new_state: str, **detail) -> None:
    old = run.state
    run.state = new_state
    run.updated_at = clock.now()
    if new_state in CLOSING:
        run.closed_at = clock.now()
    session.add(run)
    inv = invoice_of(session, run)
    if inv is not None:
        inv.status = new_state.lower()
        session.add(inv)
    audit.log(session, "system", "state_changed", run.id, {"from": old, "to": new_state, **detail})


def invoice_of(session: Session, run: Run) -> Invoice | None:
    return session.exec(select(Invoice).where(Invoice.run_id == run.id)).first()


def lines_of(session: Session, invoice: Invoice) -> list[InvoiceLine]:
    return list(session.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.id)))


def findings_of(session: Session, invoice: Invoice) -> list[Finding]:
    return list(session.exec(select(Finding).where(Finding.invoice_id == invoice.id).order_by(Finding.id)))


def payment_of(session: Session, invoice: Invoice) -> Payment | None:
    return session.exec(select(Payment).where(Payment.invoice_id == invoice.id)).first()


def open_tasks(session: Session, run: Run, *kinds: str) -> list[Task]:
    q = select(Task).where(Task.run_id == run.id, Task.status == "open")
    return [t for t in session.exec(q) if not kinds or t.kind in kinds]


def eff(run: Run, key: str, vendor_id: str | None = None, default=None):
    from ...core import settings
    return settings.effective(RUN_TYPE, key, run, vendor_id, default)


def task_due_h(run: Run, kind: str, vendor_id: str | None = None) -> float:
    return float(eff(run, f"task_defaults.{kind}.due_h", vendor_id))


def task_role(run: Run, kind: str, vendor_id: str | None = None) -> str:
    return eff(run, f"task_defaults.{kind}.role", vendor_id)


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)
