from .base import finding, money


def check(invoice, line, ctx):
    if line is None:
        return []
    if not line.item_key:
        return [finding(invoice, line, "delivery", "unverified", "The item could not be matched, so deliveries cannot be looked up.",
                        evidence={"item_key": None}, source="no item")]
    rows = ctx.vendors.deliveries(invoice.vendor_id, line.item_key, invoice.period_from, invoice.period_to)
    ev = {"deliveries": rows, "period": [invoice.period_from, invoice.period_to], "billed_qty": line.qty}
    if not rows:
        return [finding(invoice, line, "delivery", "unverified", "No delivery record found for this item in the period.",
                        evidence=ev, source="deliveries: none found")]
    delivered = sum(float(r["qty"]) for r in rows)
    src = f"{len(rows)} delivery record(s), {delivered:g} delivered"
    if line.qty > delivered + 1e-9:
        return [finding(invoice, line, "delivery", "failed",
                        f"Billed {line.qty:g} but only {delivered:g} were delivered.",
                        expected=delivered, actual=line.qty, at_risk=(line.qty - delivered) * line.unit_price,
                        evidence=ev, source=src)]
    return [finding(invoice, line, "delivery", "verified", f"Billed {line.qty:g}, delivered {delivered:g}.",
                    expected=delivered, actual=line.qty, evidence=ev, source=src)]
