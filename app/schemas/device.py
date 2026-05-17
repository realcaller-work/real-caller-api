import uuid
from typing import Optional
from pydantic import BaseModel
from app.models.device import PlatformType

class DeviceBase(BaseModel):
    deviceId: str
    platform: Optional[PlatformType] = PlatformType.OTHER

class DeviceCreate(DeviceBase):
    phone: Optional[str] = None

class Device(DeviceBase):
    id: uuid.UUID
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
