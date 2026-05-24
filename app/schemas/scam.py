from datetime import date
from typing import List, Optional
from pydantic import BaseModel, EmailStr
from app.models.scam_number import ScamType, RiskLevel
from app.models.scam_report import ReportSource

class MessageItem(BaseModel):
    sender: str
    content: str

class ConversationCheck(BaseModel):
    phone: str
    messages: Optional[List[MessageItem]] = []

class ScamCheckPhonesRequest(BaseModel):
    phones: List[str]

class ScamCheckConversationsRequest(BaseModel):
    conversations: List[ConversationCheck]

class ScamInfo(BaseModel):
    scam_type: Optional[ScamType] = None
    risk_level: Optional[RiskLevel] = None
    reports: Optional[int] = 0
    ai_confidence: Optional[float] = 0.0

class UserInfo(BaseModel):
    fullName: Optional[str] = None
    email: Optional[EmailStr] = None
    birthday: Optional[date] = None
    gender: Optional[str] = None

class ScamCheckResult(BaseModel):
    phone: str
    type: str # 'scam', 'unknown', 'normal'
    scam_info: Optional[ScamInfo] = None
    user_info: Optional[UserInfo] = None

class ScamCheckResponse(BaseModel):
    results: List[ScamCheckResult]

class ScamReportCreate(BaseModel):
    phone: str
    type: ScamType = ScamType.OTHER
    source: ReportSource = ReportSource.USER_MANUAL
    description: Optional[str] = None
    messages: Optional[List[dict]] = []

class ScamReportResponse(BaseModel):
    success: bool
    message: str
    report_id: str
    action_taken: str
    updated_risk_level: Optional[RiskLevel] = None
