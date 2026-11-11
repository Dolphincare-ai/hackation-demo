"""Agent playbooks: one markdown file per workflow type. Generic, no invoice logic.

A playbook has prose (read by the AI chat agent) and exactly one fenced block

    ```yaml settings
    ...
    ```

that the engine reads. The live copy lives in data/playbooks/<run_type>.md and is changed only
through the app (chat proposal -> person confirms). The factory default ships with the workflow
and is copied only when the live file is missing or someone confirms "restore defaults".
"""
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from ..config import data_dir

BLOCK = re.compile(r"```yaml settings\n(.*?)```", re.DOTALL)

_registry: dict[str, tuple[Path, type[BaseModel]]] = {}
_last_good: dict[str, "Playbook"] = {}


class PlaybookError(ValueError):
    pass


@dataclass
class Playbook:
    run_type: str
    text: str
    settings: dict  # validated, None-free

    @property
    def prose(self) -> str:
        return BLOCK.sub("(settings block omitted)", self.text).strip()


def register(run_type: str, default_path: Path, schema: type[BaseModel]) -> None:
    _registry[run_type] = (default_path, schema)


def registered() -> list[str]:
    return list(_registry)


def live_path(run_type: str) -> Path:
    return data_dir() / "playbooks" / f"{run_type}.md"


def default_text(run_type: str) -> str:
    return _registry[run_type][0].read_text(encoding="utf-8")


def parse(run_type: str, text: str) -> Playbook:
    """Validate a full playbook text. Raises PlaybookError with a readable message."""
    blocks = BLOCK.findall(text)
    if len(blocks) != 1:
        raise PlaybookError("The playbook must contain exactly one ```yaml settings``` block")
    try:
        raw = yaml.safe_load(blocks[0]) or {}
    except yaml.YAMLError as e:
        raise PlaybookError(f"Settings block is not valid YAML: {e}") from e
    schema = _registry[run_type][1]
    try:
        settings = schema.model_validate(raw).model_dump(exclude_none=True)
    except ValidationError as e:
        raise PlaybookError(_readable(e)) from e
    return Playbook(run_type, text, settings)


def _readable(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = "is not a setting that can be changed" if err["type"] == "extra_forbidden" else err["msg"]
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts)


def load(run_type: str) -> Playbook:
    """The live playbook. Creates it from the factory default if missing.
    If the live file is broken, keep using the last good version (never crash the bot)."""
    path = live_path(run_type)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_registry[run_type][0], path)
    try:
        pb = parse(run_type, path.read_text(encoding="utf-8"))
    except PlaybookError:
        return _last_good.get(run_type) or parse(run_type, default_text(run_type))
    _last_good[run_type] = pb
    return pb


def render(text: str, settings: dict) -> str:
    """Replace the settings block, keep the prose exactly as it is."""
    body = yaml.safe_dump(settings, sort_keys=False, default_flow_style=None, allow_unicode=True)
    return BLOCK.sub(lambda _: f"```yaml settings\n{body}```", text, count=1)


def write_text(run_type: str, text: str) -> tuple[str, str]:
    """Validate then write. Returns (before, after) for the audit log."""
    parse(run_type, text)
    path = live_path(run_type)
    before = load(run_type).text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _last_good.pop(run_type, None)
    return before, text


def write_settings(run_type: str, settings: dict) -> tuple[str, str]:
    return write_text(run_type, render(load(run_type).text, settings))


def append_note(run_type: str, note: str) -> tuple[str, str]:
    """Add a bullet under '## Notes' in the prose (created if missing)."""
    text = load(run_type).text.rstrip() + "\n"
    if "\n## Notes\n" not in text:
        text += "\n## Notes\n"
    return write_text(run_type, text + f"- {note.strip()}\n")
