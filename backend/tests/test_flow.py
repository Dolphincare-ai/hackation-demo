"""State machine, API and end-to-end tests. Driven through the HTTP API, with the clock frozen."""
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, select

from app.core import clock, playbook, settings
from app.db import get_session

ADMIN, BOM, DON, CFO, OWNER = "u_admin_rc", "u_bom_rc", "u_don_rc", "u_cfo", "u_owner"
START = datetime(2026, 11, 11, 9, 0)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    clock.freeze(START)
    from app.main import app
    return TestClient(app)


def sent_dir():
    from app.config import mock_world_dir
    return mock_world_dir() / "mailbox" / "sent"


def run_state(c, rid=1):
    return c.get(f"/runs/{rid}").json()["run"]["state"]


def open_task(c, kind, rid=1):
    return next((t for t in c.get(f"/runs/{rid}").json()["tasks"] if t["kind"] == kind and t["status"] == "open"), None)


def decisions(c, rid=1, exclude=("Apixaban",), at_contract=("Atorvastatin",)):
    out = []
    for l in c.get(f"/runs/{rid}").json()["invoice"]["lines"]:
        d = "approve"
        if any(x in l["description"] for x in exclude):
            d = "exclude"
        if any(x in l["description"] for x in at_contract):
            d = "approve_at_contract"
        out.append({"line_id": l["id"], "decision": d})
    return out


def start(c, template="harbor_4471"):
    r = c.post("/mock/email", json={"template": template})
    assert r.status_code == 200, r.text
    return r.json()


def to_approval(c):
    start(c)
    t = open_task(c, "manual_check")
    assert c.post(f"/tasks/{t['id']}/resolve", json={"user_id": DON, "response": "verified", "note": "Seen on the dock log"}).status_code == 200
    assert run_state(c) == "PENDING_APPROVAL"


def approve(c, user=ADMIN, **kw):
    return c.post("/runs/1/approval", json={"user_id": user, "decision": "approve", "reason": kw.pop("reason", ""),
                                            "lines": decisions(c, **kw)})


def pay(c, amount=-3410.0, ref="INV-4471"):
    return c.post("/mock/bank/post", json={"account_id": "acct_riverside_op", "payee": "Harbor Pharmacy",
                                           "amount": amount, "reference": ref})


# ---- the seed scenario ----
def test_seed_findings_and_manual_check(client):
    start(client)
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "NEEDS_INFO" and d["run"]["context"]["vendor_name"] == "Harbor Pharmacy"
    bad = {(f["check"], f["status"], f["amount_at_risk"]) for f in d["findings"] if f["status"] != "verified"}
    assert bad == {("price", "failed", 192.0), ("date", "failed", 408.0), ("delivery", "unverified", 0.0)}
    tasks = [t for t in d["tasks"] if t["kind"] == "manual_check"]
    assert len(tasks) == 1 and tasks[0]["role"] == "don"
    assert d["packet"]["totals"] == {"billed": 4010.0, "verified": 158.0, "at_risk": 600.0}


def test_manual_check_loop(client):
    start(client)
    t = open_task(client, "manual_check")
    assert client.post(f"/tasks/{t['id']}/resolve", json={"user_id": BOM, "response": "verified"}).status_code == 403
    assert client.post(f"/tasks/{t['id']}/resolve", json={"user_id": DON, "response": "dispute"}).status_code == 400  # note needed
    assert run_state(client) == "NEEDS_INFO"
    assert client.post(f"/tasks/{t['id']}/resolve", json={"user_id": DON, "response": "verified", "note": "ok"}).status_code == 200
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "PENDING_APPROVAL"
    assert open_task(client, "approval")["role"] == "administrator"
    assert d["packet"]["manually_verified"][0]["by"] == DON
    assert d["packet"]["unverified"] == []


def test_not_verified_check_still_reaches_approval_as_failed(client):
    start(client)
    t = open_task(client, "manual_check")
    client.post(f"/tasks/{t['id']}/resolve", json={"user_id": DON, "response": "not_verified", "note": "no delivery"})
    p = client.get("/runs/1").json()["packet"]
    assert any(f["check"] == "delivery" and f["manually_rejected"] and f["amount_at_risk"] == 2940.0 for f in p["failed"])


def test_happy_path_end_to_end_closed_with_reply(client):
    to_approval(client)
    r = approve(client)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["run"]["state"] == "AWAITING_PAYMENT"
    assert d["invoice"]["payable_amount"] == 3410.0
    assert d["approval"]["snapshot"]["payable_amount"] == 3410.0
    pt = open_task(client, "payment")
    assert pt["role"] == "business_office_manager" and pt["payload"]["amount"] == 3410.0
    assert pt["payload"]["reference"] == "INV-4471" and d["payment"]["status"] == "pending"
    assert pay(client).status_code == 200
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "CLOSED" and d["run"]["closed_at"]
    paid_task = next(t for t in d["tasks"] if t["kind"] == "payment")
    assert paid_task["status"] == "done" and paid_task["completion_source"] == "system_observed"
    assert d["payment"]["status"] == "matched"
    replies = [json.loads(p.read_text()) for p in sent_dir().glob("*.json")]
    assert len(replies) == 1
    assert replies[0]["thread_ref"] == "thread-harbor-4471" and replies[0]["to"] == "billing@harborpharmacy.example"
    assert "3,410.00" in replies[0]["body"] and "Apixaban" in replies[0]["body"]  # disputed lines are noted
    actions = [e["action"] for e in d["timeline"]]
    assert "approval_decided" in actions and "reply_sent" in actions and "payment_matched" in actions
    dash = client.get("/dashboard").json()
    assert dash["dollars_paid"] == 3410.0 and dash["invoices_by_state"] == {"CLOSED": 1}


def test_failed_lines_need_a_reason_or_exclusion(client):
    to_approval(client)
    lines = client.get("/runs/1").json()["invoice"]["lines"]
    all_billed = [{"line_id": l["id"], "decision": "approve"} for l in lines]
    r = client.post("/runs/1/approval", json={"user_id": ADMIN, "decision": "approve", "lines": all_billed})
    assert r.status_code == 400 and "failed check" in r.json()["detail"]
    assert run_state(client) == "PENDING_APPROVAL"
    r = client.post("/runs/1/approval", json={"user_id": ADMIN, "decision": "approve", "reason": "Vendor agreed by phone",
                                              "lines": all_billed})
    assert r.status_code == 200 and r.json()["invoice"]["payable_amount"] == 4010.0
    assert r.json()["approval"]["reason"] == "Vendor agreed by phone"


def test_only_the_right_role_may_approve(client):
    to_approval(client)
    assert approve(client, user=BOM).status_code == 403
    assert approve(client, user=DON).status_code == 403
    assert approve(client, user=OWNER).status_code == 200  # owner is top of every ladder


def test_every_line_needs_a_decision(client):
    to_approval(client)
    r = client.post("/runs/1/approval", json={"user_id": ADMIN, "decision": "approve", "lines": decisions(client)[:2]})
    assert r.status_code == 400 and "decide every line" in r.json()["detail"]


def test_rejection_closes_and_notifies(client):
    to_approval(client)
    assert client.post("/runs/1/approval", json={"user_id": ADMIN, "decision": "reject"}).status_code == 400
    r = client.post("/runs/1/approval", json={"user_id": ADMIN, "decision": "reject", "reason": "Wrong prices"})
    assert r.json()["run"]["state"] == "REJECTED" and r.json()["run"]["closed_at"]
    assert open_task(client, "approval") is None
    with get_session() as s:
        from app.models import Notification
        assert any("Rejected" in n.subject for n in s.exec(select(Notification)))


def test_insufficient_funds_then_retry(client):
    to_approval(client)
    client.post("/mock/bank/balance", json={"account_id": "acct_riverside_op", "balance": 6000})
    assert approve(client).json()["run"]["state"] == "FUNDS_INSUFFICIENT"
    ft = open_task(client, "funds_check")
    assert ft["role"] == "cfo" and "2,410.00" in ft["title"]  # 3410 + 5000 reserve - 6000
    snap = snapshot()
    client.post("/mock/tick")
    assert snapshot() == snap  # a failed retry changes nothing
    client.post("/mock/bank/balance", json={"account_id": "acct_riverside_op", "balance": 12000})
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "AWAITING_PAYMENT"
    funds_task = next(t for t in d["tasks"] if t["kind"] == "funds_check")
    assert funds_task["status"] == "done" and funds_task["completion_source"] == "system_observed"
    assert open_task(client, "payment")


def test_changed_bank_details_fail_the_invoice(client):
    start(client, "harbor_changed_bank")
    f = next(f for f in client.get("/runs/1").json()["findings"] if f["check"] == "bank_details")
    assert f["status"] == "failed" and f["evidence"]["vendor_master"]["remit_to"]["account_last4"] == "4821"
    t = open_task(client, "manual_check")
    client.post(f"/tasks/{t['id']}/resolve", json={"user_id": DON, "response": "verified", "note": "ok"})
    r = approve(client)  # lines approved, invoice-level failure, no reason
    assert r.status_code == 400 and "bank details" in r.json()["detail"]


# ---- escalation under the clock ----
def test_approval_timeout_escalates_per_ladder(client):
    to_approval(client)
    client.post("/mock/advance", json={"hours": 23})
    assert open_task(client, "approval")["escalation_level"] == 0
    client.post("/mock/advance", json={"hours": 2})  # 25h: remind the assignee
    t = open_task(client, "approval")
    assert t["escalation_level"] == 1 and t["late"]
    client.post("/mock/advance", json={"hours": 24})  # 49h: alert owner and backup approver
    assert open_task(client, "approval")["escalation_level"] == 2
    with get_session() as s:
        from app.models import Notification
        subjects = [(n.to, n.subject) for n in s.exec(select(Notification))]
    assert (ADMIN, "Reminder: Approve Harbor Pharmacy invoice #4471 ($4,010.00)") in subjects
    assert any(to == "u_owner" and subj.startswith("Alert:") for to, subj in subjects)
    client.post("/mock/advance", json={"hours": 100})
    assert open_task(client, "approval")["escalation_level"] == 2  # ladder is finished


def test_payment_task_alerts_once_late(client):
    to_approval(client)
    approve(client)
    client.post("/mock/advance", json={"hours": 24 * 18})  # 2026-11-29, before the 11-30 due date
    assert open_task(client, "payment")["escalation_level"] == 0
    client.post("/mock/advance", json={"hours": 24})  # 11-30 09:00, due at 17:00
    assert open_task(client, "payment")["escalation_level"] == 0
    client.post("/mock/advance", json={"hours": 9})  # past due
    assert open_task(client, "payment")["escalation_level"] == 1


def test_extra_step_is_a_generic_task_before_approval(client):
    pb = playbook.load("invoice_audit")
    cfg = dict(pb.settings)
    cfg["extra_steps"] = [{"key": "second_look", "title": "DON reviews the packet", "role": "don", "due_h": 6}]
    playbook.write_settings("invoice_audit", cfg)
    start(client)
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "NEEDS_INFO"
    for t in [t for t in d["tasks"] if t["status"] == "open"]:
        client.post(f"/tasks/{t['id']}/resolve", json={"user_id": DON, "response": "verified", "note": "done"})
    assert run_state(client) == "PENDING_APPROVAL"


def test_disabled_check_shows_as_not_checked_in_packet(client):
    cfg = dict(playbook.load("invoice_audit").settings)
    cfg["checks"] = {**cfg["checks"], "delivery": {"enabled": False}}
    playbook.write_settings("invoice_audit", cfg)
    start(client)
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "PENDING_APPROVAL"  # nothing unverified, so no manual check
    assert [s["check"] for s in d["packet"]["skipped"]] == ["delivery"]
    assert d["packet"]["totals"]["verified"] == 0.0  # a skipped check never counts as verified


# ---- payment matcher ----
def test_payment_matcher_cases(session):
    from app.models import Payment
    from app.workflows.invoice_audit.payment_match import find_match
    p = Payment(invoice_id=1, amount=3410.0, account_id="a", expected_ref="INV-4471")
    t = lambda amt, ref="INV-4471", payee="Harbor Pharmacy", acct="a": {"txn_id": "x", "account_id": acct, "amount": amt,
                                                                      "reference": ref, "payee": payee}
    assert find_match(p, "Harbor Pharmacy", [t(-3410.0)])[0] == "matched"
    assert find_match(p, "Harbor Pharmacy", [t(-3000.0)])[0] == "mismatch"
    assert find_match(p, "Harbor Pharmacy", [t(-3410.0, ref="", payee="Harbor Pharmacy")])[0] == "matched"
    assert find_match(p, "Harbor Pharmacy", [t(-3410.0, ref="X", payee="Medline")])[0] == "none"
    assert find_match(p, "Harbor Pharmacy", [t(-3410.0, acct="other")])[0] == "none"
    assert find_match(p, "Harbor Pharmacy", [])[0] == "none"


def test_wrong_amount_is_flagged_not_closed(client):
    to_approval(client)
    approve(client)
    pay(client, amount=-3000.0)
    d = client.get("/runs/1").json()
    assert d["run"]["state"] == "AWAITING_PAYMENT" and d["payment"]["status"] == "mismatch"
    assert open_task(client, "payment")
    n = len(d["timeline"])
    client.post("/mock/tick")
    assert len(client.get("/runs/1").json()["timeline"]) == n  # reported once, not on every tick
    pay(client)  # the right amount arrives later
    assert run_state(client) == "CLOSED"


def test_unrelated_transaction_does_not_close(client):
    to_approval(client)
    approve(client)
    pay(client, amount=-99.0, ref="OTHER-1").json()
    client.post("/mock/bank/post", json={"account_id": "acct_riverside_op", "payee": "Medline", "amount": -3410.0, "reference": "MED-1"})
    assert run_state(client) == "AWAITING_PAYMENT"


# ---- bot ----
def snapshot():
    from app.models import AuditLog, Event, Finding, Invoice, Notification, Payment, Run, Task
    with get_session() as s:
        return [[r.model_dump() for r in s.exec(select(m).order_by(m.id))]
                for m in (Run, Task, Finding, Invoice, Payment, Notification, AuditLog, Event)]


def test_tick_is_idempotent(client):
    to_approval(client)
    snap = snapshot()
    client.post("/mock/tick")
    client.post("/mock/tick")
    assert snapshot() == snap
    approve(client)
    snap = snapshot()
    client.post("/mock/tick")
    assert snapshot() == snap


def test_daily_poll_under_clock_advance(client):
    from app.connectors import get_connectors
    clock.freeze(datetime(2026, 11, 11, 6, 0))
    cfg = dict(playbook.load("invoice_audit").settings)
    cfg["inbox_poll"] = {"mode": "daily", "daily_at": "07:00"}
    playbook.write_settings("invoice_audit", cfg)
    mb = get_connectors().mailbox
    mb.drop_template("harbor_4471")
    client.post("/mock/tick")
    assert client.get("/runs").json() == []  # 06:00, not yet 07:00
    clock.advance(2)  # 08:00
    client.post("/mock/tick")
    assert len(client.get("/runs").json()) == 1
    mb.drop_template("harbor_changed_bank")
    client.post("/mock/tick")
    assert len(client.get("/runs").json()) == 1  # already read today
    clock.advance(24)
    client.post("/mock/tick")
    assert len(client.get("/runs").json()) == 2


def test_non_invoice_email_is_ignored(client):
    from app.config import mock_world_dir
    p = mock_world_dir() / "mailbox" / "inbox" / "hello.json"
    p.write_text(json.dumps({"id": "hello", "from": "friend@example.com", "to": "ap@riverside.example", "subject": "Lunch?",
                             "received_at": "2026-11-11T08:00:00", "body": "Lunch?", "thread_ref": "t1", "attachments": []}))
    client.post("/mock/tick")
    assert client.get("/runs").json() == []
    with get_session() as s:
        from app.models import AuditLog
        assert any(a.action == "email_ignored" for a in s.exec(select(AuditLog)))


# ---- settings and playbook ----
def test_settings_layering_order(client):
    start(client)
    with get_session() as s:
        from app.models import Run
        run = s.get(Run, 1)
        key = "task_defaults.approval.due_h"
        assert settings.explain("invoice_audit", key, run)[0] == 24
        cfg = dict(playbook.load("invoice_audit").settings)
        cfg["task_defaults"] = {**cfg["task_defaults"], "approval": {"due_h": 12}}
        playbook.write_settings("invoice_audit", cfg)
        assert settings.explain("invoice_audit", key, run) == (12, "playbook")
        cfg["vendors"] = {"harbor": {"task_defaults": {"approval": {"due_h": 6}}}}
        playbook.write_settings("invoice_audit", cfg)
        assert settings.explain("invoice_audit", key, run) == (6, "playbook, vendor harbor")
        assert settings.effective("invoice_audit", key, run, vendor_id="other") == 12
        run.context_json = json.dumps({**json.loads(run.context_json), "overrides": {"task_defaults": {"approval": {"due_h": 2}}}})
        assert settings.explain("invoice_audit", key, run) == (2, "this run only")
        assert settings.effective("invoice_audit", "ladders.funds_check", run)[0]["after_h"] == 4  # engine default


@pytest.mark.parametrize("patch,fragment", [
    ({"approval_enabled": False}, "approval_enabled"),
    ({"skip_funds_check": True}, "skip_funds_check"),
    ({"transfer": {"to": "x"}}, "transfer"),
    ({"reserve_min": -5}, "reserve_min"),
    ({"reserve_min": 5_000_000}, "reserve_min"),
    ({"task_defaults": {"approval": {"due_h": 0}}}, "due_h"),
    ({"task_defaults": {"payment": {"due_h": 3}}}, "payment"),
    ({"ladders": {"approval": []}}, "approval"),
    ({"inbox_poll": {"mode": "hourly"}}, "mode"),
    ({"inbox_poll": {"daily_at": "25:99"}}, "daily_at"),
    ({"checks": {"approval": {"enabled": False}}}, "approval"),
    ({"extra_steps": [{"key": "x", "title": "t", "role": "janitor", "due_h": 4}]}, "role"),
    ({"vendors": {"harbor": {"reserve_min": 0}}}, "reserve_min"),
])
def test_invalid_playbook_rejected_and_live_file_untouched(patch, fragment):
    before = playbook.load("invoice_audit").text
    cfg = {**playbook.load("invoice_audit").settings, **patch}
    with pytest.raises(playbook.PlaybookError) as e:
        playbook.write_settings("invoice_audit", cfg)
    assert fragment in str(e.value)
    assert playbook.live_path("invoice_audit").read_text() == before


def test_broken_live_file_falls_back_to_last_good():
    good = playbook.load("invoice_audit")
    playbook.live_path("invoice_audit").write_text("```yaml settings\nreserve_min: [oops\n```")
    assert playbook.load("invoice_audit").settings == good.settings


def test_write_settings_keeps_prose_and_returns_before_after():
    pb = playbook.load("invoice_audit")
    cfg = {**pb.settings, "reserve_min": 7000}
    before, after = playbook.write_settings("invoice_audit", cfg)
    assert before == pb.text and "reserve_min: 7000" in after
    assert playbook.load("invoice_audit").prose == pb.prose


def test_mock_reset_leaves_playbook_alone(client):
    cfg = {**playbook.load("invoice_audit").settings, "reserve_min": 7000}
    playbook.write_settings("invoice_audit", cfg)
    start(client)
    assert client.post("/mock/reset").json() == {"ok": True}
    assert client.get("/runs").json() == []
    assert playbook.load("invoice_audit").settings["reserve_min"] == 7000
    assert client.post("/mock/email", json={"template": "harbor_4471"}).status_code == 200  # world is rebuilt


def test_connectors_health_and_lists(client):
    h = client.get("/connectors/health").json()
    assert set(h) == {"mailbox", "vendors", "ehr", "bank"} and all(v["mode"] == "mock" for v in h.values())
    to_approval(client)
    run = client.get("/runs").json()[0]
    assert run["state"] == "PENDING_APPROVAL" and run["vendor"] == "Harbor Pharmacy" and run["at_risk"] == 600.0
    assert run["open_tasks"] == 1 and run["total"] == 4010.0
    tasks = client.get("/tasks", params={"user_id": ADMIN}).json()
    assert [t["kind"] for t in tasks] == ["approval"] and "late" in tasks[0]
    assert client.get("/tasks", params={"role": "don"}).json() == []
    assert client.get("/runs/99").status_code == 404


def test_lifespan_starts_and_stops_the_scheduler(monkeypatch):
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    from app.main import app
    with TestClient(app) as c:  # runs the lifespan: creates tables, starts the 5 s loop, cancels it on exit
        assert c.get("/runs").status_code == 200
