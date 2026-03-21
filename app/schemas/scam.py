import uuid
from typing import List, Optional
from pydantic import BaseModel
from app.models.scam_number import ScamType, RiskLevel

class MessageItem(BaseModel):
    sender: str
    content: str
    
class ConversationCheck(BaseModel):
    phone: str
    messages: Optional[List[MessageItem]] = []

class ScamCheckRequest(BaseModel):
    phones: Optional[List[str]] = []
    conversations: Optional[List[ConversationCheck]] = []

class ScamCheckResult(BaseModel):
    phone: str
    isScam: bool
    scam_type: Optional[ScamType] = None
    risk_level: Optional[RiskLevel] = None
    reports: Optional[int] = 0
    ai_confidence: Optional[float] = 0.0

class ScamCheckResponse(BaseModel):
    results: List[ScamCheckResult]

class ScamReportCreate(BaseModel):
    phone: str
    type: ScamType = ScamType.OTHER
    description: Optional[str] = None
    evidence_urls: Optional[List[str]] = []
    messages: Optional[List[dict]] = []
