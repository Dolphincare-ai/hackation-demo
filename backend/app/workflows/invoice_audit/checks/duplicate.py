from sqlmodel import select

from ....models import Invoice, InvoiceLine
from .base import finding


def _key(l: InvoiceLine):
    return (l.description, l.item_key, l.resident_id, l.service_from, l.service_to, l.qty, l.unit_price)


def check(invoice, line, ctx):
    if line is not None:
        lines = ctx.session.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.id)).all()
        earlier = [l for l in lines if l.id < line.id and _key(l) == _key(line)]
        ev = {"same_as_line_ids": [l.id for l in earlier]}
        if earlier:
            return [finding(invoice, line, "duplicate", "failed", "The same line appears earlier on this invoice.",
                            at_risk=line.amount, evidence=ev, source="lines of this invoice")]
        return [finding(invoice, line, "duplicate", "verified", "Not repeated on this invoice.", evidence=ev,
                        source="lines of this invoice")]
    prior = ctx.session.exec(select(Invoice).where(
        Invoice.vendor_id == invoice.vendor_id, Invoice.invoice_no == invoice.invoice_no, Invoice.id < invoice.id)).all()
    ev = {"earlier_invoice_ids": [p.id for p in prior], "earlier_run_ids": [p.run_id for p in prior]}
    if prior:
        return [finding(invoice, None, "duplicate", "failed",
                        f"Invoice number {invoice.invoice_no} from this vendor was received before.",
                        at_risk=invoice.total, evidence=ev, source="earlier invoices")]
    return [finding(invoice, None, "duplicate", "verified", "Invoice number not seen before for this vendor.",
                    evidence=ev, source="earlier invoices")]
