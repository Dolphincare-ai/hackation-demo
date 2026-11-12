"""AI slot 2: extract the invoice from email text. Output is validated against InvoiceExtract.
Any failure raises, and slots.py retries via its regex reader, then the run goes to MANUAL_ENTRY."""
from ...ai.client import call_json
from ...connectors import get_connectors
from ...schemas import Email, InvoiceExtract


def extract_invoice(email: Email) -> InvoiceExtract:
    c = get_connectors()
    masters = c.vendors._load("vendors/vendor_master.json")
    payload = {
        "email": {"from": email.from_, "subject": email.subject, "body": email.body,
                  "attachments": [{"filename": a.filename, "text": a.text} for a in email.attachments]},
        "vendors": [{"vendor_id": v["vendor_id"], "name": v["name"], "email_domain": v["email_domain"]} for v in masters],
        "contract_keys": {v["vendor_id"]: c.vendors.contract_keys(v["vendor_id"]) for v in masters},
        "residents": [{"resident_id": r["resident_id"], "name": r["name"]} for r in c.ehr._load("ehr/census.json")],
    }
    out = call_json("extract", payload, InvoiceExtract)
    keys = set(payload["contract_keys"].get(out.vendor_id, []))
    for line in out.lines:  # the model may only choose known keys
        if line.item_key not in keys:
            line.item_key = None
    return out
