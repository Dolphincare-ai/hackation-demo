from .base import TOL, finding, money


def check(invoice, line, ctx):
    if line is not None:
        calc = round(line.qty * line.unit_price, 2)
        ev = {"qty": line.qty, "unit_price": line.unit_price, "amount": line.amount, "computed": calc}
        if abs(calc - line.amount) > TOL:
            return [finding(invoice, line, "math", "failed",
                            f"{line.qty:g} x {money(line.unit_price)} is {money(calc)}, invoice says {money(line.amount)}.",
                            expected=calc, actual=line.amount, at_risk=abs(line.amount - calc), evidence=ev,
                            source="qty x unit price")]
        return [finding(invoice, line, "math", "verified", "Quantity times price equals the line amount.",
                        expected=calc, actual=line.amount, evidence=ev, source="qty x unit price")]
    # invoice level: lines must add up to the total
    from sqlmodel import select
    from ....models import InvoiceLine
    lines = ctx.session.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)).all()
    s = round(sum(l.amount for l in lines), 2)
    ev = {"line_amounts": [l.amount for l in lines], "sum": s, "total": invoice.total}
    if abs(s - invoice.total) > TOL:
        return [finding(invoice, None, "math", "failed",
                        f"Lines add up to {money(s)}, invoice total says {money(invoice.total)}.",
                        expected=s, actual=invoice.total, at_risk=abs(invoice.total - s), evidence=ev, source="sum of lines")]
    return [finding(invoice, None, "math", "verified", "Lines add up to the invoice total.",
                    expected=s, actual=invoice.total, evidence=ev, source="sum of lines")]
