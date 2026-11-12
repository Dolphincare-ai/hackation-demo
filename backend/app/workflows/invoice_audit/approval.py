"""Approval: a person decides, line by line. The bot never approves (CLAUDE.md principle 5)."""
import json

from sqlmodel import Session

from ...connectors import get_connectors
from ...core import audit, clock, notify, permissions, tasks
from ...models import Approval, Invoice, InvoiceLine, Run, User
from . import packet, state

DECISIONS = ("approve", "approve_at_contract", "exclude")
BAD = {"failed", "manually_rejected"}


def contract_rate(invoice: Invoice, line: InvoiceLine) -> float | None:
    if not line.item_key:
        return None
    c = get_connectors().vendors.contract_rate(invoice.vendor_id, line.item_key, line.service_from)
    return float(c["rate"]) if c else None


def line_payable(invoice: Invoice, line: InvoiceLine) -> float:
    if line.decision == "approve":
        return line.amount
    if line.decision == "approve_at_contract":
        rate = contract_rate(invoice, line)
        return round(line.qty * rate, 2) if rate is not None else 0.0
    return 0.0


def payable_amount(invoice: Invoice, lines: list[InvoiceLine]) -> float:
    return round(sum(line_payable(invoice, l) for l in lines), 2)


def decide(session: Session, run: Run, user: User | None, decision: str, reason: str | None,
           line_decisions: list[dict]) -> None:
    if run.state != "PENDING_APPROVAL":
        raise ValueError(f"This invoice is {run.state.replace('_', ' ').lower()}, not waiting for approval")
    task = next(iter(state.open_tasks(session, run, "approval")), None)
    if task is None:
        raise ValueError("There is no open approval step")
    permissions.require_task(user, task)
    invoice = state.invoice_of(session, run)
    lines = {l.id: l for l in state.lines_of(session, invoice)}
    findings = state.findings_of(session, invoice)
    reason = (reason or "").strip()
    snapshot = {"packet": packet.build(session, invoice, state.ctx(run).get("packet_summary", "")),
                "findings": [f.model_dump() for f in findings]}

    if decision == "reject":
        if not reason:
            raise ValueError("Please type a reason for rejecting")
        _record(session, run, task, user, "reject", reason, snapshot)
        state.transition(session, run, "REJECTED", reason=reason)
        notify.send(session, run_id=run.id, channel="email", to_role="business_office_manager",
                    subject=f"Rejected: {run.title}", body=f"{user.name} rejected this invoice. Reason: {reason}")
        return
    if decision != "approve":
        raise ValueError("Decision must be approve or reject")

    chosen = {}
    for d in line_decisions:
        if d.get("line_id") not in lines or d.get("decision") not in DECISIONS:
            raise ValueError(f"Bad line decision: {d}")
        chosen[d["line_id"]] = d["decision"]
    missing = [l.description for i, l in lines.items() if i not in chosen]
    if missing:
        raise ValueError("Please decide every line. Missing: " + ", ".join(missing))

    for i, dec in chosen.items():
        line_bad = [f for f in findings if f.line_id == i and f.status in BAD]
        if dec == "approve" and line_bad and not reason:
            raise ValueError(f"'{lines[i].description}' has a failed check. Type a reason to approve it as billed, "
                             "approve it at the contract rate, or exclude it")
        if dec == "approve_at_contract":
            if contract_rate(invoice, lines[i]) is None:
                raise ValueError(f"'{lines[i].description}' has no contract rate to pay at")
            if any(f.check != "price" for f in line_bad) and not reason:
                raise ValueError(f"'{lines[i].description}' has failed checks besides price. Type a reason or exclude it")
    invoice_bad = [f for f in findings if f.line_id is None and f.status in BAD]
    if invoice_bad and any(d != "exclude" for d in chosen.values()) and not reason:
        raise ValueError("The invoice itself has a failed check (" + ", ".join(f.check.replace("_", " ") for f in invoice_bad)
                         + "). Type a reason to approve anyway")

    for i, dec in chosen.items():
        lines[i].decision = dec
    payable = payable_amount(invoice, list(lines.values()))
    if payable <= 0:
        session.rollback()
        raise ValueError("Nothing is left to pay. Reject the invoice instead")
    for l in lines.values():
        session.add(l)
    invoice.payable_amount = payable
    session.add(invoice)
    snapshot["payable_amount"] = payable
    snapshot["decisions"] = [{"line_id": i, "decision": d} for i, d in chosen.items()]
    _record(session, run, task, user, "approve", reason or None, snapshot)
    state.transition(session, run, "FUNDS_CHECK", payable_amount=payable)


def _record(session, run, task, user, decision, reason, snapshot):
    session.add(Approval(run_id=run.id, task_id=task.id, decision=decision, decided_by=user.id, decided_at=clock.now(),
                         reason=reason, snapshot_json=json.dumps(snapshot, default=str)))
    tasks.complete_task(session, task.id, by=user.id, source="user", note=reason)
    audit.log(session, user.id, "approval_decided", run.id, {"decision": decision, "reason": reason,
                                                            "payable": snapshot.get("payable_amount")})
