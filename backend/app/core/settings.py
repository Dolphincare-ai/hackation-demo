"""Layered settings. Generic, no invoice logic.

Order (first layer with a value wins):
  1. this run only      runs.context_json["overrides"]
  2. playbook, vendor   live playbook `vendors.<vendor_id>`
  3. playbook, general  live playbook top level
  4. engine default     config.yaml
"""
import copy
import json

from ..config import get_config
from ..models import Run
from . import playbook

_MISSING = object()


def get_path(d: dict, key: str, default=_MISSING):
    cur = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(d: dict, key: str, value) -> None:
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def run_context(run: Run | None) -> dict:
    return json.loads(run.context_json) if run is not None else {}


def layers(run_type: str, run: Run | None = None, vendor_id: str | None = None) -> list[tuple[str, dict]]:
    ctx = run_context(run)
    vendor_id = vendor_id or ctx.get("vendor_id")
    pb = playbook.load(run_type).settings
    out = [("this run only", ctx.get("overrides", {}))]
    if vendor_id:
        out.append((f"playbook, vendor {vendor_id}", pb.get("vendors", {}).get(vendor_id, {})))
    out.append(("playbook", {k: v for k, v in pb.items() if k != "vendors"}))
    out.append(("default", get_config()))
    return out


def effective(run_type: str, key: str, run: Run | None = None, vendor_id: str | None = None, default=None):
    return explain(run_type, key, run, vendor_id, default)[0]


def explain(run_type: str, key: str, run: Run | None = None, vendor_id: str | None = None, default=None):
    """(value, source) so the chat agent can say where a setting came from."""
    for source, layer in layers(run_type, run, vendor_id):
        v = get_path(layer, key)
        if v is not _MISSING:
            return copy.deepcopy(v), source
    return default, "not set"


def flatten(d: dict, prefix: str = "") -> dict:
    """Leaf keys, but lists (ladders, extra_steps) stay whole."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


EDITABLE_ROOTS = ("checks", "task_defaults", "ladders", "manual_check_roles", "extra_steps", "inbox_poll",
                  "approval_owner_threshold", "reserve_min")


def snapshot(run_type: str, run: Run | None = None, vendor_id: str | None = None) -> list[dict]:
    """Every editable setting with its effective value and source."""
    keys = [k for k in flatten(get_config()) if k.split(".")[0] in EDITABLE_ROOTS]
    return [{"key": k, "value": v, "source": s} for k in keys for v, s in [explain(run_type, k, run, vendor_id)]]
