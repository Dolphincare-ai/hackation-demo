"""AI layer: the narrow Claude/LLM slots. Text slots live here; classify and extract live in
workflows/invoice_audit/{classify,extract}.py and call client.call_json."""
from .client import call_text


def summarize_packet(packet: dict) -> str:
    return call_text("summarize_packet", packet)


def draft_reply(payment: dict, invoice: dict, thread: dict) -> str:
    return call_text("draft_reply", {"payment": payment, "invoice": invoice, "thread": thread})


def draft_dispute(findings: list[dict]) -> str:
    return call_text("draft_dispute", {"disputed_lines": findings})
