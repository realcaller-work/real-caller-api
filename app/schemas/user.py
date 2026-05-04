from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date
from uuid import UUID
from app.models.user import GenderType

class UserProfileUpdate(BaseModel):
    fullName: Optional[str] = None
    avatar: Optional[str] = None
    email: Optional[EmailStr] = None
    birthday: Optional[date] = None
    gender: Optional[GenderType] = None

class UserProfileResponse(BaseModel):
    id: UUID
    phone: str
    fullName: Optional[str] = None
    avatar: Optional[str] = None
    email: Optional[str] = None
    birthday: Optional[date] = None
    gender: Optional[GenderType] = None

    class Config:
        from_attributes = True
