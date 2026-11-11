"""SQLModel tables, CLAUDE.md section 5. JSON columns are stored as text (`*_json`)."""
from datetime import date

from pydantic import NaiveDatetime

from sqlmodel import Field, SQLModel


# ---- generic tables, reused by every scenario ----
class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str
    source: str
    building_id: str
    payload_json: str = "{}"
    received_at: NaiveDatetime


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str
    state: str
    building_id: str
    title: str
    context_json: str = "{}"
    created_at: NaiveDatetime
    updated_at: NaiveDatetime
    closed_at: NaiveDatetime | None = None


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    kind: str
    title: str
    role: str
    assignee_id: str | None = None
    status: str = "open"  # open | done | cancelled
    created_at: NaiveDatetime
    due_at: NaiveDatetime
    escalation_level: int = 0
    last_escalated_at: NaiveDatetime | None = None
    payload_json: str = "{}"
    via: str = "email"  # email | teams | text | ehr_alert
    blocks_json: str = "[]"
    completed_at: NaiveDatetime | None = None
    completed_by: str | None = None
    completion_source: str | None = None  # user | system_observed


class Approval(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    task_id: int | None = None
    decision: str  # approve | reject
    decided_by: str
    decided_at: NaiveDatetime
    reason: str | None = None
    snapshot_json: str = "{}"


class Notification(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int | None = Field(default=None, index=True)
    channel: str  # email | teams | text
    to: str
    subject: str
    body: str
    thread_ref: str | None = None
    sent_at: NaiveDatetime


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    at: NaiveDatetime
    actor: str  # system | claude | <user_id>
    run_id: int | None = Field(default=None, index=True)
    action: str
    detail_json: str = "{}"


class User(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    role: str
    building_id: str


class KV(SQLModel, table=True):
    """Small key/value store for bot bookkeeping (e.g. last inbox poll)."""
    key: str = Field(primary_key=True)
    value: str


# ---- agent chat (generic, reused by every scenario) ----
class AgentProposal(SQLModel, table=True):
    __tablename__ = "agent_proposals"
    id: int | None = Field(default=None, primary_key=True)
    user_id: str  # whose chat proposed it; only this user's later message can confirm it
    chat_msg_id: int  # the user message in the turn that created it
    kind: str  # change | note | revert | restore
    run_type: str
    run_id: int | None = None  # the run "only this time" would apply to
    vendor_id: str | None = None  # the vendor "always" would apply to (None = all)
    changes_json: str = "[]"  # [{key, from, to}]
    payload_json: str = "{}"  # note text, or full playbook text for revert/restore
    rationale: str = ""
    status: str = "pending"  # pending | applied | cancelled
    scope: str | None = None  # once | always, set on confirm
    proposed_at: NaiveDatetime
    decided_by: str | None = None
    decided_at: NaiveDatetime | None = None


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    run_id: int | None = None
    role: str  # user | assistant
    content: str
    at: NaiveDatetime


# ---- invoice tables ----
class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    vendor_id: str
    invoice_no: str
    invoice_date: date
    due_date: date
    period_from: date
    period_to: date
    total: float
    remit_to_json: str = "{}"
    source_event_id: int | None = None
    payable_amount: float | None = None
    status: str = "received"


class InvoiceLine(SQLModel, table=True):
    __tablename__ = "invoice_lines"
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(index=True)
    description: str
    item_key: str | None = None
    resident_id: str | None = None
    service_from: date
    service_to: date
    qty: float
    unit_price: float
    amount: float
    decision: str | None = None  # approve | approve_at_contract | exclude


class Finding(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(index=True)
    line_id: int | None = None
    check: str  # price | date | delivery | math | duplicate | bank_details
    status: str  # verified | failed | unverified | manually_verified | manually_rejected
    expected: str | None = None
    actual: str | None = None
    amount_at_risk: float = 0.0
    message: str = ""
    evidence_json: str = "{}"  # exactly what was compared, so an approval can be reproduced
    resolved_by: str | None = None
    resolved_at: NaiveDatetime | None = None
    resolution_note: str | None = None


class Payment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(index=True)
    amount: float
    account_id: str
    expected_ref: str
    matched_txn_id: str | None = None
    matched_at: NaiveDatetime | None = None
    status: str = "pending"  # pending | matched | mismatch
