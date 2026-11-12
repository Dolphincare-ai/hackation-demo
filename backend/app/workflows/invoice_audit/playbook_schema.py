"""The settings the invoice-audit playbook may hold. This model is the whitelist.

`extra="forbid"` is the guard: a key that is not declared here (disable the approval step, remove
the funds check, anything that moves money) cannot be written to the playbook, whoever asks.
Every number has a minimum and a maximum. All fields default to None so that "not set" falls
through to the next layer in core/settings.py.
"""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core import playbook

Role = Literal["owner", "administrator", "business_office_manager", "don", "cfo"]
Recipient = Literal["owner", "administrator", "business_office_manager", "don", "cfo",
                    "assignee_role", "backup_approver"]
CHECKS = ("price", "date", "delivery", "math", "duplicate", "bank_details")
LADDER_KINDS = ("manual_check", "extra_step", "approval", "funds_check", "payment")

# Things the chat agent must refuse even to propose. Nothing here exists in the schema below.
LOCKED = (
    "removing or skipping the approval step",
    "removing or skipping the funds check",
    "moving money or preparing a transfer",
    "approving, rejecting or resolving a task",
    "editing a finding",
    "approving a failed finding without a typed reason",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckSetting(_Strict):
    enabled: bool | None = None


class Checks(_Strict):
    price: CheckSetting | None = None
    date: CheckSetting | None = None
    delivery: CheckSetting | None = None
    math: CheckSetting | None = None
    duplicate: CheckSetting | None = None
    bank_details: CheckSetting | None = None


class TaskDefault(_Strict):
    due_h: float | None = Field(default=None, ge=0.25, le=720)


class TaskDefaults(_Strict):
    manual_entry: TaskDefault | None = None
    manual_check: TaskDefault | None = None
    extra_step: TaskDefault | None = None
    approval: TaskDefault | None = None
    funds_check: TaskDefault | None = None
    # `payment` is deliberately absent: its due date comes from the invoice due date.


class LadderStep(_Strict):
    after_h: float = Field(ge=0, le=720)
    action: Literal["remind", "alert"]
    to: list[Recipient] = Field(min_length=1, max_length=6)


class Ladders(_Strict):
    manual_check: list[LadderStep] | None = Field(default=None, max_length=5)
    extra_step: list[LadderStep] | None = Field(default=None, max_length=5)
    # approval and funds_check must keep at least one step: a wait must always escalate.
    approval: list[LadderStep] | None = Field(default=None, min_length=1, max_length=5)
    funds_check: list[LadderStep] | None = Field(default=None, min_length=1, max_length=5)
    payment: list[LadderStep] | None = Field(default=None, min_length=1, max_length=5)


class ManualCheckRoles(_Strict):
    delivery: Role | None = None
    price: Role | None = None
    date: Role | None = None


class ExtraStep(_Strict):
    """An optional extra task, run in parallel with the manual checks and before the approval."""
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    title: str = Field(min_length=3, max_length=120)
    role: Role
    due_h: float = Field(ge=0.25, le=720)


class InboxPoll(_Strict):
    mode: Literal["every_tick", "daily"] | None = None
    daily_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class _Common(_Strict):
    checks: Checks | None = None
    task_defaults: TaskDefaults | None = None
    ladders: Ladders | None = None
    manual_check_roles: ManualCheckRoles | None = None
    extra_steps: list[ExtraStep] | None = Field(default=None, max_length=5)

    @field_validator("extra_steps")
    @classmethod
    def _unique_keys(cls, v):
        if v and len({s.key for s in v}) != len(v):
            raise ValueError("extra step keys must be unique")
        return v


class VendorSettings(_Common):
    """Per-vendor overrides. The owner-only money limits are not allowed here."""


class InvoiceAuditSettings(_Common):
    inbox_poll: InboxPoll | None = None
    approval_owner_threshold: float | None = Field(default=None, ge=1000, le=1_000_000)
    reserve_min: float | None = Field(default=None, ge=0, le=1_000_000)
    vendors: dict[str, VendorSettings] | None = None

    @field_validator("vendors")
    @classmethod
    def _vendor_ids(cls, v):
        for k in v or {}:
            if not k.replace("_", "").isalnum():
                raise ValueError(f"bad vendor id {k!r}")
        return v


DEFAULT_PATH = Path(__file__).with_name("AGENT.md")


def register() -> None:
    playbook.register("invoice_audit", DEFAULT_PATH, InvoiceAuditSettings)


register()
