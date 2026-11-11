import json

from .base import finding


def check(invoice, line, ctx):
    if line is not None:
        return []
    master = ctx.vendors.vendor_master(invoice.vendor_id)
    billed = json.loads(invoice.remit_to_json or "{}")
    ev = {"vendor_master": master, "invoice_remit_to": billed}
    if master is None:
        return [finding(invoice, None, "bank_details", "unverified", "No vendor master record to compare bank details with.",
                        evidence=ev, source="vendor master: none")]
    known = master.get("remit_to") or {}
    diff = [k for k in ("bank", "account_last4", "routing_last4") if str(known.get(k)) != str(billed.get(k))]
    if diff:
        return [finding(invoice, None, "bank_details", "failed",
                        "Remit-to details differ from the vendor master (" + ", ".join(d.replace("_", " ") for d in diff)
                        + "). Possible payment fraud: confirm with the vendor by phone.",
                        expected=f"{known.get('bank')} ...{known.get('account_last4')}",
                        actual=f"{billed.get('bank')} ...{billed.get('account_last4')}",
                        at_risk=invoice.total, evidence=ev, source="vendor master")]
    return [finding(invoice, None, "bank_details", "verified", "Remit-to matches the vendor master.",
                    expected=f"{known.get('bank')} ...{known.get('account_last4')}", evidence=ev, source="vendor master")]
