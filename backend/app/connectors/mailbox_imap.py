"""Real mailbox over IMAP (read) and, only when REPLY_MODE=smtp, SMTP (reply).

Reads only unread mail and marks it read once the bot has taken it:
  * SEARCH UNSEEN, FETCH BODY.PEEK[], then STORE +FLAGS \\Seen (skipped when IMAP_MARK_READ=0,
    which also opens INBOX read-only). Nothing else is ever changed or deleted.
  * Dedupe by Message-ID in a small SQLite file next to the platform database, a second guard in
    case marking read fails or is switched off. (A separate file, not platform.db: the bot
    holds a write transaction there while it polls.)
  * PDF attachments are turned into text with pypdf. A scan with no text gives an empty string,
    and the invoice flow sends such a run to MANUAL_ENTRY.
Replies go to mock_world/mailbox/sent unless REPLY_MODE=smtp.
"""
import email as emaillib
import imaplib
import os
import smtplib
import sqlite3
from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from io import BytesIO

from ..config import data_dir
from ..core import clock
from ..schemas import Attachment, Email, Outgoing
from .base import ConnectorError
from .mock import MockMailbox


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(data)).pages).strip()
    except Exception:
        return ""


def parse_message(raw: bytes, mailbox_user: str) -> Email:
    msg = emaillib.message_from_bytes(raw, policy=policy.default)
    msg_id = (msg["Message-ID"] or "").strip()
    refs = (msg["References"] or "").split()
    body_part = msg.get_body(preferencelist=("plain", "html"))
    attachments = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        data = part.get_payload(decode=True) or b""
        if part.get_content_type() == "application/pdf" or name.lower().endswith(".pdf"):
            text = pdf_text(data)
        elif part.get_content_maintype() == "text":
            text = data.decode(part.get_content_charset() or "utf-8", errors="replace")
        else:
            continue
        attachments.append(Attachment(filename=name, text=text))
    try:
        received = parsedate_to_datetime(msg["Date"]).replace(tzinfo=None).isoformat()
    except Exception:
        received = clock.now().isoformat()
    return Email.model_validate({
        "id": msg_id.strip("<>") or f"noid-{hash(raw) & 0xFFFFFFFF:x}",
        "from": parseaddr(msg["From"] or "")[1],
        "to": mailbox_user,
        "subject": str(msg["Subject"] or ""),
        "received_at": received,
        "body": body_part.get_content() if body_part else "",
        "thread_ref": refs[0] if refs else msg_id,
        "attachments": attachments,
    })


class ImapMailbox(MockMailbox):
    mode = "imap"

    def __init__(self, host=None, user=None, password=None, port=993, root=None, seen_db=None):
        super().__init__(root)
        self.host = host or os.environ["IMAP_HOST"]
        self.user = user or os.environ["IMAP_USER"]
        self.password = password or os.environ["IMAP_PASSWORD"]
        self.port = int(os.environ.get("IMAP_PORT", port))
        self.seen_db = seen_db or (data_dir() / "imap_seen.db")
        self.max_age_days = int(os.environ.get("IMAP_MAX_AGE_DAYS", 30))
        self.mark_read =os.environ.get("IMAP_MARK_READ", "1") != "0"  # set 0 to leave mail unread (re-demo)

    @property
    def info(self) -> dict:
        return {"reply_mode": os.environ.get("REPLY_MODE", "mock"), "mailbox": self.user}

    # ---- dedupe store ----
    def _seen_conn(self) -> sqlite3.Connection:
        self.seen_db.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.seen_db)
        c.execute("CREATE TABLE IF NOT EXISTS seen (message_id TEXT PRIMARY KEY, at TEXT)")
        return c

    def forget_seen(self) -> None:
        with self._seen_conn() as c:
            c.execute("DELETE FROM seen")

    # ---- read ----
    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            m = imaplib.IMAP4_SSL(self.host, self.port, timeout=20)
            m.login(self.user, self.password)
            m.select("INBOX", readonly=not self.mark_read)  # writable only so we can set \Seen
            return m
        except (imaplib.IMAP4.error, OSError) as e:
            raise ConnectorError(f"IMAP login or connect failed: {e}") from e

    def _since(self) -> str:
        """IMAP date (DD-Mon-YYYY, English month) of the oldest mail we look at: IMAP_MAX_AGE_DAYS back (default 30)."""
        d = clock.now().date() - timedelta(days=self.max_age_days)
        months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        return f"{d.day:02d}-{months[d.month - 1]}-{d.year}"

    def poll(self) -> list[Email]:
        m = self._connect()
        out: list[Email] = []
        try:
            typ, data = m.uid("SEARCH", None, "UNSEEN", "SINCE", self._since())
            if typ != "OK":
                raise ConnectorError("IMAP search failed")
            with self._seen_conn() as db:
                for uid in (data[0] or b"").split():
                    typ, parts = m.uid("FETCH", uid, "(BODY.PEEK[])")
                    raw = next((p[1] for p in parts if isinstance(p, tuple)), None) if typ == "OK" else None
                    if raw is None:
                        continue
                    mail = parse_message(raw, self.user)
                    cur = db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (mail.id, clock.now().isoformat()))
                    if cur.rowcount:  # first time we see this Message-ID
                        out.append(mail)
                    if self.mark_read:  # taken by the bot: mark read (also for repeats, so they leave UNSEEN)
                        m.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        except imaplib.IMAP4.error as e:
            raise ConnectorError(f"IMAP error: {e}") from e
        finally:
            try:
                m.logout()
            except Exception:
                pass
        self.last_read = clock.now()
        return out

    # ---- reply ----
    def send(self, msg: Outgoing) -> None:
        if os.environ.get("REPLY_MODE", "mock") != "smtp":
            return super().send(msg)  # written to mock_world/mailbox/sent, nothing leaves the machine
        m = EmailMessage()
        m["From"], m["To"] = self.user, msg.to
        m["Subject"] = msg.subject if msg.subject.lower().startswith("re:") else f"Re: {msg.subject}"
        if msg.thread_ref:
            m["In-Reply-To"] = m["References"] = msg.thread_ref
        m.set_content(msg.body)
        host = os.environ.get("SMTP_HOST") or self.host.replace("imap", "smtp", 1)
        try:
            with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", 465)), timeout=20) as s:
                s.login(self.user, self.password)
                s.send_message(m)
        except (smtplib.SMTPException, OSError) as e:
            raise ConnectorError(f"SMTP send failed: {e}") from e
        super().send(msg)  # keep a local copy for the audit trail and the demo
