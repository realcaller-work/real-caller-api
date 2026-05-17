from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    idToken: str
    deviceId: str
    platform: Optional[str] = "other"

class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    needsProfileUpdate: bool
