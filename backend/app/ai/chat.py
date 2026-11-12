"""Chat agent: explains status and PROPOSES changes. It can read, propose, and confirm only through
four server-side guards. It has no tool that approves, resolves, edits a finding or moves money.

Confirm guards (all enforced in `_confirm`, never by the prompt):
  1. the proposal is pending
  2. it was proposed in this user's own chat
  3. the user wrote a message AFTER the proposal (the model cannot confirm in the turn it proposed)
  4. the user's role may confirm these keys at this scope (core/permissions.require_change)
"""
import copy
import json
import logging
from datetime import timedelta

from sqlmodel import Session, select

from ..api.serialize import finding_out, j, task_out
from ..core import audit, bot, clock, permissions, playbook, settings
from ..core import tasks as task_engine
from ..models import AgentProposal, AuditLog, ChatMessage, Finding, Run, Task, User
from ..workflows.invoice_audit import playbook_schema  # noqa: F401  (registers the playbook)
from . import cache
from .client import AIError, get_client, mode, model, prompt

log = logging.getLogger("chat")
RUN_TYPE = "invoice_audit"
MAX_STEPS = 6
HISTORY = 12
OFFLINE = "I can't answer right now: the AI is offline and has no saved answer for this message."


class ChatRefused(ValueError):
    """A guard or validator said no. The message goes back to the model and the user in plain words."""


# ---------------------------------------------------------------- tool schemas
def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": required or []}}}


_RUN = {"run_id": {"type": "integer", "description": "Run id. Omit to use the run the user has open."}}
_VENDOR = {"vendor_id": {"type": "string", "description": "Vendor id for a rule that applies to one vendor's invoices (for 'always'). Omit for all vendors."}}
TOOLS = [
    _fn("list_runs", "List workflow runs with state, vendor, invoice number, totals and late tasks."),
    _fn("get_run", "Details of one run: state, invoice lines, findings, tasks, packet, payment, recent timeline.", _RUN),
    _fn("list_tasks", "Open tasks, optionally for one role.", {"role": {"type": "string"}}),
    _fn("get_settings", "Every editable setting with its effective value and where it comes from.", {**_RUN, **_VENDOR}),
    _fn("explain_finding", "What a check compared and why it passed or failed.", {"finding_id": {"type": "integer"}}, ["finding_id"]),
    _fn("check_inbox_now", "Read the accounts-payable inbox right now and run the bot once, so any new unread invoice emails start a workflow. "
        "Use it whenever the user's meaning is to look for or pick up new mail or invoices, however it is worded: "
        "'any new invoices?', 'check the inbox', 'did Harbor send anything?', 'look for new mail', 'pull in the latest emails'. "
        "Do not use it to answer questions about runs that already exist (use list_runs)."),
    _fn("propose_change", "Propose changing settings. Nothing changes until the user confirms. Keys: checks.<price|date|delivery|math|duplicate|bank_details>.enabled, "
        "task_defaults.<manual_entry|manual_check|approval|funds_check>.due_h, ladders.<kind>, manual_check_roles.<delivery|price|date>, "
        "inbox_poll.mode, inbox_poll.daily_at, approval_owner_threshold, reserve_min.",
        {"changes": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string"}, "to": {}}, "required": ["key", "to"]}},
         "rationale": {"type": "string"}, **_RUN, **_VENDOR}, ["changes"]),
    _fn("propose_extra_step", "Propose adding an extra task (such as a second approver) that must be done before approval.",
        {"key": {"type": "string"}, "title": {"type": "string"}, "role": {"type": "string"}, "due_h": {"type": "number"}, "rationale": {"type": "string"}, **_RUN, **_VENDOR},
        ["key", "title", "role", "due_h"]),
    _fn("propose_note", "Propose adding a note (a fact about a vendor or how to work) to the playbook prose.", {"note": {"type": "string"}}, ["note"]),
    _fn("propose_revert", "Propose undoing a playbook change. audit_id is a playbook_changed audit id, or 'last'.", {"audit_id": {"type": "string"}}),
    _fn("propose_restore_defaults", "Propose restoring the factory default playbook."),
    _fn("confirm_proposal", "Apply a proposal AFTER the user answered 'only this time' (once) or 'always'.",
        {"proposal_id": {"type": "integer"}, "scope": {"type": "string", "enum": ["once", "always"]}}, ["proposal_id", "scope"]),
    _fn("cancel_proposal", "Drop a pending proposal.", {"proposal_id": {"type": "integer"}}, ["proposal_id"]),
]


# ---------------------------------------------------------------- helpers
def _run(session, run_id):
    run = session.get(Run, run_id) if run_id else None
    if run_id and run is None:
        raise ChatRefused(f"Run {run_id} not found")
    return run


def _vendor_of(run):
    return settings.run_context(run).get("vendor_id") if run else None


def _validate(changes: list[dict], vendor_id: str | None) -> None:
    """Dry-run the changes through the playbook schema (the whitelist). Raises ChatRefused."""
    base = copy.deepcopy(playbook.load(RUN_TYPE).settings)
    for c in changes:
        root = c["key"].split(".")[0]
        if root not in settings.EDITABLE_ROOTS:
            raise ChatRefused(f"'{c['key']}' is not a setting that can be changed")
        settings.set_path(base, f"vendors.{vendor_id}.{c['key']}" if vendor_id else c["key"], c["to"])
    try:
        playbook.parse(RUN_TYPE, playbook.render(playbook.load(RUN_TYPE).text, base))
    except playbook.PlaybookError as e:
        raise ChatRefused(str(e)) from e


def _fmt(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _describe(p: AgentProposal) -> str:
    ch = j(p.changes_json, [])
    if p.kind == "change":
        return "; ".join(f"{c['key']}: {_fmt(c.get('from'))} -> {_fmt(c['to'])}" for c in ch)
    return {"note": "add a note: " + j(p.payload_json, {}).get("note", ""), "revert": "undo a playbook change",
            "restore": "restore the factory default playbook"}[p.kind]


def _proposal_out(p: AgentProposal) -> dict:
    return {"id": p.id, "kind": p.kind, "status": p.status, "run_id": p.run_id, "vendor_id": p.vendor_id,
            "summary": _describe(p), "rationale": p.rationale}


def _new_proposal(session, ctx, kind, *, changes=None, payload=None, rationale="", run_id=None, vendor_id=None) -> dict:
    p = AgentProposal(user_id=ctx["user_id"], chat_msg_id=ctx["msg_id"], kind=kind, run_type=RUN_TYPE,
                      run_id=run_id or ctx.get("run_id"), vendor_id=vendor_id,
                      changes_json=json.dumps(changes or []), payload_json=json.dumps(payload or {}),
                      rationale=rationale or "", proposed_at=clock.now())
    session.add(p)
    session.flush()
    audit.log(session, "claude", "proposal_created", p.run_id,
              {"proposal_id": p.id, "kind": kind, "summary": _describe(p), "user": ctx["user_id"]})
    return {"proposal_id": p.id, "status": "pending", "summary": _describe(p),
            "next": "Ask the user: only this time, always, or cancel. Do not confirm yet."}


def _recompute_due(session, p: AgentProposal, run_type: str, scope: str) -> int:
    n = 0
    runs = [session.get(Run, p.run_id)] if scope == "once" else session.exec(
        select(Run).where(Run.type == run_type, Run.closed_at == None)).all()  # noqa: E711
    for run in runs:
        if run is None or (scope == "always" and p.vendor_id and _vendor_of(run) != p.vendor_id):
            continue
        for t in session.exec(select(Task).where(Task.run_id == run.id, Task.status == "open")):
            if t.kind == "extra_step":
                continue
            hours = settings.effective(run_type, f"task_defaults.{t.kind}.due_h", run)
            if hours is None:
                continue
            due = t.created_at + timedelta(hours=hours)
            if due != t.due_at:
                audit.log(session, "system", "task_due_changed", run.id, {"task_id": t.id, "from": t.due_at, "to": due})
                t.due_at = due
                session.add(t)
                n += 1
    return n


# ---------------------------------------------------------------- confirm (the guards)
def _confirm(session: Session, ctx: dict, proposal_id: int, scope: str) -> dict:
    p = session.get(AgentProposal, proposal_id)
    if p is None:
        raise ChatRefused(f"Proposal {proposal_id} not found")
    if p.status != "pending":  # guard 1
        raise ChatRefused(f"Proposal {proposal_id} is already {p.status}")
    if p.user_id != ctx["user_id"]:  # guard 2
        raise ChatRefused("That proposal belongs to another person's chat")
    last = session.exec(select(ChatMessage).where(ChatMessage.user_id == ctx["user_id"], ChatMessage.role == "user")
                        .order_by(ChatMessage.id.desc())).first()
    if last is None or last.id <= p.chat_msg_id:  # guard 3
        raise ChatRefused("The user has not answered yet. Ask them first.")
    user = session.get(User, ctx["user_id"])
    changes = j(p.changes_json, [])
    if scope == "once" and (p.kind != "change" or p.run_id is None):
        raise ChatRefused("'Only this time' needs a setting change on a specific invoice. Use 'always' or cancel.")
    permissions.require_change(user, scope, [c["key"] for c in changes])  # guard 4

    run = session.get(Run, p.run_id) if p.run_id else None
    if p.kind == "change":
        _validate(changes, p.vendor_id if scope == "always" else None)
    if scope == "once":
        c = settings.run_context(run)
        for ch in changes:
            settings.set_path(c.setdefault("overrides", {}), ch["key"], ch["to"])
        run.context_json = json.dumps(c, default=str)
        session.add(run)
        audit.log(session, user.id, "setting_override", run.id, {"proposal_id": p.id, "changes": changes})
    else:
        live = playbook.load(p.run_type)
        if p.kind == "change":
            new = copy.deepcopy(live.settings)
            for ch in changes:
                settings.set_path(new, f"vendors.{p.vendor_id}.{ch['key']}" if p.vendor_id else ch["key"], ch["to"])
            before, after = playbook.write_settings(p.run_type, new)
        elif p.kind == "note":
            before, after = playbook.append_note(p.run_type, j(p.payload_json, {})["note"])
        else:
            text = j(p.payload_json, {}).get("text") or playbook.default_text(p.run_type)
            before, after = playbook.write_text(p.run_type, text)
        audit.log(session, user.id, "playbook_changed", p.run_id,
                  {"proposal_id": p.id, "kind": p.kind, "scope": "always", "vendor_id": p.vendor_id,
                   "changes": changes, "before": before, "after": after})
    moved = _recompute_due(session, p, p.run_type, scope) if p.kind == "change" else 0
    p.status, p.scope, p.decided_by, p.decided_at = "applied", scope, user.id, clock.now()
    session.add(p)
    audit.log(session, user.id, "proposal_applied", p.run_id, {"proposal_id": p.id, "scope": scope})
    return {"applied": True, "scope": scope, "summary": _describe(p), "due_times_updated": moved}


def _cancel(session, ctx, proposal_id):
    p = session.get(AgentProposal, proposal_id)
    if p is None or p.user_id != ctx["user_id"] or p.status != "pending":
        raise ChatRefused("No pending proposal of yours with that id")
    p.status, p.decided_by, p.decided_at = "cancelled", ctx["user_id"], clock.now()
    session.add(p)
    audit.log(session, ctx["user_id"], "proposal_cancelled", p.run_id, {"proposal_id": p.id})
    return {"cancelled": True}


# ---------------------------------------------------------------- tool dispatch
def run_tool(session: Session, ctx: dict, name: str, a: dict):
    run_id = a.get("run_id") or ctx.get("run_id")
    if name == "list_runs":
        from ..api.routes_runs import list_runs
        return list_runs(session)
    if name == "get_run":
        from ..api.routes_runs import get_run
        if not run_id:
            raise ChatRefused("Which run? Give a run_id.")
        out = get_run(run_id, session)
        out["timeline"] = out["timeline"][-10:]
        return out
    if name == "list_tasks":
        q = select(Task).where(Task.status == "open").order_by(Task.due_at)
        return [task_out(t) for t in session.exec(q) if not a.get("role") or t.role == a["role"]]
    if name == "get_settings":
        run = _run(session, run_id)
        return settings.snapshot(RUN_TYPE, run, a.get("vendor_id"))
    if name == "explain_finding":
        f = session.get(Finding, a["finding_id"])
        if f is None:
            raise ChatRefused("Finding not found")
        return finding_out(f)
    if name == "check_inbox_now":
        audit.log(session, "claude", "inbox_check_requested", None, {"user": ctx["user_id"]})
        before = session.exec(select(AuditLog).order_by(AuditLog.id.desc())).first()
        before_id = before.id if before else 0
        out = bot.tick(session, force_poll=True)
        # Runs started by THIS check belong to this chat: the activity feed follows them here.
        # Runs the scheduler starts on its own are never watched, so they only show in the Workflows tab.
        started = session.exec(select(AuditLog).where(AuditLog.id > before_id, AuditLog.action == "run_started")).all()
        runs = []
        for a in started:
            run = session.get(Run, a.run_id)
            if run is None:
                continue
            audit.log(session, "claude", "chat_run_watched", run.id, {"user": ctx["user_id"]})
            open_tasks = session.exec(select(Task).where(Task.run_id == run.id, Task.status == "open")).all()
            runs.append({"run_id": run.id, "title": run.title, "state": run.state,
                         "open_tasks": [{"title": t.title, "role": t.role} for t in open_tasks]})
        return {**out, "new_runs": runs,
                "note": "Give a short status of each new run (state and who has to act). Details are in the Workflows tab. "
                        "Then ask the user what they want to do next."}
    if name == "propose_change":
        changes = a.get("changes") or []
        if not changes:
            raise ChatRefused("No changes given")
        run = _run(session, run_id)
        vendor = a.get("vendor_id")
        _validate(changes, vendor)
        changes = [{"key": c["key"], "from": settings.explain(RUN_TYPE, c["key"], run, vendor)[0], "to": c["to"]} for c in changes]
        return _new_proposal(session, ctx, "change", changes=changes, rationale=a.get("rationale", ""), run_id=run_id, vendor_id=vendor)
    if name == "propose_extra_step":
        run = _run(session, run_id)
        current = settings.effective(RUN_TYPE, "extra_steps", run, a.get("vendor_id"), default=[]) or []
        step = {k: a[k] for k in ("key", "title", "role", "due_h")}
        new = [s for s in current if s.get("key") != step["key"]] + [step]
        _validate([{"key": "extra_steps", "to": new}], a.get("vendor_id"))
        return _new_proposal(session, ctx, "change", changes=[{"key": "extra_steps", "from": current, "to": new}],
                             rationale=a.get("rationale", ""), run_id=run_id, vendor_id=a.get("vendor_id"))
    if name == "propose_note":
        note = (a.get("note") or "").strip()
        if not note or len(note) > 300:
            raise ChatRefused("A note must be 1 to 300 characters")
        return _new_proposal(session, ctx, "note", payload={"note": note})
    if name == "propose_revert":
        want = str(a.get("audit_id") or "last")
        q = select(AuditLog).where(AuditLog.action == "playbook_changed").order_by(AuditLog.id.desc())
        rows = session.exec(q).all()
        row = rows[0] if want == "last" and rows else next((r for r in rows if str(r.id) == want), None)
        if row is None:
            raise ChatRefused("There is no playbook change to undo")
        return _new_proposal(session, ctx, "revert", payload={"text": j(row.detail_json, {})["before"], "audit_id": row.id})
    if name == "propose_restore_defaults":
        return _new_proposal(session, ctx, "restore", payload={})
    if name == "confirm_proposal":
        return _confirm(session, ctx, a["proposal_id"], a["scope"])
    if name == "cancel_proposal":
        return _cancel(session, ctx, a["proposal_id"])
    raise ChatRefused(f"Unknown tool {name}")


# ---------------------------------------------------------------- model step (cached in AI_MODE=cache)
def _step(messages: list[dict]) -> dict:
    k = cache.key("chat", model(), messages)
    if mode() == "cache":
        hit = cache.get("chat", k)
        if hit is None:
            raise AIError("no cached chat answer")
        return json.loads(hit)
    try:
        r = get_client().chat.completions.create(model=model(), messages=messages, tools=TOOLS, temperature=0)
    except AIError:
        raise
    except Exception as e:  # network, auth, rate limit: never a 500 in the chat window
        log.error("chat model call failed: %s", e)
        raise AIError(str(e)) from e
    m = r.choices[0].message
    out = {"content": m.content, "tool_calls": [{"id": t.id, "name": t.function.name, "arguments": t.function.arguments}
                                                for t in (m.tool_calls or [])]}
    cache.put("chat", k, json.dumps(out))
    return out


def _system(session, user: User, run_id) -> str:
    pb = playbook.load(RUN_TYPE)
    ctx = f"\n\nYou are talking to {user.name}, the {user.role.replace('_', ' ')}. Today is {clock.now():%Y-%m-%d %H:%M}."
    if run_id:
        ctx += f" They have run {run_id} open."
    return prompt("chat") + ctx + "\n\n# Current playbook (prose)\n" + pb.prose


# ---------------------------------------------------------------- entry point
def chat(session: Session, user_id: str, message: str, run_id: int | None = None) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise permissions.Forbidden("Unknown user")
    um = ChatMessage(user_id=user_id, run_id=run_id, role="user", content=message, at=clock.now())
    session.add(um)
    session.flush()
    ctx = {"user_id": user_id, "run_id": run_id, "msg_id": um.id}
    hist = session.exec(select(ChatMessage).where(ChatMessage.user_id == user_id, ChatMessage.id < um.id)
                        .order_by(ChatMessage.id.desc()).limit(HISTORY)).all()[::-1]
    messages = [{"role": "system", "content": _system(session, user, run_id)}]
    messages += [{"role": m.role, "content": m.content} for m in hist] + [{"role": "user", "content": message}]

    reply = OFFLINE
    try:
        for _ in range(MAX_STEPS):
            out = _step(messages)
            if not out["tool_calls"]:
                reply = out["content"] or ""
                break
            messages.append({"role": "assistant", "content": out["content"], "tool_calls": [
                {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": t["arguments"]}}
                for t in out["tool_calls"]]})
            for t in out["tool_calls"]:
                try:
                    with session.begin_nested():  # a refused tool must not leave half-written rows
                        res = run_tool(session, ctx, t["name"], json.loads(t["arguments"] or "{}"))
                except (ChatRefused, permissions.Forbidden, LookupError, KeyError, ValueError) as e:
                    res = {"error": str(e)}
                messages.append({"role": "tool", "tool_call_id": t["id"], "content": json.dumps(res, default=str)})
        else:
            reply = "I got stuck on that. Could you rephrase?"
    except AIError as e:
        log.warning("chat unavailable: %s", e)
        reply = OFFLINE
    audit.log(session, "claude", "ai_call", run_id, {"slot": "chat", "user": user_id})
    session.add(ChatMessage(user_id=user_id, run_id=run_id, role="assistant", content=reply, at=clock.now()))
    pending = session.exec(select(AgentProposal).where(AgentProposal.user_id == user_id, AgentProposal.status == "pending")).all()
    return {"reply": reply, "proposals": [_proposal_out(p) for p in pending]}


def history(session: Session, user_id: str, limit: int = 50) -> list[dict]:
    rows = session.exec(select(ChatMessage).where(ChatMessage.user_id == user_id)
                        .order_by(ChatMessage.id.desc()).limit(limit)).all()[::-1]
    return [{"id": m.id, "role": m.role, "content": m.content, "at": m.at, "run_id": m.run_id} for m in rows]
