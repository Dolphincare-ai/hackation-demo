import json
import random
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

TONE = {"on_track": "good", "watch": "warn", "act_now": "bad"}
GENERIC_TODOS = [
    ("Care plan update, Rm {room}", "don", "today"),
    ("Post night-shift opening", "administrator", "week"),
    ("Review month-end census report", "administrator", "month"),
    ("Family notice, Rm {room}", "don", "today"),
    ("Renew pharmacy contract", "business_office_manager", "month"),
]


def _money(n):
    return "$" + format(round(n), ",")


def _board(b):
    """Quadrant board for one building. Fixture data now.

    TODO: Money and To-dos come from runs/tasks (the agent). Residents and Staffing stay
    mock connectors (PCC, Workday) and must keep the `live: false` tag.
    """
    rng = random.Random(b["id"])
    beds = rng.choice([48, 54, 60, 72])
    census = beds - rng.randint(1, 5)
    open_shifts = rng.randint(0, 3)
    rooms = [rng.randint(1, 40) for _ in range(3)]

    todos = [
        {"title": t.format(room=rooms[i % 3]), "owner": o, "bucket": bk, "late": i == 0 and b["late_tasks"] > 0, "source": "mock"}
        for i, (t, o, bk) in enumerate(GENERIC_TODOS[: 3 + rng.randint(0, 2)])
    ]
    if b["id"] == "riverside":  # the live demo building
        todos = [
            {"title": "Check enoxaparin delivery, invoice #4471", "owner": "don", "bucket": "today", "late": False, "source": "agent"},
            {"title": "Approve Harbor Pharmacy invoice #4471", "owner": "administrator", "bucket": "today", "late": False, "source": "agent"},
        ] + todos

    return {
        "building": {"id": b["id"], "name": b["name"], "beds": beds},
        "as_of": "10:42",
        "quadrants": [
            {
                "key": "residents", "title": "Residents & clinical", "headline": f"{census} / {beds}", "tone": "neutral",
                "lines": [
                    f"Census · {rng.randint(0, 3)} admits, {rng.randint(0, 2)} discharge today",
                    f"{rng.randint(0, 2)} hospital transfer · {rng.randint(0, 3)} open falls",
                    f"{rng.randint(0, 5)} changes in condition this week",
                ],
                "source": "Mock PointClickCare (ADT, incidents)", "live": False,
            },
            {
                "key": "money", "title": "Money today", "headline": {"on_track": "On track", "watch": "Watch", "act_now": "Act now"}[b["status"]],
                "tone": TONE[b["status"]],
                "lines": [
                    f"{b['open_runs']} invoice audits open · {b['late_tasks']} steps late",
                    f"{_money(b['at_risk'])} at risk on flagged invoice lines",
                    f"{_money(b['held_back'])} held back pending approval or funds",
                    f"Medicare A days {rng.randint(8, 20)} · Medicaid pending {rng.randint(0, 6)}",
                ],
                "source": "Invoice agent (live) + mock billing", "live": True,
            },
            {
                "key": "staffing", "title": "Staffing", "headline": f"{open_shifts} open shifts", "tone": "warn" if open_shifts >= 2 else "neutral",
                "lines": [
                    f"Tonight: {rng.randint(0, 2)} CNA call-off, {rng.randint(0, 2)} nurse vacancy",
                    f"{rng.randint(0, 2)} resignation in progress",
                    f"Agency hours this week {rng.randint(10, 60)}",
                ],
                "source": "Mock Workday (scheduling, HRIS)", "live": False,
            },
        ],
        "todos": todos,
    }


@router.get("/buildings/{building_id}/board")
def building_board(building_id: str):
    data = json.loads((FIXTURES / "portfolio.json").read_text(encoding="utf-8"))
    for b in data["buildings"]:
        if b["id"] == building_id:
            return _board(b)
    raise HTTPException(404, "Unknown building")
