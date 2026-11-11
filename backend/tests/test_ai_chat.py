"""AI layer and chat agent tests. The OpenAI client is always a scripted stub: no network."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.ai import client as ai_client
from app.ai import chat as chat_mod
from app.core import clock, playbook, settings
from app.models import AgentProposal, AuditLog, Run, Task
from app.workflows.invoice_audit.classify import classify_email
from app.workflows.invoice_audit.extract import extract_invoice

ADMIN, DON, OWNER = "u_admin_rc", "u_don_rc", "u_owner"
START = datetime(2026, 11, 11, 9, 0)


def reply(content=None, calls=()):
    tcs = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
           for i, (n, a) in enumerate(calls)]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tcs or None))])


class Stub:
    """Returns scripted responses in order and records every request."""
    def __init__(self, *script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return self.script.pop(0)


@pytest.fixture(autouse=True)
def _ai(monkeypatch):
    monkeypatch.setenv("AI_MODE", "live")
    ai_client.set_client(Stub())  # empty script: any unscripted call raises, never reaches AWS or OpenAI
    yield
    ai_client.set_client(None)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    clock.freeze(START)
    from app.main import app
    c = TestClient(app)
    assert c.post("/mock/email", json={"template": "harbor_4471"}).status_code == 200
    tid = next(t["id"] for t in c.get("/runs/1").json()["tasks"] if t["kind"] == "manual_check")
    assert c.post(f"/tasks/{tid}/resolve", json={"user_id": DON, "response": "verified", "note": "ok"}).status_code == 200
    assert c.get("/runs/1").json()["run"]["state"] == "PENDING_APPROVAL"
    return c


def say(session, user, text, *script, run_id=1):
    ai_client.set_client(Stub(*script))
    out = chat_mod.chat(session, user, text, run_id)
    session.commit()
    return out


def propose_12h():
    return reply(calls=[("propose_change", {"changes": [{"key": "task_defaults.approval.due_h", "to": 12}]})])


def approval_due(session):
    return session.exec(select(Task).where(Task.kind == "approval", Task.status == "open")).first().due_at


# ---- chat guards ----
def test_proposal_is_pending_and_changes_nothing(api, session):
    before = playbook.load("invoice_audit").text
    due = approval_due(session)
    out = say(session, ADMIN, "give approvals 12h", propose_12h(), reply("Only this time or always?"))
    assert out["proposals"][0]["status"] == "pending" and "24 -> 12" in out["proposals"][0]["summary"]
    assert playbook.load("invoice_audit").text == before
    assert approval_due(session) == due


def test_model_cannot_confirm_in_the_turn_it_proposed(api, session):
    out = say(session, ADMIN, "give approvals 12h", propose_12h(),
              reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("done"))
    p = session.get(AgentProposal, 1)
    assert p.status == "pending"
    assert out["proposals"][0]["id"] == 1
    assert playbook.load("invoice_audit").settings["task_defaults"]["approval"]["due_h"] == 24


def test_confirm_refused_without_permission(api, session):
    say(session, DON, "give approvals 12h", propose_12h(), reply("ask"))
    say(session, DON, "always", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("refused"))
    assert session.get(AgentProposal, 1).status == "pending"
    assert playbook.load("invoice_audit").settings["task_defaults"]["approval"]["due_h"] == 24


def test_owner_only_keys(api, session):
    say(session, ADMIN, "reserve 8000", reply(calls=[("propose_change", {"changes": [{"key": "reserve_min", "to": 8000}]})]), reply("ask"))
    say(session, ADMIN, "always", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("no"))
    assert session.get(AgentProposal, 1).status == "pending"
    say(session, OWNER, "reserve 8000", reply(calls=[("propose_change", {"changes": [{"key": "reserve_min", "to": 8000}]})]), reply("ask"))
    say(session, OWNER, "always", reply(calls=[("confirm_proposal", {"proposal_id": 2, "scope": "always"})]), reply("ok"))
    assert playbook.load("invoice_audit").settings["reserve_min"] == 8000


def test_only_this_time_writes_to_the_run_not_the_playbook(api, session):
    before = playbook.load("invoice_audit").text
    say(session, ADMIN, "12h on this one", propose_12h(), reply("ask"))
    say(session, ADMIN, "only this time", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "once"})]), reply("done"))
    run = session.get(Run, 1)
    assert json.loads(run.context_json)["overrides"]["task_defaults"]["approval"]["due_h"] == 12
    assert playbook.load("invoice_audit").text == before
    assert approval_due(session) == START + timedelta(hours=12)


def test_always_rewrites_playbook_audits_and_recomputes_due(api, session):
    prose = playbook.load("invoice_audit").prose
    say(session, ADMIN, "12h for approvals", propose_12h(), reply("ask"))
    say(session, ADMIN, "always", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("done"))
    pb = playbook.load("invoice_audit")
    assert pb.settings["task_defaults"]["approval"]["due_h"] == 12 and pb.prose == prose
    assert approval_due(session) == START + timedelta(hours=12)
    row = session.exec(select(AuditLog).where(AuditLog.action == "playbook_changed")).one()
    d = json.loads(row.detail_json)
    assert d["proposal_id"] == 1 and "due_h: 24" in d["before"] and "due_h: 12" in d["after"]
    assert row.actor == ADMIN


def test_revert_restores_the_previous_playbook(api, session):
    original = playbook.load("invoice_audit").text
    say(session, ADMIN, "12h", propose_12h(), reply("ask"))
    say(session, ADMIN, "always", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("done"))
    say(session, ADMIN, "undo", reply(calls=[("propose_revert", {"audit_id": "last"})]), reply("ask"))
    say(session, ADMIN, "always", reply(calls=[("confirm_proposal", {"proposal_id": 2, "scope": "always"})]), reply("done"))
    assert playbook.load("invoice_audit").text == original


def test_vendor_rule_goes_under_vendors_and_skips_check(api, session):
    ch = {"changes": [{"key": "checks.delivery.enabled", "to": False}], "vendor_id": "harbor"}
    say(session, ADMIN, "turn off delivery for Harbor", reply(calls=[("propose_change", ch)]), reply("ask"))
    say(session, ADMIN, "always", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("done"))
    assert playbook.load("invoice_audit").settings["vendors"]["harbor"]["checks"]["delivery"]["enabled"] is False


@pytest.mark.parametrize("key,to", [("approval.enabled", False), ("funds_check.enabled", False),
                                    ("task_defaults.approval.due_h", 0), ("transfer.allowed", True),
                                    ("vendors.harbor.reserve_min", 1)])
def test_locked_or_invalid_keys_never_become_proposals(api, session, key, to):
    out = say(session, ADMIN, "do it", reply(calls=[("propose_change", {"changes": [{"key": key, "to": to}]})]), reply("sorry"))
    assert out["proposals"] == [] and session.exec(select(AgentProposal)).first() is None


def test_extra_step_proposal(api, session):
    step = {"key": "second_approver", "title": "Second approver signs off", "role": "owner", "due_h": 12}
    say(session, ADMIN, "add a second approver", reply(calls=[("propose_extra_step", step)]), reply("ask"))
    say(session, ADMIN, "always", reply(calls=[("confirm_proposal", {"proposal_id": 1, "scope": "always"})]), reply("done"))
    assert playbook.load("invoice_audit").settings["extra_steps"][0]["key"] == "second_approver"


def test_tools_are_whitelisted_no_money_or_approval_tools():
    names = {t["function"]["name"] for t in chat_mod.TOOLS}
    assert not any(w in n for n in names for w in ("pay", "transfer", "approve", "resolve", "send"))


def test_history_and_assistant_text_saved(api, session):
    say(session, ADMIN, "hello", reply("Hi, I can help."))
    h = chat_mod.history(session, ADMIN)
    assert [m["role"] for m in h] == ["user", "assistant"] and h[1]["content"] == "Hi, I can help."


def test_chat_offline_in_cache_mode_without_cached_answer(api, session, monkeypatch):
    monkeypatch.setenv("AI_MODE", "cache")
    out = say(session, ADMIN, "hello")
    assert out["reply"] == chat_mod.OFFLINE


def test_chat_cache_replays_in_cache_mode(api, session, monkeypatch):
    from app.models import ChatMessage
    say(session, ADMIN, "what is waiting?", reply("Nothing late."))
    for m in session.exec(select(ChatMessage)).all():  # same conversation start, so same cache key
        session.delete(m)
    session.commit()
    monkeypatch.setenv("AI_MODE", "cache")
    stub = Stub()
    ai_client.set_client(stub)
    out = chat_mod.chat(session, ADMIN, "what is waiting?", 1)
    assert out["reply"] == "Nothing late." and stub.requests == []


# ---- AI layer: validate, retry once, fall back, cache ----
def email():
    from app.connectors import get_connectors
    get_connectors().mailbox.drop_template("harbor_4471")
    return get_connectors().mailbox.poll()[0]


GOOD = json.dumps({"kind": "invoice", "vendor_hint": "Harbor Pharmacy", "confidence": 0.97})


def test_classify_validates_and_caches(api):
    stub = Stub(reply(GOOD))
    ai_client.set_client(stub)
    out = classify_email(email())
    assert out.kind == "invoice" and len(stub.requests) == 1
    out2 = classify_email(email())  # served from cache, no second call
    assert out2.kind == "invoice" and len(stub.requests) == 1


def test_invalid_answer_retries_once_then_succeeds(api):
    stub = Stub(reply("not json"), reply(GOOD))
    ai_client.set_client(stub)
    assert classify_email(email()).kind == "invoice" and len(stub.requests) == 2


def test_two_invalid_answers_raise_so_slot_can_fall_back(api):
    ai_client.set_client(Stub(reply('{"kind": "banana", "confidence": 2}'), reply("{}")))
    with pytest.raises(ai_client.AIError):
        classify_email(email())


def test_cache_mode_serves_only_from_cache(api, monkeypatch):
    monkeypatch.setenv("AI_MODE", "cache")
    ai_client.set_client(Stub(reply(GOOD)))
    with pytest.raises(ai_client.AICacheMiss):
        classify_email(email())


def test_slots_fall_back_when_ai_fails(api):
    from app.workflows.invoice_audit import slots
    ai_client.set_client(Stub())  # empty script: any call raises
    kind, via = slots.classify_email(email())
    assert (kind, via) == ("invoice", "fallback")
    extract, via = slots.extract_invoice(email())
    assert via == "fallback" and extract.invoice_no == "4471"


def test_extract_only_keeps_known_item_keys(api):
    from app.connectors import get_connectors
    from app.workflows.invoice_audit import slots
    good = slots._regex_extract(email()).model_dump(mode="json")
    good["lines"][0]["item_key"] = "made_up_key"
    ai_client.set_client(Stub(reply(json.dumps(good))))
    out = extract_invoice(email())
    assert out.lines[0].item_key is None and out.lines[1].item_key == good["lines"][1]["item_key"]


def test_text_slots(api):
    from app import ai
    ai_client.set_client(Stub(reply("  Short summary.  ")))
    assert ai.summarize_packet({"totals": {"billed": 1}}) == "Short summary."
    with pytest.raises(ai_client.AIError):
        ai_client.set_client(Stub(reply(""), reply("  ")))
        ai.draft_dispute([{"description": "x"}])
