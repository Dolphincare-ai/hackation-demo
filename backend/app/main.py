from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_board import router as board_router
from .api.routes_portfolio import router as portfolio_router

app = FastAPI(title="SNF Operating Layer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(portfolio_router)
app.include_router(board_router)
