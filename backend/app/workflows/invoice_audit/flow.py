"""Invoice audit workflow handler: the section 6 state machine.

Implements the generic handler interface from workflows/registry.py:
  run_type, on_email, advance, observe.
`advance` is idempotent and keyed off the run state; it keeps stepping until nothing more can happen,
so one tick takes a fresh email all the way to its first wait (manual check or approval).
"""
import json

from sqlmodel import Session

from ...config import get_config
from ...connectors import get_connectors
from ...core import audit, clock, permissions, tasks
from ...models import Event, Finding, Invoice, InvoiceLine, Run, User
from ...schemas import Email
from . import checks, funds, packet, payment_match, slots, state

VIA = {"manual_entry": "email", "manual_check": "ehr_alert", "extra_step": "teams", "approval": "email"}


def _ai_audit(session, run_id, slot: str, via: str, **detail):
    audit.log(session, "claude" if via == "ai" else "system", "ai_call", run_id, {"slot": slot, "via": via, **detail})


class InvoiceAuditHandler:
    run_type = state.RUN_TYPE

    # ---- 1. email in ----
    def on_email(self, session: Session, email: Email) -> bool:
        building = get_config()["mailbox_buildings"].get(email.to)
        if building is None:
            return False
        kind, via = slots.classify_email(email)
        _ai_audit(session, None, "classify_email", via, email_id=email.id, kind=kind)
        if kind != "invoice":
            return False
        now = clock.now()
        event = Event(type="email", source="mailbox", building_id=building, received_at=now,
                      payload_json=json.dumps({"email_id": email.id, "subject": email.subject}))
        session.add(event)
        session.flush()
        run = Run(type=self.run_type, state="RECEIVED", building_id=building, title=email.subject, created_at=now,
                  updated_at=now, context_json=json.dumps({"email": email.model_dump(by_alias=True), "event_id": event.id,
                                                             "overrides": {}}, default=str))
        session.add(run)
        session.flush()
        audit.log(session, "system", "run_started", run.id, {"email_id": email.id, "state": "RECEIVED"})
        return True

    # ---- 2. advance ----
    def advance(self, session: Session, run: Run) -> None:
        steps = {"RECEIVED": self._extract, "EXTRACTED": self._check, "CHECKED": self._after_checks,
                 "NEEDS_INFO": self._needs_info, "FUNDS_CHECK": self._funds, "FUNDS_INSUFFICIENT": self._funds,
                 "PAID": self._paid}
        for _ in range(15):
            step = steps.get(run.state)
            if step is None or not step(session, run):
                return

    def observe(self, session: Session) -> None:
        payment_match.observe(session)

    # ---- steps (each returns True when it changed the state) ----
    def _extract(self, session, run) -> bool:
        email = Email.model_validate(state.ctx(run)["email"])
        extract = None
        for attempt in (1, 2):
            extract, via = slots.extract_invoice(email)
            _ai_audit(session, run.id, "extract_invoice", via, attempt=attempt, valid=extract is not None)
            if extract is not None:
                break
        if extract is None:
            state.transition(session, run, "MANUAL_ENTRY", reason="extraction invalid twice")
            tasks.create_task(session, run_id=run.id, kind="manual_entry", via=VIA["manual_entry"],
                              title=f"Enter this invoice by hand: '{email.subject}' could not be read",
                              due_in_h=state.task_due_h(run, "manual_entry"),
                              role=state.task_role(run, "manual_entry"),
                              blocks=[{"type": "text", "text": "The invoice could not be read automatically."}])
            return True
        inv = Invoice(run_id=run.id, vendor_id=extract.vendor_id, invoice_no=extract.invoice_no,
                      invoice_date=extract.invoice_date, due_date=extract.due_date, period_from=extract.period_from,
                      period_to=extract.period_to, total=extract.total, remit_to_json=extract.remit_to.model_dump_json(),
                      source_event_id=state.ctx(run).get("event_id"))
        session.add(inv)
        session.flush()
        for l in extract.lines:
            session.add(InvoiceLine(invoice_id=inv.id, **l.model_dump()))
        session.flush()
        vendor = (get_connectors().vendors.vendor_master(inv.vendor_id) or {}).get("name", inv.vendor_id)
        run.title = f"{vendor} invoice #{inv.invoice_no}"
        state.set_ctx(run, vendor_id=inv.vendor_id, vendor_name=vendor)
        state.transition(session, run, "EXTRACTED", invoice_id=inv.id, lines=len(extract.lines))
        return True

    def _check(self, session, run) -> bool:
        inv = state.invoice_of(session, run)
        found = checks.run_all(session, run, inv)
        for f in found:
            session.add(f)
        session.flush()
        counts: dict[str, int] = {}
        for f in found:
            counts[f.status] = counts.get(f.status, 0) + 1
        audit.log(session, "system", "checks_run", run.id, counts)
        state.transition(session, run, "CHECKED", **counts)
        return True

    def _after_checks(self, session, run) -> bool:
        inv = state.invoice_of(session, run)
        lines = {l.id: l for l in state.lines_of(session, inv)}
        waiting = 0
        for f in state.findings_of(session, inv):
            if f.status != "unverified":
                continue
            line = lines.get(f.line_id)
            what = line.description if line else "the invoice"
            role = state.eff(run, f"manual_check_roles.{f.check}", inv.vendor_id) or state.task_role(run, "manual_check")
            tasks.create_task(
                session, run_id=run.id, kind="manual_check", role=role, via=VIA["manual_check"],
                due_in_h=state.task_due_h(run, "manual_check", inv.vendor_id),
                title=f"Confirm {f.check.replace('_', ' ')} for {what}",
                payload={"finding_id": f.id, "line_id": f.line_id, "check": f.check},
                blocks=[{"type": "text", "text": f.message},
                        {"type": "kv", "items": [["Invoice", f"#{inv.invoice_no}"], ["Line", what],
                                                 ["Amount", f"${line.amount:,.2f}" if line else f"${inv.total:,.2f}"]]}])
            waiting += 1
        for step in state.eff(run, "extra_steps", inv.vendor_id, default=[]) or []:
            tasks.create_task(
                session, run_id=run.id, kind="extra_step", role=step["role"], due_in_h=float(step["due_h"]),
                via=VIA["extra_step"], title=f"{step['title']} (invoice #{inv.invoice_no})",
                payload={"step_key": step["key"]},
                blocks=[{"type": "text", "text": step["title"]}])
            waiting += 1
        if waiting:
            state.transition(session, run, "NEEDS_INFO", open_tasks=waiting)
        else:
            self._open_approval(session, run, inv)
        return True

    def _needs_info(self, session, run) -> bool:
        if state.open_tasks(session, run, "manual_check", "extra_step"):
            return False
        self._open_approval(session, run, state.invoice_of(session, run))
        return True

    def _open_approval(self, session, run, inv) -> None:
        pk = packet.build(session, inv)
        summary, via = slots.summarize_packet(pk)
        _ai_audit(session, run.id, "summarize_packet", via)
        pk["summary"] = summary
        state.set_ctx(run, packet_summary=summary)
        threshold = float(state.eff(run, "approval_owner_threshold", inv.vendor_id))
        role = "owner" if inv.total > threshold else state.task_role(run, "approval", inv.vendor_id)
        t = pk["totals"]
        tasks.create_task(
            session, run_id=run.id, kind="approval", role=role, via=VIA["approval"],
            due_in_h=state.task_due_h(run, "approval", inv.vendor_id),
            title=f"Approve {run.title} (${inv.total:,.2f})",
            payload={"totals": t, "failed": len(pk["failed"]), "unverified": len(pk["unverified"])},
            blocks=[{"type": "text", "text": summary},
                    {"type": "kv", "items": [["Billed", f"${t['billed']:,.2f}"], ["Verified", f"${t['verified']:,.2f}"],
                                             ["At risk", f"${t['at_risk']:,.2f}"]]}])
        state.transition(session, run, "PENDING_APPROVAL")

    def _funds(self, session, run) -> bool:
        return funds.attempt(session, run, state.invoice_of(session, run))

    def _paid(self, session, run) -> bool:
        payment_match.finish(session, run)
        return True


handler = InvoiceAuditHandler()


# ---- actions called by the API (a person acts; the bot then advances the run) ----
def resolve_task(session: Session, user: User | None, task_id: int, response: str, note: str | None) -> Run:
    from ...models import Task
    task = session.get(Task, task_id)
    if task is None:
        raise LookupError(f"Task {task_id} not found")
    permissions.require_task(user, task)
    if task.status != "open":
        raise ValueError("This step is already closed")
    note = (note or "").strip()
    run = session.get(Run, task.run_id)
    if task.kind == "manual_check":
        if response not in ("verified", "not_verified", "dispute"):
            raise ValueError("Response must be verified, not_verified or dispute")
        if response != "verified" and not note:
            raise ValueError("Please type a note explaining why")
        f = session.get(Finding, json.loads(task.payload_json)["finding_id"])
        f.status = "manually_verified" if response == "verified" else "manually_rejected"
        f.resolved_by, f.resolved_at, f.resolution_note = user.id, clock.now(), note or None
        ev = json.loads(f.evidence_json or "{}")
        ev["resolution"] = response
        f.evidence_json = json.dumps(ev)
        if f.status == "manually_rejected" and not f.amount_at_risk:
            line = session.get(InvoiceLine, f.line_id) if f.line_id else None
            f.amount_at_risk = line.amount if line else state.invoice_of(session, run).total
        session.add(f)
        audit.log(session, user.id, "finding_resolved", run.id, {"finding_id": f.id, "check": f.check,
                                                                "response": response, "note": note})
    elif task.kind in ("extra_step", "manual_entry"):
        if task.kind == "manual_entry":
            state.transition(session, run, "REJECTED", reason="entered by hand outside the platform")
    else:
        raise ValueError(f"A {task.kind.replace('_', ' ')} step is not resolved here; it closes through its own action")
    tasks.complete_task(session, task.id, by=user.id, source="user", note=note or response)
    handler.advance(session, run)
    return run
