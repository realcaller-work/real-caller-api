from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.chatbot import ChatRequest, ChatResponse
from app.services.chatbot import chatbot_service
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
def handle_chat_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    AI Hybrid Chatbot: NLP Intent (CHECK/REPORT) -> Extract Phone -> Core DB/AI -> NLP Response.
    History is loaded from DB automatically per user.
    """
    response = chatbot_service.process_message(request.message, db, current_user)
    return response
