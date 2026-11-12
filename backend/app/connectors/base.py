"""Connector interfaces (CLAUDE.md section 9). Real systems plug in behind these."""
from typing import Protocol

from ..schemas import Email, Outgoing


class ConnectorError(Exception):
    """A connector could not reach its system (network, login). The bot logs it and carries on."""


class MailboxConnector(Protocol):
    def poll(self) -> list[Email]: ...
    def send(self, msg: Outgoing) -> None: ...
