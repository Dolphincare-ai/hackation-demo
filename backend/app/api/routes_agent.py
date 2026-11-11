from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..ai import chat as chat_mod
from .deps import acting_user, session_dep, x_user

router = APIRouter()


class ChatBody(BaseModel):
    user_id: str | None = None
    message: str
    run_id: int | None = None


@router.post("/agent/chat")
def post_chat(body: ChatBody, session=Depends(session_dep), x_user_id=Depends(x_user)):
    user = acting_user(session, body.user_id, x_user_id)
    try:
        out = chat_mod.chat(session, user.id if user else "", body.message.strip()[:2000], body.run_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return out


@router.get("/agent/chat/history")
def get_history(user_id: str | None = None, limit: int = 50, session=Depends(session_dep), x_user_id=Depends(x_user)):
    user = acting_user(session, user_id, x_user_id)
    return chat_mod.history(session, user.id, min(limit, 200)) if user else []
