"""Cache of AI answers keyed by a hash of the input, in data/ai_cache/. Lets the demo run offline."""
import hashlib
import json

from ..config import data_dir


def key(name: str, system: str, payload) -> str:
    raw = json.dumps({"n": name, "s": system, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _path(name: str, k: str):
    return data_dir() / "ai_cache" / f"{name}_{k}.json"


def get(name: str, k: str) -> str | None:
    p = _path(name, k)
    return json.loads(p.read_text(encoding="utf-8"))["output"] if p.exists() else None


def put(name: str, k: str, output: str) -> None:
    p = _path(name, k)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"output": output}), encoding="utf-8")
