"""Shared scam-report logic used by both the /scam/report endpoint and the chatbot tool.

Encapsulates:
  - Audit log creation (ScamReport row, with user_id + source)
  - Direct path (AI confidence × source trust ≥ 0.4)
  - Consensus path (distinct(user_id) ≥ 5 + AI agrees)
  - Risk-level promotion on existing blacklist entries (SMS_INBOX only)
"""
from typing import Any
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.models.scam_number import ScamNumber
from app.models.scam_report import ScamReport, ReportSource, SOURCE_TRUST
from app.models.user import User
from app.services.ai import ai_service
from app.services.utils import normalize_phone


BLACKLIST_THRESHOLD = 0.4
CONSENSUS_THRESHOLD = 5


def _risk_from_score(score: float) -> str:
    if score >= 0.8:
        return "CRITICAL"
    if score >= 0.6:
        return "HIGH"
    if score >= 0.4:
        return "MEDIUM"
    return "LOW"


def _risk_rank(level) -> int:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return order.get(str(level).split(".")[-1], 0)


def submit_report(
    *,
    db: Session,
    current_user: User,
    phone: str,
    source: ReportSource = ReportSource.USER_MANUAL,
    description: str = "",
    messages: list[dict] | None = None,
    scam_type_fallback: str = "OTHER",
) -> dict[str, Any]:
    """Apply the full report flow and return the response payload."""
    norm_phone = normalize_phone(phone)
    source_trust = SOURCE_TRUST[source]

    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    report_log = ScamReport(phone=norm_phone, source=source, user_id=current_user.id)
    db.add(report_log)
    db.flush()  # make new row visible to distinct-reporters query

    # ── existing blacklist entry ─────────────────────────────────────────────
    if scam_num:
        scam_num.reportCount += 1
        if source_trust >= 0.8:
            if _risk_rank(scam_num.risk_level) < 3:
                scam_num.risk_level = "CRITICAL"
        db.commit()
        db.refresh(report_log)
        return {
            "success": True,
            "message": (
                "Cảm ơn bạn đã báo cáo. Số điện thoại này đã nằm trong danh sách đen, "
                "chúng tôi đã ghi nhận thêm."
            ),
            "report_id": str(report_log.id),
            "action_taken": "REPORT_COUNT_INCREMENTED",
            "updated_risk_level": scam_num.risk_level,
        }

    # ── new phone ────────────────────────────────────────────────────────────
    ai_result = ai_service.analyze_scam_report(
        description=description or "",
        messages=messages or [],
        evidence_urls=[],
    )
    ai_confidence = float(ai_result.get("confidence", 0.0)) if ai_result else 0.0
    ai_says_scam = bool(ai_result.get("is_scam", False)) if ai_result else False
    combined_score = ai_confidence * source_trust

    direct_path = ai_says_scam and combined_score >= BLACKLIST_THRESHOLD

    distinct_reporters = (
        db.query(func.count(distinct(ScamReport.user_id)))
        .filter(ScamReport.phone == norm_phone, ScamReport.user_id.is_not(None))
        .scalar() or 0
    )
    consensus_path = ai_says_scam and distinct_reporters >= CONSENSUS_THRESHOLD

    if direct_path or consensus_path:
        scam_enum_vals = ["INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER"]
        raw_type_in = ai_result.get("scam_type", scam_type_fallback) if ai_result else scam_type_fallback
        raw_type = str(raw_type_in).upper()
        scam_type = raw_type if raw_type in scam_enum_vals else "OTHER"

        effective_score = max(combined_score, 0.4 if consensus_path else 0.0)
        risk_level = _risk_from_score(effective_score)

        db.add(ScamNumber(
            phone=norm_phone,
            scam_type=scam_type,
            risk_level=risk_level,
            reportCount=distinct_reporters,
        ))
        db.commit()
        db.refresh(report_log)
        return {
            "success": True,
            "message": (
                "Báo cáo thành công. Cộng đồng xác nhận đây là số có rủi ro lừa đảo và đã thêm vào danh sách đen."
                if consensus_path and not direct_path
                else "Báo cáo thành công. Hệ thống AI xác nhận đây là số có rủi ro lừa đảo/làm phiền và đã thêm vào danh sách đen."
            ),
            "report_id": str(report_log.id),
            "action_taken": "AI_EVALUATED_AND_ADDED",
            "updated_risk_level": risk_level,
        }

    db.commit()
    db.refresh(report_log)
    return {
        "success": True,
        "message": "Đã ghi nhận báo cáo. Hệ thống AI đánh giá rủi ro thấp, số này sẽ được đưa vào diện theo dõi thêm.",
        "report_id": str(report_log.id),
        "action_taken": "LOGGED_ONLY",
        "updated_risk_level": None,
    }
