"""Shared pieces for the six checks. Each check is a pure function (invoice, line, ctx) -> [Finding].

`line` is None for invoice-level findings. Findings are returned unsaved; flow.py stores them.
`evidence` holds exactly what was compared (contract row, delivery rows, census row, vendor master)
so an approval can be reproduced later, plus a short `source` string the packet shows.
"""
import json
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session

from ....models import Finding, Invoice, InvoiceLine

CHECK_NAMES = ("price", "date", "delivery", "math", "duplicate", "bank_details")
TOL = 0.005


@dataclass
class CheckContext:
    session: Session
    vendors: object  # VendorConnector
    ehr: object  # EHRConnector
    disabled: dict[str, str] = field(default_factory=dict)  # check -> where the switch-off came from


def money(x: float) -> str:
    return f"${x:,.2f}"


def finding(invoice: Invoice, line: InvoiceLine | None, check: str, status: str, message: str, *,
            expected=None, actual=None, at_risk: float = 0.0, evidence: dict | None = None,
            source: str = "") -> Finding:
    ev = dict(evidence or {})
    ev["source"] = source
    return Finding(
        invoice_id=invoice.id, line_id=line.id if line else None, check=check, status=status,
        expected=None if expected is None else str(expected), actual=None if actual is None else str(actual),
        amount_at_risk=round(at_risk, 2), message=message, evidence_json=json.dumps(ev, default=str),
    )


def days(a: date, b: date) -> int:
    """Inclusive day count."""
    return (b - a).days + 1
