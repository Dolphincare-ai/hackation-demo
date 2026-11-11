"""Shared contract between the engine (A) and connectors / AI layer (B). Change only by agreement."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    filename: str
    text: str  # invoice content is plain text, no PDF parsing


class Email(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    from_: str = Field(alias="from")  # the JSON files use "from"
    to: str
    subject: str
    received_at: str
    body: str
    thread_ref: str
    attachments: list[Attachment] = []


class Outgoing(BaseModel):
    to: str
    subject: str
    body: str
    thread_ref: str | None = None


class RemitTo(BaseModel):
    bank: str
    account_last4: str
    routing_last4: str


class ExtractedLine(BaseModel):
    description: str
    item_key: str | None = None  # chosen from known contract keys, else null
    resident_id: str | None = None  # resident name mapped to census id, else null
    service_from: date
    service_to: date
    qty: float
    unit_price: float
    amount: float


class InvoiceExtract(BaseModel):
    vendor_id: str
    invoice_no: str
    invoice_date: date
    due_date: date
    period_from: date
    period_to: date
    total: float
    remit_to: RemitTo
    lines: list[ExtractedLine]
