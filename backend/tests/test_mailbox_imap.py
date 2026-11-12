"""IMAP connector against a stubbed server: UNSEEN filtering, BODY.PEEK, dedupe, PDF text, replies."""
import imaplib
import json
from email.message import EmailMessage

import pytest
from sqlmodel import select

from app.connectors import get_connectors
from app.connectors.mailbox_imap import ImapMailbox
from app.core import bot
from app.models import AuditLog, Run
from make_invoice import build


class FakeServer:
    """Class-level state so every IMAP4_SSL() the connector opens sees the same mailbox."""
    messages: dict[bytes, dict] = {}
    commands: list = []
    expect_since = None  # tests that freeze the clock set the exact date they expect
    max_age = 30

    def __init__(self, host, port=993, timeout=None):
        pass

    def login(self, u, p):
        FakeServer.commands.append(("LOGIN", u))

    def select(self, box, readonly=False):
        FakeServer.commands.append(("SELECT", box, readonly))
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        FakeServer.commands.append((cmd, *args))
        if cmd == "SEARCH":
            assert args[1:3] == ("UNSEEN", "SINCE")
            assert FakeServer.expect_since is None or args[3] == FakeServer.expect_since
            ids = b" ".join(u for u, m in FakeServer.messages.items()
                            if not m["seen"] and m.get("age_days", 0) <= FakeServer.max_age)
            return "OK", [ids]
        if cmd == "FETCH":
            uid, what = args
            assert what == "(BODY.PEEK[])"  # plain BODY[] would set \Seen
            return "OK", [(b"1 (UID 1 BODY[] {1}", FakeServer.messages[uid]["raw"]), b")"]
        if cmd == "STORE":
            uid, op, flags = args
            assert (op, flags) == ("+FLAGS", "(\\Seen)")
            FakeServer.messages[uid]["seen"] = True
            return "OK", [b""]
        raise AssertionError(cmd)

    def logout(self):
        pass


def mail(msg_id, subject="Harbor Pharmacy invoice #4471 (October)", pdf: bytes | None = None, refs=None):
    m = EmailMessage()
    m["From"], m["To"] = "someone@example.com", "riverside.ap@example.com"
    m["Subject"], m["Message-ID"], m["Date"] = subject, msg_id, "Mon, 02 Nov 2026 09:00:00 +0000"
    if refs:
        m["References"] = refs
    m.set_content("Invoice attached.")
    if pdf is not None:
        m.add_attachment(pdf, maintype="application", subtype="pdf", filename="invoice.pdf")
    return m.as_bytes()


@pytest.fixture
def server(monkeypatch):
    FakeServer.messages, FakeServer.commands = {}, []
    FakeServer.expect_since, FakeServer.max_age = None, 30
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeServer)
    for k, v in dict(MAILBOX_MODE="imap", IMAP_HOST="imap.example.com", IMAP_USER="riverside.ap@example.com",
                     IMAP_PASSWORD="x", IMAP_BUILDING="riverside").items():
        monkeypatch.setenv(k, v)
    return FakeServer


def add(server, uid, raw, seen=False):
    server.messages[uid] = {"raw": raw, "seen": seen}


def test_only_unseen_mail_is_returned_and_then_marked_read(server, tmp_path):
    add(server, b"1", mail("<a@x>", pdf=build("default", tmp_path / "o").read_bytes()))
    add(server, b"2", mail("<b@x>"), seen=True)
    got = get_connectors().mailbox.poll()
    assert [e.id for e in got] == ["a@x"]
    assert server.messages[b"1"]["seen"] is True  # taken by the bot, so it is read now
    assert [c[1] for c in server.commands if c[0] == "STORE"] == [b"1"]  # the already-read mail is untouched
    assert not any(c[0] in ("COPY", "EXPUNGE") for c in server.commands)
    assert get_connectors().mailbox.poll() == []  # nothing unread left


def test_mark_read_off_keeps_mail_unread_and_selects_read_only(server, monkeypatch):
    monkeypatch.setenv("IMAP_MARK_READ", "0")
    add(server, b"1", mail("<a@x>"))
    assert len(get_connectors().mailbox.poll()) == 1
    assert server.messages[b"1"]["seen"] is False
    assert ("SELECT", "INBOX", True) in server.commands
    assert not any(c[0] == "STORE" for c in server.commands)
    assert get_connectors().mailbox.poll() == []  # still deduped by Message-ID


def test_pdf_text_reaches_attachments(server, tmp_path):
    add(server, b"1", mail("<a@x>", pdf=build("default", tmp_path / "o").read_bytes()))
    e = get_connectors().mailbox.poll()[0]
    text = e.attachments[0].text
    assert "4471" in text and "TOTAL DUE" in text and "Enoxaparin 40 mg" in text and "4,010.00" in text
    assert e.to == "riverside.ap@example.com"


def test_changed_bank_variant_has_other_account(tmp_path):
    from app.connectors.mailbox_imap import pdf_text
    t = pdf_text(build("changed_bank", tmp_path).read_bytes())
    assert "4480" in t and "7733" in t and "banking details have changed" in t


def test_dedupe_by_message_id_when_server_still_lists_it_unread(server):
    add(server, b"1", mail("<a@x>"))
    assert len(get_connectors().mailbox.poll()) == 1
    server.messages[b"1"]["seen"] = False  # e.g. someone marked it unread again
    assert get_connectors().mailbox.poll() == []


def test_thread_ref_uses_references_root_else_message_id(server):
    add(server, b"1", mail("<a@x>"))
    add(server, b"2", mail("<b@x>", refs="<root@x> <mid@x>"))
    refs = {e.id: e.thread_ref for e in get_connectors().mailbox.poll()}
    assert refs == {"a@x": "<a@x>", "b@x": "<root@x>"}


def test_login_failure_is_logged_once_and_does_not_crash_tick(server, session, monkeypatch):
    def boom(self, u, p):
        raise imaplib.IMAP4.error("bad credentials")
    monkeypatch.setattr(FakeServer, "login", boom)
    bot.tick(session, force_poll=True)
    bot.tick(session, force_poll=True)
    rows = session.exec(select(AuditLog).where(AuditLog.action == "inbox_error")).all()
    assert len(rows) == 1


def test_empty_pdf_text_goes_to_manual_entry(server, session, tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(p)); c.showPage(); c.save()
    add(server, b"1", mail("<scan@x>", pdf=p.read_bytes()))
    bot.tick(session, force_poll=True)
    run = session.exec(select(Run)).one()
    assert run.state == "MANUAL_ENTRY"


def test_reply_stays_mock_unless_smtp(server, monkeypatch):
    from app.config import mock_world_dir
    from app.schemas import Outgoing
    sent = []
    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **k: sent.append(a) or pytest.fail("smtp used"))
    box = get_connectors().mailbox
    box.send(Outgoing(to="a@b.c", subject="Re: x", body="paid", thread_ref="<a@x>"))
    assert len(list((mock_world_dir() / "mailbox" / "sent").glob("*.json"))) == 1 and not sent


def test_smtp_reply_sets_threading_headers(server, monkeypatch):
    import smtplib
    from app.schemas import Outgoing
    sent = []

    class S:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, u, p): pass
        def send_message(self, m): sent.append(m)
    monkeypatch.setattr(smtplib, "SMTP_SSL", S)
    monkeypatch.setenv("REPLY_MODE", "smtp")
    get_connectors().mailbox.send(Outgoing(to="a@b.c", subject="Harbor invoice", body="paid", thread_ref="<a@x>"))
    assert sent[0]["In-Reply-To"] == "<a@x>" and sent[0]["References"] == "<a@x>" and sent[0]["Subject"] == "Re: Harbor invoice"


def test_health_reports_imap_mode(server):
    from fastapi.testclient import TestClient
    from app.main import app
    h = TestClient(app).get("/connectors/health").json()
    assert h["mailbox"]["mode"] == "imap" and h["bank"]["mode"] == "mock"


def test_only_the_last_30_days_are_searched(server, monkeypatch):
    from datetime import datetime
    from app.core import clock
    clock.freeze(datetime(2026, 11, 11, 9, 0))
    server.expect_since = "12-Oct-2026"
    add(server, b"1", mail("<new@x>"))
    server.messages[b"1"]["age_days"] = 5
    add(server, b"2", mail("<old@x>"))
    server.messages[b"2"]["age_days"] = 45
    assert [e.id for e in get_connectors().mailbox.poll()] == ["new@x"]
    assert server.messages[b"2"]["seen"] is False  # too old: not read, not marked


def test_max_age_is_configurable(server, monkeypatch):
    from datetime import datetime
    from app.core import clock
    clock.freeze(datetime(2026, 11, 11, 9, 0))
    monkeypatch.setenv("IMAP_MAX_AGE_DAYS", "7")
    server.expect_since, server.max_age = "04-Nov-2026", 7
    add(server, b"1", mail("<a@x>"))
    assert len(get_connectors().mailbox.poll()) == 1
