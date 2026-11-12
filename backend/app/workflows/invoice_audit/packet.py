"""The approval packet (CLAUDE.md section 11): what was verified, what failed, what is unknown.
Built from the database by plain code. Claude only writes the `summary` sentence."""
import json

from sqlmodel import Session

from ...models import Invoice
from . import state

LINE_CHECKS = {"price", "date", "delivery", "math", "duplicate"}


def build(session: Session, invoice: Invoice, summary: str = "") -> dict:
    lines = {l.id: l for l in state.lines_of(session, invoice)}
    findings = state.findings_of(session, invoice)
    p: dict = {"summary": summary, "verified": [], "manually_verified": [], "failed": [], "unverified": [],
               "skipped": [], "disputed": [], "totals": {}}
    ok_lines = set(lines)
    skipped_line_checks = any(f.status == "skipped" and f.check in LINE_CHECKS for f in findings)
    risk = 0.0
    for f in findings:
        ev = json.loads(f.evidence_json or "{}")
        if f.status == "verified":
            p["verified"].append({"line_id": f.line_id, "check": f.check, "message": f.message, "source": ev.get("source", "")})
        elif f.status == "manually_verified":
            p["manually_verified"].append({"line_id": f.line_id, "check": f.check, "by": f.resolved_by,
                                           "at": f.resolved_at.isoformat() if f.resolved_at else None,
                                           "note": f.resolution_note})
        elif f.status in ("failed", "manually_rejected"):
            p["failed"].append({"line_id": f.line_id, "check": f.check, "message": f.message,
                                "amount_at_risk": f.amount_at_risk, "manually_rejected": f.status == "manually_rejected",
                                "note": f.resolution_note})
            risk += f.amount_at_risk
            ok_lines.discard(f.line_id)
        elif f.status == "unverified":
            p["unverified"].append({"line_id": f.line_id, "check": f.check, "reason": f.message})
            ok_lines.discard(f.line_id)
        elif f.status == "skipped":
            p["skipped"].append({"check": f.check, "message": f.message})
    if skipped_line_checks:
        ok_lines.clear()
    from .approval import line_payable
    for l in lines.values():
        if l.decision in ("exclude", "approve_at_contract"):
            bad = [x["message"] for x in p["failed"] if x["line_id"] == l.id] or ["Excluded by the approver."]
            p["disputed"].append({"line_id": l.id, "description": l.description, "billed": l.amount,
                                  "payable": line_payable(invoice, l), "decision": l.decision, "reason": " ".join(bad)})
    p["totals"] = {"billed": invoice.total, "verified": round(sum(lines[i].amount for i in ok_lines), 2),
                   "at_risk": round(min(risk, invoice.total), 2)}
    return p
