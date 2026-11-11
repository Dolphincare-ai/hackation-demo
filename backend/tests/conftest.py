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
