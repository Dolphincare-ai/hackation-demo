import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # repo root
load_dotenv(ROOT / ".env")


def mock_world_dir() -> Path:
    return Path(os.environ.get("MOCK_WORLD", ROOT / "mock_world"))


def db_path() -> Path:
    return Path(os.environ.get("PLATFORM_DB", ROOT / "data" / "platform.db"))


def data_dir() -> Path:
    """Platform data lives next to the database (playbooks, AI cache)."""
    return db_path().parent


def mailbox_buildings() -> dict:
    """Mailbox address -> building. The real IMAP mailbox joins via IMAP_USER and IMAP_BUILDING."""
    m = dict(get_config()["mailbox_buildings"])
    if os.environ.get("IMAP_USER") and os.environ.get("IMAP_BUILDING"):
        m[os.environ["IMAP_USER"]] = os.environ["IMAP_BUILDING"]
    return m


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(Path(__file__).with_name("config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)
