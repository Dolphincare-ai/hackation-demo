from .base import TOL, finding, money


def check(invoice, line, ctx):
    if line is None:
        return []
    if not line.item_key:
        return [finding(invoice, line, "price", "unverified", "The item could not be matched to a contract item.",
                        evidence={"item_key": None}, source="no contract item")]
    contract = ctx.vendors.contract_rate(invoice.vendor_id, line.item_key, line.service_from)
    if contract is None:
        return [finding(invoice, line, "price", "unverified",
                        f"No contract rate found for {line.item_key} on {line.service_from}.",
                        evidence={"item_key": line.item_key, "on_date": line.service_from}, source="no contract")]
    rate = float(contract["rate"])
    ev = {"contract": contract, "billed_unit_price": line.unit_price, "qty": line.qty}
    src = f"contract {invoice.vendor_id} {line.item_key} rate {rate:.2f}"
    if line.unit_price > rate + TOL:
        risk = (line.unit_price - rate) * line.qty
        return [finding(invoice, line, "price", "failed",
                        f"Billed {money(line.unit_price)} each, contract rate is {money(rate)}.",
                        expected=rate, actual=line.unit_price, at_risk=risk, evidence=ev, source=src)]
    return [finding(invoice, line, "price", "verified", f"Billed {money(line.unit_price)} each, matches contract.",
                    expected=rate, actual=line.unit_price, evidence=ev, source=src)]
