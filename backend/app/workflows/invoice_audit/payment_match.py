"""Match bank transactions to pending payments. Read-only: the platform only observes the feed."""
from sqlmodel import Session, select

from ...connectors import get_connectors
from ...core import audit, clock, notify, tasks
from ...models import Notification, Payment, Run
from ...schemas import Email, Outgoing
from . import slots, state


def find_match(payment: Payment, vendor_name: str, txns: list[dict]) -> tuple[str, dict | None]:
    """('matched'|'mismatch'|'none', txn). Amounts compare as absolute values (outflows are negative)."""
    ref = payment.expected_ref.lower()
    candidates = [t for t in txns if t["account_id"] == payment.account_id and (
        ref in str(t.get("reference", "")).lower() or vendor_name.lower() in str(t.get("payee", "")).lower())]
    for t in candidates:
        if abs(abs(t["amount"]) - payment.amount) < 0.005:
            return "matched", t
    return ("mismatch", candidates[-1]) if candidates else ("none", None)


def observe(session: Session) -> None:
    runs = session.exec(select(Run).where(Run.type == state.RUN_TYPE, Run.state == "AWAITING_PAYMENT")).all()
    if not runs:
        return
    conns = get_connectors()
    txns = conns.bank.transactions()
    for run in runs:
        inv = state.invoice_of(session, run)
        pay = state.payment_of(session, inv)
        if pay is None or pay.status == "matched":
            continue
        vendor = (conns.vendors.vendor_master(inv.vendor_id) or {}).get("name", inv.vendor_id)
        result, txn = find_match(pay, vendor, txns)
        if result == "matched":
            pay.status, pay.matched_txn_id, pay.matched_at = "matched", txn["txn_id"], clock.now()
            session.add(pay)
            for t in state.open_tasks(session, run, "payment"):
                tasks.complete_task(session, t.id, by="system", source="system_observed",
                                    note=f"Seen on the bank feed as {txn['txn_id']}")
            audit.log(session, "system", "payment_matched", run.id, {"txn": txn, "expected": pay.amount})
            state.transition(session, run, "PAID")
            finish(session, run)
        elif result == "mismatch" and (pay.status, pay.matched_txn_id) != ("mismatch", txn["txn_id"]):
            pay.status, pay.matched_txn_id = "mismatch", txn["txn_id"]
            session.add(pay)
            audit.log(session, "system", "payment_mismatch", run.id, {"txn": txn, "expected": pay.amount})
            notify.send(session, run_id=run.id, channel="teams", to_role="business_office_manager",
                        subject=f"Payment amount does not match: {run.title}",
                        body=f"The bank shows ${abs(txn['amount']):,.2f} ({txn['txn_id']}) but ${pay.amount:,.2f} was expected.")


def finish(session: Session, run: Run) -> None:
    """PAID -> reply on the original thread -> CLOSED."""
    from .approval import line_payable
    inv = state.invoice_of(session, run)
    pay = state.payment_of(session, inv)
    email = Email.model_validate(state.ctx(run)["email"])
    disputed = [{"description": l.description, "billed": l.amount, "payable": line_payable(inv, l),
                 "reason": "Billed above the contract rate or not supported by our records."}
                for l in state.lines_of(session, inv)
                if l.decision in ("exclude", "approve_at_contract") and line_payable(inv, l) < l.amount]
    body, via = slots.draft_reply({"amount": pay.amount, "expected_ref": pay.expected_ref},
                                  {"invoice_no": inv.invoice_no, "total": inv.total},
                                  {"thread_ref": email.thread_ref, "subject": email.subject}, disputed)
    audit.log(session, "claude" if via == "ai" else "system", "reply_drafted", run.id, {"via": via})
    subject = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"
    get_connectors().mailbox.send(Outgoing(to=email.from_, subject=subject, body=body, thread_ref=email.thread_ref))
    session.add(Notification(run_id=run.id, channel="email", to=email.from_, subject=subject, body=body,
                             thread_ref=email.thread_ref, sent_at=clock.now()))
    audit.log(session, "system", "reply_sent", run.id, {"to": email.from_, "thread_ref": email.thread_ref})
    state.transition(session, run, "CLOSED")
