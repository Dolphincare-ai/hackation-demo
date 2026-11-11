"""Mock connectors: read plain files in mock_world/. Platform state never goes here (SQLite only)."""
import json
from datetime import date, datetime
from pathlib import Path

from ..config import mock_world_dir
from ..core import clock
from ..schemas import Email, Outgoing


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class _Base:
    mode = "mock"

    def __init__(self, root: Path | None = None):
        self.root = root or mock_world_dir()
        self.last_read: datetime | None = None

    def _load(self, rel: str, default=None):
        self.last_read = clock.now()
        return _read(self.root / rel, [] if default is None else default)


class MockMailbox(_Base):
    def poll(self) -> list[Email]:
        inbox = self.root / "mailbox" / "inbox"
        seen_file = self.root / "mailbox" / "seen.json"
        seen = set(_read(seen_file, []))
        self.last_read = clock.now()
        new = []
        for f in sorted(inbox.glob("*.json")) if inbox.exists() else []:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data["id"] not in seen:
                new.append(Email.model_validate(data))
                seen.add(data["id"])
        _write(seen_file, sorted(seen))
        return new

    def send(self, msg: Outgoing) -> None:
        sent = self.root / "mailbox" / "sent"
        n = len(list(sent.glob("*.json"))) + 1 if sent.exists() else 1
        _write(sent / f"{n:04d}.json", {**msg.model_dump(), "sent_at": clock.now().isoformat()})

    # demo helpers (not part of the read-only interface)
    def drop_template(self, template: str) -> str:
        data = _read(self.root / "mailbox" / "templates" / f"{template}.json", None)
        if data is None:
            raise LookupError(f"Unknown email template {template!r}")
        n = len(list((self.root / "mailbox" / "inbox").glob("*.json"))) + 1
        data["id"] = f"{data['id']}-{n}"
        data["received_at"] = clock.now().isoformat()
        _write(self.root / "mailbox" / "inbox" / f"{data['id']}.json", data)
        return data["id"]


class MockVendors(_Base):
    def vendor_master(self, vendor_id):
        return next((v for v in self._load("vendors/vendor_master.json") if v["vendor_id"] == vendor_id), None)

    def contract_rate(self, vendor_id, item_key, on_date: date):
        d = on_date.isoformat()
        for c in self._load("vendors/contracts.json"):
            if c["vendor_id"] == vendor_id and c["item_key"] == item_key and c["valid_from"] <= d <= c["valid_to"]:
                return c
        return None

    def deliveries(self, vendor_id, item_key, date_from: date, date_to: date):
        a, b = date_from.isoformat(), date_to.isoformat()
        return [
            r for r in self._load("vendors/deliveries.json")
            if r["vendor_id"] == vendor_id and r["item_key"] == item_key and a <= r["date"] <= b
        ]

    def contract_keys(self, vendor_id: str) -> list[str]:
        return sorted({c["item_key"] for c in self._load("vendors/contracts.json") if c["vendor_id"] == vendor_id})


class MockEHR(_Base):
    def resident(self, resident_id):
        return next((r for r in self._load("ehr/census.json") if r["resident_id"] == resident_id), None)

    def find_by_name(self, name: str, building_id: str | None = None) -> dict | None:
        for r in self._load("ehr/census.json"):
            if r["name"].lower() == name.lower() and (building_id is None or r["building_id"] == building_id):
                return r
        return None


class MockBank(_Base):
    def available_balance(self, account_id):
        acct = next((a for a in self._load("bank/accounts.json") if a["account_id"] == account_id), None)
        return acct["balance"] if acct else None

    def transactions(self, since=None):
        txns = self._load("bank/transactions.json")
        if since is None:
            return txns
        s = since.isoformat()[:10]
        return [t for t in txns if t["date"] >= s]

    # demo helpers (the "bank" is theirs; the platform only reads)
    def post_transaction(self, account_id: str, payee: str, amount: float, reference: str) -> dict:
        path = self.root / "bank" / "transactions.json"
        txns = _read(path, [])
        txn = {"txn_id": f"t_{len(txns) + 1:04d}", "account_id": account_id, "date": clock.now().date().isoformat(),
               "payee": payee, "amount": amount, "reference": reference}
        _write(path, txns + [txn])
        return txn

    def set_balance(self, account_id: str, balance: float) -> None:
        path = self.root / "bank" / "accounts.json"
        accts = _read(path, [])
        for a in accts:
            if a["account_id"] == account_id:
                a["balance"] = balance
        _write(path, accts)
