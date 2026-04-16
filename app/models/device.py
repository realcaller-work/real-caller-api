import uuid
from enum import Enum
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.base import Base

class PlatformType(str, Enum):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    OTHER = "other"

class Device(Base):
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    deviceId = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True) # Could be deprecated later now that User exists
    platform = Column(SQLEnum(PlatformType, name="platform_type"), default=PlatformType.OTHER)
    
    # Link to User
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    user = relationship("User", back_populates="devices")
    
    createdAt = Column(DateTime(timezone=True), server_default=func.now())
    lastActive = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
