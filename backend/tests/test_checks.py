"""Table-driven tests for the six checks (CLAUDE.md section 8)."""
import json
from datetime import date

import pytest

from app.connectors import get_connectors
from app.models import Invoice, InvoiceLine, Run
from app.workflows.invoice_audit import checks
from app.workflows.invoice_audit.checks.base import CheckContext

GOOD_REMIT = {"bank": "First Harbor Bank", "account_last4": "4821", "routing_last4": "0912"}


def make(session, lines, *, invoice_no="9001", total=None, remit=GOOD_REMIT, vendor="harbor"):
    from datetime import datetime
    run = Run(type="invoice_audit", state="EXTRACTED", building_id="riverside", title="t",
              created_at=datetime(2026, 11, 11), updated_at=datetime(2026, 11, 11), context_json=json.dumps({"vendor_id": vendor}))
    session.add(run)
    session.flush()
    inv = Invoice(run_id=run.id, vendor_id=vendor, invoice_no=invoice_no, invoice_date=date(2026, 11, 2),
                  due_date=date(2026, 12, 2), period_from=date(2026, 10, 1), period_to=date(2026, 10, 31),
                  total=total if total is not None else sum(l["amount"] for l in lines), remit_to_json=json.dumps(remit))
    session.add(inv)
    session.flush()
    rows = []
    for l in lines:
        row = InvoiceLine(invoice_id=inv.id, **{"description": "x", "item_key": None, "resident_id": None,
                          "service_from": date(2026, 10, 1), "service_to": date(2026, 10, 31), **l})
        session.add(row)
        rows.append(row)
    session.flush()
    return run, inv, rows


def ctx(session):
    c = get_connectors()
    return CheckContext(session=session, vendors=c.vendors, ehr=c.ehr)


def line(item="metformin_500", qty=900, price=0.09, **kw):
    return {"item_key": item, "qty": qty, "unit_price": price, "amount": round(qty * price, 2), **kw}


# (name, check, line kwargs, expected status, expected at risk)
LINE_CASES = [
    ("price ok", "price", line(), "verified", 0),
    ("price above contract", "price", line("atorvastatin_40", 600, 0.84), "failed", 192.0),
    ("price below contract is fine", "price", line("atorvastatin_40", 600, 0.40), "verified", 0),
    ("price no item key", "price", line(None), "unverified", 0),
    ("price no contract on date", "price", line(service_from=date(2027, 1, 5), service_to=date(2027, 1, 6)), "unverified", 0),
    ("delivery ok", "delivery", line(), "verified", 0),
    ("delivery none found", "delivery", line("enoxaparin_40", 120, 24.5), "unverified", 0),
    ("delivery over", "delivery", line("metformin_500", 1000, 0.09), "failed", 9.0),
    ("delivery no item", "delivery", line(None), "unverified", 0),
    ("math ok", "math", line(), "verified", 0),
    ("math line wrong", "math", {**line(), "amount": 90.0}, "failed", 9.0),
    ("date ok", "date", line(), "verified", 0),
    ("date resident ok", "date", line("apixaban_5", 60, 6.8, resident_id="res_002"), "verified", 0),
    ("date after discharge", "date", line("apixaban_5", 60, 6.8, resident_id="res_001",
                                          service_from=date(2026, 10, 22), service_to=date(2026, 10, 31)), "failed", 408.0),
    ("date partly after discharge", "date", line("apixaban_5", 60, 6.8, resident_id="res_001",
                                                 service_from=date(2026, 10, 17), service_to=date(2026, 10, 26)), "failed", 204.0),
    ("date before admission", "date", line("apixaban_5", 60, 6.8, resident_id="res_004",
                                           service_from=date(2026, 9, 25), service_to=date(2026, 10, 4)), "failed", None),
    ("date unknown resident", "date", line("apixaban_5", 60, 6.8, resident_id="res_999"), "unverified", 0),
    ("date outside period", "date", line(service_from=date(2026, 10, 25), service_to=date(2026, 11, 4)), "failed", None),
    ("date outside contract", "date", line(service_from=date(2026, 12, 20), service_to=date(2027, 1, 5)), "failed", None),
]


@pytest.mark.parametrize("name,check,lk,status,risk", LINE_CASES, ids=[c[0] for c in LINE_CASES])
def test_line_checks(session, name, check, lk, status, risk):
    _, inv, rows = make(session, [lk])
    out = checks.CHECKS[check](inv, rows[0], ctx(session))
    assert len(out) == 1
    f = out[0]
    assert f.status == status, f.message
    if risk is not None:
        assert f.amount_at_risk == pytest.approx(risk)
    ev = json.loads(f.evidence_json)
    assert ev["source"]  # every finding says what it compared against


def test_evidence_holds_what_was_compared(session):
    _, inv, rows = make(session, [line("atorvastatin_40", 600, 0.84)])
    ev = json.loads(checks.CHECKS["price"](inv, rows[0], ctx(session))[0].evidence_json)
    assert ev["contract"]["rate"] == 0.52 and ev["billed_unit_price"] == 0.84
    _, inv, rows = make(session, [line("metformin_500")], invoice_no="9002")
    ev = json.loads(checks.CHECKS["delivery"](inv, rows[0], ctx(session))[0].evidence_json)
    assert len(ev["deliveries"]) == 3


INVOICE_CASES = [
    ("math total ok", "math", {"lines": [line()]}, "verified"),
    ("math total wrong", "math", {"lines": [line()], "total": 100.0}, "failed"),
    ("bank ok", "bank_details", {"lines": [line()]}, "verified"),
    ("bank changed", "bank_details", {"lines": [line()], "remit": {**GOOD_REMIT, "account_last4": "7733"}}, "failed"),
    ("bank no master", "bank_details", {"lines": [line()], "vendor": "unknown_vendor"}, "unverified"),
    ("duplicate ok", "duplicate", {"lines": [line()]}, "verified"),
]


@pytest.mark.parametrize("name,check,kw,status", INVOICE_CASES, ids=[c[0] for c in INVOICE_CASES])
def test_invoice_level_checks(session, name, check, kw, status):
    _, inv, _ = make(session, **kw)
    out = checks.CHECKS[check](inv, None, ctx(session))
    assert [f.status for f in out] == [status]
    assert out[0].line_id is None


def test_duplicate_line_within_invoice(session):
    _, inv, rows = make(session, [line(), line()])
    assert checks.CHECKS["duplicate"](inv, rows[0], ctx(session))[0].status == "verified"
    second = checks.CHECKS["duplicate"](inv, rows[1], ctx(session))[0]
    assert second.status == "failed" and second.amount_at_risk == rows[1].amount


def test_duplicate_invoice_number_same_vendor(session):
    make(session, [line()], invoice_no="5555")
    _, again, _ = make(session, [line()], invoice_no="5555")
    assert checks.CHECKS["duplicate"](again, None, ctx(session))[0].status == "failed"
    _, other_vendor, _ = make(session, [line()], invoice_no="5555", vendor="other")
    assert checks.CHECKS["duplicate"](other_vendor, None, ctx(session))[0].status == "verified"


def test_disabled_check_is_skipped_never_verified(session):
    run, inv, _ = make(session, [line()])
    run.context_json = json.dumps({"vendor_id": "harbor", "overrides": {"checks": {"delivery": {"enabled": False}}}})
    found = checks.run_all(session, run, inv)
    delivery = [f for f in found if f.check == "delivery"]
    assert [f.status for f in delivery] == ["skipped"]
    assert "this run only" in delivery[0].message
    assert all(f.status == "verified" for f in found if f.check == "price")
