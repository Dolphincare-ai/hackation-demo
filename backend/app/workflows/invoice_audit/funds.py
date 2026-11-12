"""Funds check: balance minus payable must stay at or above the reserve. Retried on every tick."""
import json
from datetime import datetime, time, timedelta

from sqlmodel import Session

from ...config import get_config
from ...connectors import get_connectors
from ...core import audit, tasks
from ...models import Invoice, Payment, Run
from . import state


def account_for(run: Run) -> str:
    return get_config()["bank_accounts"][run.building_id]


def attempt(session: Session, run: Run, invoice: Invoice) -> bool:
    """Returns True if the state changed. A failed retry changes nothing (so ticks stay idempotent)."""
    account = account_for(run)
    balance = get_connectors().bank.available_balance(account)
    reserve = float(state.eff(run, "reserve_min", invoice.vendor_id))
    payable = invoice.payable_amount or 0.0
    enough = balance is not None and balance - payable >= reserve
    facts = {"balance": balance, "payable": payable, "reserve": reserve, "account": account}
    if enough:
        for t in state.open_tasks(session, run, "funds_check"):
            tasks.complete_task(session, t.id, by="system", source="system_observed", note="Funds are now available")
        _create_payment(session, run, invoice, account)
        audit.log(session, "system", "funds_ok", run.id, facts)
        state.transition(session, run, "AWAITING_PAYMENT")
        return True
    if run.state == "FUNDS_CHECK":
        short = payable + reserve - (balance or 0.0)
        tasks.create_task(
            session, run_id=run.id, kind="funds_check", role=state.task_role(run, "funds_check", invoice.vendor_id),
            due_in_h=state.task_due_h(run, "funds_check", invoice.vendor_id), via="text",
            title=f"Add ${short:,.2f} to the operating account to pay invoice #{invoice.invoice_no}",
            payload=facts, blocks=[{"type": "kv", "items": [
                ["Balance", f"${(balance or 0):,.2f}"], ["To pay", f"${payable:,.2f}"],
                ["Reserve to keep", f"${reserve:,.2f}"], ["Short by", f"${short:,.2f}"]]}])
        audit.log(session, "system", "funds_insufficient", run.id, facts)
        state.transition(session, run, "FUNDS_INSUFFICIENT")
        return True
    return False


def _create_payment(session: Session, run: Run, invoice: Invoice, account: str) -> None:
    vendor = get_connectors().vendors.vendor_master(invoice.vendor_id) or {}
    name = vendor.get("name", invoice.vendor_id)
    ref = f"INV-{invoice.invoice_no}"
    days_before = int(state.eff(run, "payment_due_days_before", default=2))
    due_at = datetime.combine(invoice.due_date, time(17, 0)) - timedelta(days=days_before)
    session.add(Payment(invoice_id=invoice.id, amount=invoice.payable_amount, account_id=account, expected_ref=ref))
    remit = json.loads(invoice.remit_to_json or "{}")
    tasks.create_task(
        session, run_id=run.id, kind="payment", role=state.task_role(run, "payment", invoice.vendor_id), due_at=due_at,
        via="teams", title=f"Pay {name} ${invoice.payable_amount:,.2f} for invoice #{invoice.invoice_no}",
        payload={"amount": invoice.payable_amount, "payee": name, "reference": ref, "account_id": account,
                 "pay_to": remit, "due": due_at.isoformat()},
        blocks=[{"type": "kv", "items": [
            ["Pay", f"${invoice.payable_amount:,.2f}"], ["To", f"{name} ({remit.get('bank')} ...{remit.get('account_last4')})"],
            ["Reference", ref], ["Pay by", f"{due_at:%b %d}"]]},
            {"type": "text", "text": "Make this payment in your own bank. The platform never moves money; "
                                     "this step closes by itself when the payment shows on the bank feed."}])
