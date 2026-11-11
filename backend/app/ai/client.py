"""Thin OpenAI wrapper used by every AI slot.

Rules (CLAUDE.md section 10): validate against a schema, retry once, then raise AIError so the
caller can fall back. AI_MODE=cache serves from data/ai_cache only (AICacheMiss when absent).
The key comes from OPENAI_API_KEY in the environment, never from code.
"""
import json
import os
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import cache

PROMPTS = Path(__file__).with_name("prompts")
_client = None  # tests inject a stub with set_client()


class AIError(RuntimeError):
    pass


class AICacheMiss(AIError):
    pass


def mode() -> str:
    return os.environ.get("AI_MODE", "live").lower()


def model() -> str:
    return os.environ.get("MODEL", "gpt-4o")


def set_client(c) -> None:
    global _client
    _client = c


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        if not os.environ.get("OPENAI_API_KEY"):
            raise AIError("OPENAI_API_KEY is not set")
        _client = OpenAI()
    return _client


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def _complete(system: str, user: str, json_mode: bool) -> str:
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    r = get_client().chat.completions.create(
        model=model(), temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
    return r.choices[0].message.content or ""


def _run(name: str, payload, validate, json_mode: bool):
    system = prompt(name)
    k = cache.key(name, system, payload)
    hit = cache.get(name, k)
    if hit is not None:
        try:
            return validate(hit)
        except (ValidationError, ValueError):
            pass  # a bad cache entry is ignored
    if mode() == "cache":
        raise AICacheMiss(f"{name}: no cached answer")
    user = json.dumps(payload, default=str, indent=1)
    last = None
    for _ in range(2):  # one retry
        try:
            out = _complete(system, user, json_mode)
            val = validate(out)
        except (ValidationError, ValueError) as e:
            last = e
            continue
        except Exception as e:  # network, auth, rate limit
            raise AIError(f"{name}: {e}") from e
        cache.put(name, k, out)
        return val
    raise AIError(f"{name}: invalid response after retry: {last}")


def call_json(name: str, payload, schema: type[BaseModel]):
    return _run(name, payload, schema.model_validate_json, True)


def call_text(name: str, payload) -> str:
    def ok(s: str) -> str:
        if not s.strip():
            raise ValueError("empty")
        return s.strip()
    return _run(name, payload, ok, False)
