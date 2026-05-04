import uuid
from enum import Enum
from sqlalchemy import Column, String, DateTime, Date, Boolean, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.base import Base

class GenderType(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    
    fullName = Column(String, nullable=True)
    avatar = Column(String, nullable=True)
    email = Column(String, nullable=True)
    birthday = Column(Date, nullable=True)
    gender = Column(SQLEnum(GenderType, name="gender_type"), nullable=True)
    is_verified = Column(Boolean, default=False)
    
    createdAt = Column(DateTime(timezone=True), server_default=func.now())
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # Relationship to devices
    devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
