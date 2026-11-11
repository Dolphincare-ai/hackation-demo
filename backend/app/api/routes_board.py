import json
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from ..core import clock
from ..db import get_session
from ..models import Run, Task

router = APIRouter()

BOARDS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "boards.json"


def _bucket(due_at, now) -> str:
    if due_at <= now + timedelta(hours=24):
        return "today"
    return "week" if due_at <= now + timedelta(days=7) else "month"


def _agent_todos() -> dict[str, list[dict]]:
    """Open tasks from the engine, grouped by building. Soonest due first."""
    now = clock.now()
    out: dict[str, list[dict]] = {}
    try:
        with get_session() as s:
            rows = s.exec(
                select(Task, Run).where(Task.run_id == Run.id, Task.status == "open").order_by(Task.due_at)
            ).all()
    except OperationalError:  # db not created yet
        return out
    for task, run in rows:
        out.setdefault(run.building_id, []).append(
            {"title": task.title, "owner": task.role, "bucket": _bucket(task.due_at, now),
             "late": task.due_at < now, "source": "agent"}
        )
    return out


def load_boards() -> dict:
    # Residents and Staffing stay mock connectors (PCC, Workday), `live: false`.
    # To-dos: mock items come from the fixture; agent items come from open tasks in the DB.
    # TODO: Money quadrant from runs/tasks as well.
    boards = json.loads(BOARDS.read_text(encoding="utf-8"))
    live = _agent_todos()
    for bid, board in boards.items():
        mock = [t for t in board["todos"] if t.get("source") != "agent"]
        board["todos"] = live.get(bid, []) + mock
    return boards


@router.get("/buildings/{building_id}/board")
def building_board(building_id: str):
    board = load_boards().get(building_id)
    if board is None:
        raise HTTPException(404, "Unknown building")
    return board
