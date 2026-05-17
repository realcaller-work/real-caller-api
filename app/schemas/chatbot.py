from typing import Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class PhoneVerdict(BaseModel):
    phone: str
    verdict: str                # scam | spam | suspicious | known_user | unknown
    confidence: float
    sources: dict[str, Any]
    explanation: str


class ChatResponse(BaseModel):
    reply: str
    verdicts: list[PhoneVerdict] = []
