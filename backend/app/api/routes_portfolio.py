import json
from pathlib import Path

from fastapi import APIRouter

from .routes_board import load_boards

router = APIRouter()

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "portfolio.json"


# TODO: replace the fixture with queries over runs, tasks and audit_log.
# The response shape is the contract (CLAUDE.md section 11); the frontend must not change.
@router.get("/portfolio")
def portfolio():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    boards = load_boards()
    for b in data["buildings"]:
        board = boards[b["id"]]
        q = {x["key"]: x for x in board["quadrants"]}
        b["summary"] = {
            "residents": {"headline": q["residents"]["headline"], "tone": q["residents"]["tone"]},
            "staffing": {"headline": q["staffing"]["headline"], "tone": q["staffing"]["tone"]},
            "todos": {"open": len(board["todos"]), "late": sum(1 for t in board["todos"] if t["late"])},
        }
    return data
