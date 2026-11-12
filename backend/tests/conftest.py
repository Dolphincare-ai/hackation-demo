import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own database, mock world and clock."""
    monkeypatch.setenv("PLATFORM_DB", str(tmp_path / "platform.db"))
    monkeypatch.setenv("MOCK_WORLD", str(tmp_path / "mock_world"))
    # a developer's .env must never leak into tests: no real inbox, no real replies
    monkeypatch.setenv("MAILBOX_MODE", "mock")
    monkeypatch.setenv("REPLY_MODE", "mock")
    for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_BUILDING", "IMAP_MARK_READ", "IMAP_MAX_AGE_DAYS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AI_MODE", "cache")  # tests never call AWS or OpenAI; slots fall back (B's AI tests inject a stub)
    from app.core import clock
    from app.db import reset_db
    from seed import build_mock_world

    build_mock_world(tmp_path / "mock_world")
    reset_db()
    clock.reset()
    yield
    clock.reset()


@pytest.fixture
def session():
    from app.db import get_session

    with get_session() as s:
        yield s
