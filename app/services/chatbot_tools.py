"""Tool wrappers exposed to the Gemini agent.

Each `*_impl` function is what we actually execute when Gemini emits a function call.
Each tool also has a JSON-schema declaration the SDK passes to Gemini so it knows
when/how to invoke it.

Tools intentionally accept primitives + a DB session bound by the caller, never
the Gemini SDK types — keeps them unit-testable in isolation.
"""
from typing import Any
from sqlalchemy.orm import Session

from app.models.scam_number import ScamNumber
from app.models.user import User
from app.models.scam_report import ReportSource
from app.services.ai import ai_service, AIServiceUnavailable
from app.services.utils import normalize_phone
from app.services.scam_report_service import submit_report


# ────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ────────────────────────────────────────────────────────────────────────────

def lookup_phone_impl(phone: str, *, db: Session) -> dict[str, Any]:
    """Look up the phone in our blacklist + user directory.

    Returns a flat dict the LLM can reason about without further parsing.
    """
    norm = normalize_phone(phone)
    scam = db.query(ScamNumber).filter(ScamNumber.phone == norm).first()
    user = db.query(User).filter(User.phone == norm).first()

    return {
        "phone_input": phone,
        "phone_normalized": norm,
        "in_blacklist": scam is not None,
        "report_count": scam.reportCount if scam else 0,
        "scam_type": (scam.scam_type.value if scam else None),
        "risk_level": (scam.risk_level.value if scam else None),
        "is_known_user": user is not None,
        "owner_display_name": user.fullName if (user and user.fullName) else None,
    }


def analyze_text_for_scam_impl(text: str) -> dict[str, Any]:
    """Run the custom PhoBERT model (via HF Inference) on a chunk of conversation text."""
    if not text or not text.strip():
        return {"is_scam": False, "confidence": 0.0, "scam_type": None, "reason": "empty input"}
    try:
        result = ai_service.analyze_scam_report(description=text, messages=[], evidence_urls=[])
    except AIServiceUnavailable:
        return {"is_scam": None, "confidence": 0.0, "scam_type": None, "reason": "ai_unavailable"}
    return {
        "is_scam": bool(result.get("is_scam")),
        "confidence": float(result.get("confidence", 0.0)),
        "scam_type": result.get("scam_type"),
    }


def submit_report_impl(
    *,
    phone: str,
    source: str,
    description: str,
    db: Session,
    current_user: User,
) -> dict[str, Any]:
    """File a scam report. Goes through the same consensus/AI logic as /scam/report."""
    try:
        src = ReportSource(source)
    except ValueError:
        src = ReportSource.USER_MANUAL
    return submit_report(
        db=db,
        current_user=current_user,
        phone=phone,
        source=src,
        description=description or "",
        messages=[],
    )


# ────────────────────────────────────────────────────────────────────────────
# JSON declarations for Gemini function calling
# ────────────────────────────────────────────────────────────────────────────

TOOL_DECLARATIONS = [
    {
        "name": "lookup_phone",
        "description": (
            "Tra cứu một số điện thoại trong cơ sở dữ liệu. Trả về xem số đó có nằm trong "
            "danh sách đen (scam blacklist) không, loại scam, mức độ rủi ro, và số lượt báo cáo. "
            "GỌI tool này MỖI KHI người dùng nhắc đến một số điện thoại cụ thể — đừng tự đoán."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "Số điện thoại người dùng nhắc đến, ví dụ '0988123456' hoặc '+84988123456'.",
                },
            },
            "required": ["phone"],
        },
    },
    {
        "name": "analyze_text_for_scam",
        "description": (
            "Phân tích một đoạn văn bản hoặc tin nhắn để xác định xem nó có phải là nội dung lừa đảo không, "
            "dùng mô hình PhoBERT chuyên biệt cho tiếng Việt. GỌI tool này khi người dùng dán/forward "
            "một đoạn hội thoại đáng ngờ và muốn biết nội dung có phải scam không."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Toàn bộ nội dung văn bản cần phân tích.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "submit_report",
        "description": (
            "Gửi một báo cáo lừa đảo cho hệ thống. CHỈ GỌI khi người dùng đã xác nhận rõ ràng muốn báo cáo "
            "một số điện thoại cụ thể (không tự ý gọi). Phải hỏi lại người dùng để confirm số + lý do trước."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "source": {
                    "type": "string",
                    "enum": ["USER_MANUAL", "SMS_INBOX"],
                    "description": "USER_MANUAL nếu user gõ tay; SMS_INBOX nếu app đọc tin nhắn tự động.",
                },
                "description": {
                    "type": "string",
                    "description": "Mô tả ngắn nội dung lừa đảo do user cung cấp.",
                },
            },
            "required": ["phone", "source", "description"],
        },
    },
]
