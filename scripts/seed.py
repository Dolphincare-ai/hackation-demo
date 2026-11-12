"""Rebuild mock_world/ and reset data/platform.db. Run: python scripts/seed.py"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BUILDING = "riverside"
ACCOUNT = "acct_riverside_op"

VENDOR_MASTER = [{
    "vendor_id": "harbor", "name": "Harbor Pharmacy", "email_domain": "harborpharmacy.example",
    "remit_to": {"bank": "First Harbor Bank", "account_last4": "4821", "routing_last4": "0912"},
    "payment_terms_days": 30,
}]

# (item_key, description, unit, rate)
CONTRACT_ITEMS = [
    ("metformin_500", "Metformin 500 mg", "tablet", 0.09),
    ("lisinopril_10", "Lisinopril 10 mg", "tablet", 0.11),
    ("atorvastatin_40", "Atorvastatin 40 mg", "tablet", 0.52),
    ("apixaban_5", "Apixaban 5 mg", "tablet", 6.80),
    ("enoxaparin_40", "Enoxaparin 40 mg", "syringe", 24.50),
]
CONTRACTS = [
    {"vendor_id": "harbor", "item_key": k, "description": d, "unit": u, "rate": r,
     "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
    for k, d, u, r in CONTRACT_ITEMS
]

# Delivered quantities in October. Enoxaparin has NO record on purpose (delivery -> unverified).
DELIVERIES = [
    {"vendor_id": "harbor", "item_key": k, "date": day, "qty": q, "building_id": BUILDING}
    for k, parts in {
        "metformin_500": [("2026-10-05", 300), ("2026-10-12", 300), ("2026-10-19", 300)],
        "lisinopril_10": [("2026-10-06", 350), ("2026-10-20", 350)],
        "atorvastatin_40": [("2026-10-07", 300), ("2026-10-21", 300)],
        "apixaban_5": [("2026-10-08", 60)],
    }.items()
    for day, q in parts
]

CENSUS = [
    {"resident_id": "res_001", "name": "Jose Alvarez", "building_id": BUILDING, "room": "12", "admit_date": "2026-08-14", "discharge_date": "2026-10-21"},
    {"resident_id": "res_002", "name": "Margaret Chen", "building_id": BUILDING, "room": "14", "admit_date": "2026-03-02", "discharge_date": None},
    {"resident_id": "res_003", "name": "Walter Brooks", "building_id": BUILDING, "room": "21", "admit_date": "2026-06-19", "discharge_date": None},
    {"resident_id": "res_004", "name": "Ruth Okafor", "building_id": BUILDING, "room": "9", "admit_date": "2026-09-30", "discharge_date": None},
]

ACCOUNTS = [{"account_id": ACCOUNT, "name": "Riverside operating", "building_id": BUILDING, "balance": 12000.0}]
TRANSACTIONS = [
    {"txn_id": "t_0001", "account_id": ACCOUNT, "date": "2026-10-28", "payee": "Medline Supply", "amount": -1840.0, "reference": "MED-9921"},
    {"txn_id": "t_0002", "account_id": ACCOUNT, "date": "2026-11-03", "payee": "Medicare remittance", "amount": 21500.0, "reference": "CMS-1103"},
]

INVOICE_LINES = [
    ("Metformin 500 mg", 900, 0.09, 81.00, None),
    ("Lisinopril 10 mg", 700, 0.11, 77.00, None),
    ("Atorvastatin 40 mg", 600, 0.84, 504.00, None),
    ("Apixaban 5 mg - Jose Alvarez, 10/22 to 10/31", 60, 6.80, 408.00, "Jose Alvarez"),
    ("Enoxaparin 40 mg", 120, 24.50, 2940.00, None),
]


def invoice_text(invoice_no: str, account_last4: str) -> str:
    lines = "\n".join(
        f"  {d:<48} qty {q:>4} x ${p:>5.2f} = ${a:>8,.2f}" for d, q, p, a, _ in INVOICE_LINES
    )
    return (
        "HARBOR PHARMACY\n"
        f"Invoice #{invoice_no}\n"
        "Bill to: Riverside Care\n"
        "Invoice date: 2026-11-02\n"
        "Due date: 2026-12-02\n"
        "Service period: 2026-10-01 to 2026-10-31\n\n"
        f"{lines}\n\n"
        "Total due: $4,010.00\n\n"
        "Remit to: First Harbor Bank, account ending "
        f"{account_last4}, routing ending 0912\n"
    )


def email(email_id: str, invoice_no: str, account_last4: str, subject: str) -> dict:
    return {
        "id": email_id,
        "from": "billing@harborpharmacy.example",
        "to": "ap@riverside.example",
        "subject": subject,
        "received_at": "2026-11-02T09:00:00",
        "body": f"Hello,\n\nPlease find attached our October invoice #{invoice_no}.\n\nHarbor Pharmacy Billing",
        "thread_ref": f"thread-harbor-{invoice_no}",
        "attachments": [{"filename": f"invoice_{invoice_no}.txt", "text": invoice_text(invoice_no, account_last4)}],
    }


def build_mock_world(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    files = {
        "vendors/vendor_master.json": VENDOR_MASTER,
        "vendors/contracts.json": CONTRACTS,
        "vendors/deliveries.json": DELIVERIES,
        "ehr/census.json": CENSUS,
        "bank/accounts.json": ACCOUNTS,
        "bank/transactions.json": TRANSACTIONS,
        "mailbox/templates/harbor_4471.json": email("harbor_4471", "4471", "4821", "Harbor Pharmacy invoice #4471 (October)"),
        # Same lines, new invoice number, different remit-to account -> bank_details failure.
        "mailbox/templates/harbor_changed_bank.json": email("harbor_changed_bank", "4480", "7733", "Harbor Pharmacy invoice #4480 (updated bank details)"),
    }
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    for d in ("mailbox/inbox", "mailbox/sent"):
        (root / d).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    from app.config import mock_world_dir
    from app.core import clock
    from app.db import reset_db

    build_mock_world(mock_world_dir())
    reset_db()
    clock.reset()
    print(f"mock_world rebuilt at {mock_world_dir()} and database reset")
