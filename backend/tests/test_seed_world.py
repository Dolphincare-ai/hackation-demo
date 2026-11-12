"""The fake world must contain exactly the planted cases from CLAUDE.md section 12."""
from datetime import date

from app.connectors import get_connectors
from app.schemas import Outgoing
from seed import INVOICE_LINES


def test_invoice_lines_add_up_to_total():
    assert all(round(q * p, 2) == a for _, q, p, a, _ in INVOICE_LINES)
    assert round(sum(line[3] for line in INVOICE_LINES), 2) == 4010.00


def test_contract_rates():
    v = get_connectors().vendors
    assert v.contract_rate("harbor", "atorvastatin_40", date(2026, 10, 15))["rate"] == 0.52
    assert v.contract_rate("harbor", "metformin_500", date(2026, 10, 15))["rate"] == 0.09
    assert v.contract_rate("harbor", "unknown_item", date(2026, 10, 15)) is None
    assert v.contract_rate("harbor", "metformin_500", date(2027, 2, 1)) is None  # outside validity


def test_deliveries_match_except_enoxaparin():
    v = get_connectors().vendors
    d = lambda k: sum(r["qty"] for r in v.deliveries("harbor", k, date(2026, 10, 1), date(2026, 10, 31)))
    assert d("metformin_500") == 900
    assert d("lisinopril_10") == 700
    assert d("atorvastatin_40") == 600
    assert v.deliveries("harbor", "enoxaparin_40", date(2026, 10, 1), date(2026, 10, 31)) == []


def test_resident_discharged_before_billing():
    r = get_connectors().ehr.find_by_name("Jose Alvarez")
    assert r["discharge_date"] == "2026-10-21"
    assert get_connectors().ehr.resident(r["resident_id"]) == r


def test_bank_balance_and_demo_helpers():
    bank = get_connectors().bank
    assert bank.available_balance("acct_riverside_op") == 12000.0
    bank.set_balance("acct_riverside_op", 6000)
    assert bank.available_balance("acct_riverside_op") == 6000
    bank.post_transaction("acct_riverside_op", "Harbor Pharmacy", -3410.0, "4471")
    assert bank.transactions(None)[-1]["reference"] == "4471"


def test_mailbox_template_poll_and_send(tmp_path):
    box = get_connectors().mailbox
    assert box.poll() == []
    box.drop_template("harbor_4471")
    mails = box.poll()
    assert len(mails) == 1 and "Invoice #4471" in mails[0].attachments[0].text
    assert box.poll() == []  # marked as seen
    box.send(Outgoing(to="billing@harborpharmacy.example", subject="Re: invoice", body="Paid", thread_ref=mails[0].thread_ref))
    assert len(list((box.root / "mailbox" / "sent").glob("*.json"))) == 1


def test_changed_bank_template_has_different_account():
    box = get_connectors().mailbox
    box.drop_template("harbor_changed_bank")
    text = box.poll()[0].attachments[0].text
    assert "account ending 7733" in text
    master = get_connectors().vendors.vendor_master("harbor")
    assert master["remit_to"]["account_last4"] == "4821"


def test_health_reports_mock_mode():
    c = get_connectors()
    c.bank.available_balance("acct_riverside_op")
    h = c.health()
    assert all(v["mode"] == "mock" for v in h.values())
    assert h["bank"]["last_read"] is not None
