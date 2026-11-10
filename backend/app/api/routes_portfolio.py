import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "portfolio.json"


# TODO: replace the fixture with queries over runs, tasks and audit_log.
# The response shape is the contract (CLAUDE.md section 11); the frontend must not change.
@router.get("/portfolio")
def portfolio():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))
