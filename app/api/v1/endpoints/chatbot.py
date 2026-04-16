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
    API for AI Hybrid Chatbot: NLP Intent -> Extract Phone -> Core DB Model -> NLP Response
    """
    response = chatbot_service.process_message(request.message, request.history, db)
    return response
