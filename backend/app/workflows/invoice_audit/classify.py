"""AI slot 1: classify an inbound email. Raises on failure; slots.py falls back to a keyword rule."""
from typing import Literal

from pydantic import BaseModel, Field

from ...ai.client import call_json
from ...schemas import Email


class Classification(BaseModel):
    kind: Literal["invoice", "statement", "question", "other"]
    vendor_hint: str | None = None
    confidence: float = Field(ge=0, le=1)


def classify_email(email: Email) -> Classification:
    payload = {"from": email.from_, "subject": email.subject, "body": email.body,
               "attachments": [{"filename": a.filename, "text": a.text} for a in email.attachments]}
    return call_json("classify", payload, Classification)
