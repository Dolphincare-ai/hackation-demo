import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

BOARDS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "boards.json"


def load_boards() -> dict:
    # TODO: Money and To-dos come from runs/tasks (the agent). Residents and Staffing stay
    # mock connectors (PCC, Workday) and keep `live: false`.
    return json.loads(BOARDS.read_text(encoding="utf-8"))


@router.get("/buildings/{building_id}/board")
def building_board(building_id: str):
    board = load_boards().get(building_id)
    if board is None:
        raise HTTPException(404, "Unknown building")
    return board
