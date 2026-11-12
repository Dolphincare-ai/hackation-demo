"""The four narrow places Claude is used (CLAUDE.md section 10), with offline fallbacks.

Each slot first tries Developer B's AI layer (`classify.py`, `extract.py`, and `app/ai`). If that is
missing, unavailable (AI_MODE=cache with no cached answer) or returns invalid data, the slot falls back
to plain code: a regex reader for the synthetic invoice text and fixed text templates. Every slot returns
`(value, via)` where via is "ai" or "fallback", so flow.py can write it to the audit log.

Expected AI-layer interface (TODO(B), agree before changing):
  classify.classify_email(email: Email) -> obj or dict with `kind` in invoice|statement|question|other
  extract.extract_invoice(email: Email) -> InvoiceExtract
  app.ai.summarize_packet(packet: dict) -> str
  app.ai.draft_reply(payment: dict, invoice: dict, thread: dict) -> str
  app.ai.draft_dispute(findings: list[dict]) -> str
"""
import importlib
import re
from datetime import date

from ...connectors import get_connectors
from ...schemas import Email, InvoiceExtract


def _b(module: str, fn: str):
    try:
        return getattr(importlib.import_module(module, package=__package__), fn, None)
    except Exception:
        return None


def _try(module: str, fn: str, *args):
    f = _b(module, fn)
    if f is None:
        return None, False
    try:
        return f(*args), True
    except Exception:
        return None, False


# ---- 1. classify ----
def classify_email(email: Email) -> tuple[str, str]:
    out, ok = _try(".classify", "classify_email", email)
    if ok and out is not None:
        kind = out.get("kind") if isinstance(out, dict) else getattr(out, "kind", None)
        if kind in ("invoice", "statement", "question", "other"):
            return kind, "ai"
    text = (email.subject + " " + " ".join(a.text for a in email.attachments)).lower()
    return ("invoice" if "invoice" in text and email.attachments else "other"), "fallback"


# ---- 2. extract ----
def extract_invoice(email: Email) -> tuple[InvoiceExtract | None, str]:
    out, ok = _try(".extract", "extract_invoice", email)
    if ok and out is not None:
        try:
            return InvoiceExtract.model_validate(out if isinstance(out, dict) else out.model_dump()), "ai"
        except Exception:
            pass
    try:
        return _regex_extract(email), "fallback"
    except Exception:
        return None, "fallback"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _regex_extract(email: Email) -> InvoiceExtract:
    text = "\n".join(a.text for a in email.attachments) or email.body
    conns = get_connectors()
    masters = conns.vendors._load("vendors/vendor_master.json")  # fallback only: find vendor by sender domain
    domain = email.from_.split("@")[-1].lower()
    vendor = next(v for v in masters if v["email_domain"].lower() == domain)

    def grab(pat):
        m = re.search(pat, text, re.I)
        if not m:
            raise ValueError(pat)
        return m

    inv_no = grab(r"invoice\s*#\s*(\S+)").group(1)
    inv_date = date.fromisoformat(grab(r"invoice date:\s*(\d{4}-\d\d-\d\d)").group(1))
    due = date.fromisoformat(grab(r"due date:\s*(\d{4}-\d\d-\d\d)").group(1))
    p = grab(r"service period:\s*(\d{4}-\d\d-\d\d)\s*to\s*(\d{4}-\d\d-\d\d)")
    p_from, p_to = date.fromisoformat(p.group(1)), date.fromisoformat(p.group(2))
    total = _num(grab(r"total due:\s*\$\s*([\d,.]+)").group(1))
    r = grab(r"remit to:\s*(.+?),\s*account ending\s*(\w+),\s*routing ending\s*(\w+)")
    keys = set(conns.vendors.contract_keys(vendor["vendor_id"]))

    lines = []
    for m in re.finditer(r"^\s*(.+?)\s+qty\s+([\d.,]+)\s+x\s+\$\s*([\d,.]+)\s*=\s*\$\s*([\d,.]+)\s*$", text, re.M):
        desc = m.group(1).strip()
        s_from, s_to, resident_id = p_from, p_to, None
        rm = re.search(r"-\s*(.+?),\s*(\d\d)/(\d\d)\s*to\s*(\d\d)/(\d\d)", desc)
        if rm:
            s_from = date(p_from.year, int(rm.group(2)), int(rm.group(3)))
            s_to = date(p_from.year, int(rm.group(4)), int(rm.group(5)))
            res = conns.ehr.find_by_name(rm.group(1))
            resident_id = res["resident_id"] if res else None
        words = re.match(r"([A-Za-z]+)\s+(\d+)", desc)
        key = f"{words.group(1).lower()}_{words.group(2)}" if words else None
        lines.append({"description": desc, "item_key": key if key in keys else None, "resident_id": resident_id,
                      "service_from": s_from, "service_to": s_to, "qty": _num(m.group(2)),
                      "unit_price": _num(m.group(3)), "amount": _num(m.group(4))})
    if not lines:
        raise ValueError("no lines")
    return InvoiceExtract(vendor_id=vendor["vendor_id"], invoice_no=inv_no, invoice_date=inv_date, due_date=due,
                          period_from=p_from, period_to=p_to, total=total,
                          remit_to={"bank": r.group(1).strip(), "account_last4": r.group(2), "routing_last4": r.group(3)},
                          lines=lines)


# ---- 3. summarize ----
def summarize_packet(packet: dict) -> tuple[str, str]:
    out, ok = _try("...ai", "summarize_packet", packet)
    if ok and isinstance(out, str) and out.strip():
        return out.strip(), "ai"
    t = packet["totals"]
    parts = [f"Invoice total ${t['billed']:,.2f}. {len(packet['verified'])} checks verified automatically"
             f" (${t['verified']:,.2f} of lines fully verified)."]
    if packet["failed"]:
        parts.append(f"{len(packet['failed'])} check(s) failed with ${t['at_risk']:,.2f} at risk.")
    if packet["unverified"]:
        parts.append(f"{len(packet['unverified'])} check(s) could not be verified.")
    if packet.get("manually_verified"):
        parts.append(f"{len(packet['manually_verified'])} check(s) were verified by hand.")
    if packet.get("skipped"):
        parts.append(f"{len(packet['skipped'])} check(s) were not run by request.")
    return " ".join(parts), "fallback"


# ---- 4. drafts ----
def draft_reply(payment: dict, invoice: dict, thread: dict, disputed: list[dict]) -> tuple[str, str]:
    out, ok = _try("...ai", "draft_reply", payment, invoice, thread)
    if ok and isinstance(out, str) and out.strip():
        body, via = out.strip(), "ai"
    else:
        body = (f"Hello,\n\nWe have sent payment of ${payment['amount']:,.2f} for invoice #{invoice['invoice_no']} "
                f"(reference {payment['expected_ref']}).")
        via = "fallback"
    if disputed:
        d, _ = draft_dispute(disputed)
        body += "\n\n" + d
    return body + ("\n\nThank you,\nAccounts Payable" if via == "fallback" else ""), via


def draft_dispute(findings: list[dict]) -> tuple[str, str]:
    out, ok = _try("...ai", "draft_dispute", findings)
    if ok and isinstance(out, str) and out.strip():
        return out.strip(), "ai"
    rows = "\n".join(f"- {f['description']}: billed ${f['billed']:,.2f}, paid ${f['payable']:,.2f}. {f['reason']}"
                     for f in findings)
    return "The following lines were disputed and are not included in this payment:\n" + rows, "fallback"
