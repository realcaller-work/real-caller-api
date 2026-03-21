import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base

class ScamReport(Base):
    __tablename__ = "scam_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phone = Column(String, index=True, nullable=False)
    deviceId = Column(String, ForeignKey("devices.deviceId"), index=True, nullable=False)
    reportType = Column(String, nullable=True) # Can be Enum too, but keeping it flexible for now
    description = Column(Text, nullable=True)
    evidence_urls = Column(JSONB, nullable=True) # List of strings/objects
    messages = Column(JSONB, nullable=True) # List of message objects
    createdAt = Column(DateTime(timezone=True), server_default=func.now())
