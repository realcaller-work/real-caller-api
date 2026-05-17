import uuid
from enum import Enum
from sqlalchemy import Column, String, DateTime, Integer, Enum as SQLEnum, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base

class ScamType(str, Enum):
    INVESTMENT = "INVESTMENT"
    LOAN = "LOAN"
    RECRUITMENT = "RECRUITMENT"
    IMPERSONATION = "IMPERSONATION"
    OTHER = "OTHER"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class ScamNumber(Base):
    __tablename__ = "scam_numbers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    scam_type = Column(SQLEnum(ScamType, name="scam_type"), default=ScamType.OTHER)
    risk_level = Column(SQLEnum(RiskLevel, name="risk_level"), default=RiskLevel.MEDIUM)
    reportCount = Column(Integer, default=1)
    createdAt = Column(DateTime(timezone=True), server_default=func.now())
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

Index("idx_phone_scam_uuid", ScamNumber.phone)
