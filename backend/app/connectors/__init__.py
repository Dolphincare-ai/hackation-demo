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
            name: {"mode": c.mode, "last_read": c.last_read.isoformat() if c.last_read else None}
            for name, c in vars(self).items()
        }


def get_connectors() -> Connectors:
    """Returns the mock implementations. Real systems plug in here."""
    return Connectors(MockMailbox(), MockVendors(), MockEHR(), MockBank())
