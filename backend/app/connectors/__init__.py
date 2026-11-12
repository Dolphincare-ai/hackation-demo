import os
from dataclasses import dataclass

from .mock import MockBank, MockEHR, MockMailbox, MockVendors


@dataclass
class Connectors:
    mailbox: MockMailbox
    vendors: MockVendors
    ehr: MockEHR
    bank: MockBank

    def health(self) -> dict:
        return {
            name: {"mode": c.mode, "last_read": c.last_read.isoformat() if c.last_read else None,
                   **getattr(c, "info", {})}
            for name, c in vars(self).items()
        }


_imap = None


def _mailbox():
    """MAILBOX_MODE=mock (default) or imap. The IMAP instance is kept so health shows its last read."""
    global _imap
    if os.environ.get("MAILBOX_MODE", "mock") != "imap":
        return MockMailbox()
    from .mailbox_imap import ImapMailbox
    key = (os.environ.get("IMAP_HOST"), os.environ.get("IMAP_USER"), os.environ.get("PLATFORM_DB"), os.environ.get("MOCK_WORLD"))
    if _imap is None or _imap[0] != key:
        _imap = (key, ImapMailbox())
    return _imap[1]


def get_connectors() -> Connectors:
    """Mock implementations, except the mailbox when MAILBOX_MODE=imap. Real systems plug in here."""
    return Connectors(_mailbox(), MockVendors(), MockEHR(), MockBank())
