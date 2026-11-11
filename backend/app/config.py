import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]  # repo root


def mock_world_dir() -> Path:
    return Path(os.environ.get("MOCK_WORLD", ROOT / "mock_world"))


def db_path() -> Path:
    return Path(os.environ.get("PLATFORM_DB", ROOT / "data" / "platform.db"))


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(Path(__file__).with_name("config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)
