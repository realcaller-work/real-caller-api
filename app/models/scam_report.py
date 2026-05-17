import uuid
from enum import Enum
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class ReportSource(str, Enum):
    """Trust tier of a scam report. Lower trust sources are easier for clients to fabricate."""
    USER_MANUAL = "USER_MANUAL"        # user typed everything by hand
    SMS_INBOX = "SMS_INBOX"            # auto-extracted from device SMS inbox


# Source → trust multiplier applied to AI confidence when deciding blacklist actions.
SOURCE_TRUST: dict[ReportSource, float] = {
    ReportSource.SMS_INBOX: 1.0,
    ReportSource.USER_MANUAL: 0.4,
}


class ScamReport(Base):
    __tablename__ = "scam_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phone = Column(String, index=True, nullable=False)
    # SET NULL on user delete so audit history survives account deletion.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source = Column(
        SQLEnum(ReportSource, name="report_source"),
        nullable=False,
        default=ReportSource.USER_MANUAL,
        server_default=ReportSource.USER_MANUAL.value,
    )
    createdAt = Column(DateTime(timezone=True), server_default=func.now())


# Speeds up distinct-reporter count per phone.
Index("ix_scam_reports_phone_user", ScamReport.phone, ScamReport.user_id)
