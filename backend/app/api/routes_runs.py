import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from ..core import tasks as task_engine
from ..models import Approval, AuditLog, Invoice, Run, Task
from ..workflows import registry
from ..workflows.invoice_audit import approval as approval_mod
from ..workflows.invoice_audit import packet as packet_mod
from ..workflows.invoice_audit import state
from .deps import acting_user, session_dep, x_user
from .serialize import finding_out, j, task_out

router = APIRouter()


def _risk(findings) -> float:
    return round(sum(f.amount_at_risk for f in findings if f.status in ("failed", "manually_rejected")), 2)


@router.get("/runs")
def list_runs(session=Depends(session_dep)):
    out = []
    for run in session.exec(select(Run).order_by(Run.updated_at.desc(), Run.id.desc())).all():
        inv = session.exec(select(Invoice).where(Invoice.run_id == run.id)).first()
        open_t = [t for t in session.exec(select(Task).where(Task.run_id == run.id, Task.status == "open"))]
        c = j(run.context_json, {})
        out.append({"id": run.id, "type": run.type, "state": run.state, "building_id": run.building_id,
                    "title": run.title, "vendor": c.get("vendor_name"), "invoice_no": inv.invoice_no if inv else None,
                    "total": inv.total if inv else None, "payable": inv.payable_amount if inv else None,
                    "at_risk": _risk(state.findings_of(session, inv)) if inv else 0.0,
                    "open_tasks": len(open_t), "late_tasks": sum(task_engine.is_late(t) for t in open_t),
                    "updated_at": run.updated_at})
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: int, session=Depends(session_dep)):
    run = session.get(Run, run_id)
    if run is None:
        raise LookupError(f"Run {run_id} not found")
    inv = state.invoice_of(session, run)
    appr = session.exec(select(Approval).where(Approval.run_id == run.id).order_by(Approval.id.desc())).first()
    pay = state.payment_of(session, inv) if inv else None
    c = j(run.context_json, {})
    invoice = None
    if inv:
        invoice = {**inv.model_dump(), "remit_to": j(inv.remit_to_json, {}),
                   "lines": [l.model_dump() for l in state.lines_of(session, inv)]}
        invoice.pop("remit_to_json")
    return {
        "run": {**run.model_dump(exclude={"context_json"}), "context": {k: v for k, v in c.items() if k != "email"}},
        "invoice": invoice,
        "findings": [finding_out(f) for f in state.findings_of(session, inv)] if inv else [],
        "tasks": [task_out(t) for t in session.exec(select(Task).where(Task.run_id == run.id).order_by(Task.id))],
        "approval": ({**appr.model_dump(exclude={"snapshot_json"}), "snapshot": j(appr.snapshot_json, {})} if appr else None),
        "payment": pay.model_dump() if pay else None,
        "packet": packet_mod.build(session, inv, c.get("packet_summary", "")) if inv else None,
        "timeline": [{**a.model_dump(exclude={"detail_json"}), "detail": j(a.detail_json, {})}
                     for a in session.exec(select(AuditLog).where(AuditLog.run_id == run.id).order_by(AuditLog.id))],
    }


class LineDecision(BaseModel):
    line_id: int
    decision: str


class ApprovalBody(BaseModel):
    user_id: str | None = None
    decision: str
    reason: str | None = None
    lines: list[LineDecision] = []


@router.post("/runs/{run_id}/approval")
def post_approval(run_id: int, body: ApprovalBody, session=Depends(session_dep), x_user_id=Depends(x_user)):
    run = session.get(Run, run_id)
    if run is None:
        raise LookupError(f"Run {run_id} not found")
    user = acting_user(session, body.user_id, x_user_id)
    try:
        approval_mod.decide(session, run, user, body.decision, body.reason, [l.model_dump() for l in body.lines])
        registry.get(run.type).advance(session, run)  # funds check right away, no waiting for the tick
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_run(run_id, session)
