"""Connector interfaces (CLAUDE.md section 9). Read-only. Real systems plug in by implementing these."""
from datetime import date, datetime
from typing import Protocol

from ..schemas import Email, Outgoing


class MailboxConnector(Protocol):
    def poll(self) -> list[Email]: ...  # new emails only, marks them as seen
    def send(self, msg: Outgoing) -> None: ...


class VendorConnector(Protocol):
    def vendor_master(self, vendor_id: str) -> dict | None: ...
    def contract_rate(self, vendor_id: str, item_key: str, on_date: date) -> dict | None: ...  # the contract row
    def deliveries(self, vendor_id: str, item_key: str, date_from: date, date_to: date) -> list[dict]: ...


class EHRConnector(Protocol):
    def resident(self, resident_id: str) -> dict | None: ...  # admit_date, discharge_date, building_id


class BankConnector(Protocol):
    def available_balance(self, account_id: str) -> float | None: ...
    def transactions(self, since: datetime | date | None) -> list[dict]: ...
