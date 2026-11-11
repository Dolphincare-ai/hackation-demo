import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel

from .api.deps import run_tick
from .api.routes_agent import router as agent_router
from .api.routes_board import router as board_router
from .api.routes_dashboard import router as dashboard_router
from .api.routes_portfolio import router as portfolio_router
from .api.routes_runs import router as runs_router
from .api.routes_tasks import router as tasks_router
from .core.permissions import Forbidden
from .db import get_engine

log = logging.getLogger("scheduler")
TICK_SECONDS = 5


async def _loop():
    while True:
        try:
            await asyncio.to_thread(run_tick)
        except Exception:  # never let one bad tick stop the bot
            log.exception("tick failed")
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(get_engine())  # create missing tables, keep existing data
    task = None if os.environ.get("DISABLE_SCHEDULER") else asyncio.create_task(_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="SNF Operating Layer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(portfolio_router)
app.include_router(board_router)
app.include_router(runs_router)
app.include_router(tasks_router)
app.include_router(dashboard_router)
app.include_router(agent_router)  # B: /agent/chat, /agent/chat/history


@app.exception_handler(Forbidden)
async def _forbidden(_: Request, e: Forbidden):
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(LookupError)
async def _missing(_: Request, e: LookupError):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(ValueError)
async def _bad(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)
