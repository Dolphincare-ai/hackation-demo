"""The six automatic checks. Plain deterministic code: Claude never decides pass or fail."""
from sqlmodel import Session, select

from ....connectors import get_connectors
from ....core import settings
from ....models import Finding, Invoice, InvoiceLine, Run
from . import bank_details, date, delivery, duplicate, math, price
from .base import CHECK_NAMES, CheckContext, finding

CHECKS = {"price": price.check, "date": date.check, "delivery": delivery.check,
          "math": math.check, "duplicate": duplicate.check, "bank_details": bank_details.check}
assert set(CHECKS) == set(CHECK_NAMES)


def run_all(session: Session, run: Run, invoice: Invoice, ctx: CheckContext | None = None) -> list[Finding]:
    """Run every enabled check on every line and on the invoice. A disabled check yields one
    `skipped` finding, so the packet says "not checked" and never shows it as verified."""
    if ctx is None:
        conns = get_connectors()
        ctx = CheckContext(session=session, vendors=conns.vendors, ehr=conns.ehr)
    lines = session.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.id)).all()
    out: list[Finding] = []
    for name in CHECK_NAMES:
        value, source = settings.explain("invoice_audit", f"checks.{name}.enabled", run, invoice.vendor_id, default=True)
        if value is False:
            out.append(finding(invoice, None, name, "skipped", f"The {name.replace('_', ' ')} check was not run: "
                               f"turned off ({source}).", evidence={"enabled": False, "setting_source": source},
                               source=f"switched off by {source}"))
            continue
        fn = CHECKS[name]
        for line in lines:
            out += fn(invoice, line, ctx)
        out += fn(invoice, None, ctx)
    return out
