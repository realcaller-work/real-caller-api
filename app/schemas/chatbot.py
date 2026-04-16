from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.schemas.scam import ScamCheckResult

class ChatMessage(BaseModel):
    role: str = "user" # "user" or "model"
    content: str
    
class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []
    
class ChatResponse(BaseModel):
    reply: str
    detected_phone: Optional[str] = None
    scam_info: Optional[ScamCheckResult] = None
