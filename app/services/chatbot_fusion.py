"""Multi-signal verdict fusion.

Combines three independent signals into a single verdict per phone:
  - Database: blacklist membership + community report count
  - PhoBERT: classifier confidence on accompanying message text
  - Gemini: LLM's own assessment (provided as a 0-1 likelihood by Gemini, optional)

Weighted sum with configurable weights. The DB signal dominates because it's
ground truth from community + AI consensus; the other two are corroborative.
"""
from typing import Any

# Weights — must sum to 1.0
W_DATABASE = 0.4
W_PHOBERT = 0.3
W_GEMINI = 0.3

# Risk-level → numeric score for DB component
_RISK_SCORE = {
    "LOW": 0.3,
    "MEDIUM": 0.55,
    "HIGH": 0.8,
    "CRITICAL": 0.95,
}


def _db_signal(phone_info: dict[str, Any]) -> float:
    """Return 0-1 score from DB info. If not in blacklist, return 0."""
    if not phone_info or not phone_info.get("in_blacklist"):
        return 0.0
    risk = (phone_info.get("risk_level") or "MEDIUM").upper()
    base = _RISK_SCORE.get(risk, 0.55)
    # Slight bump for high report counts: 50+ reports → +0.05 cap
    bump = min((phone_info.get("report_count", 0)) / 1000.0, 0.05)
    return min(base + bump, 1.0)


def _phobert_signal(phobert: dict[str, Any] | None) -> float:
    if not phobert:
        return 0.0
    if not phobert.get("is_scam"):
        return 0.0
    return float(phobert.get("confidence", 0.0))


def _gemini_signal(gemini_likelihood: float | None) -> float:
    if gemini_likelihood is None:
        return 0.0
    return max(0.0, min(1.0, float(gemini_likelihood)))


def fuse_verdict(
    *,
    phone: str,
    phone_info: dict[str, Any] | None,
    phobert: dict[str, Any] | None,
    gemini_likelihood: float | None = None,
) -> dict[str, Any]:
    """Produce a structured verdict for a single phone number."""
    db_score = _db_signal(phone_info or {})
    phobert_score = _phobert_signal(phobert)
    gemini_score = _gemini_signal(gemini_likelihood)

    final = (
        db_score * W_DATABASE
        + phobert_score * W_PHOBERT
        + gemini_score * W_GEMINI
    )

    if (phone_info or {}).get("in_blacklist"):
        risk = (phone_info.get("risk_level") or "").upper()
        verdict = "scam" if risk in ("HIGH", "CRITICAL") else "spam"
    elif final >= 0.6:
        verdict = "scam"
    elif final >= 0.35:
        verdict = "suspicious"
    elif (phone_info or {}).get("is_known_user"):
        verdict = "known_user"
    else:
        verdict = "unknown"

    explanation_parts = []
    if db_score > 0:
        explanation_parts.append(
            f"có trong blacklist với mức rủi ro {(phone_info or {}).get('risk_level')} "
            f"và {(phone_info or {}).get('report_count')} báo cáo"
        )
    if phobert_score > 0:
        explanation_parts.append(
            f"PhoBERT đánh giá nội dung có dấu hiệu scam (confidence {phobert_score:.2f})"
        )
    if gemini_score > 0:
        explanation_parts.append(
            f"Gemini đánh giá khả năng lừa đảo ở mức {gemini_score:.2f}"
        )
    if not explanation_parts:
        explanation_parts.append("không có tín hiệu rủi ro nào được ghi nhận")

    return {
        "phone": phone,
        "verdict": verdict,
        "confidence": round(final, 3),
        "sources": {
            "database": {
                "score": round(db_score, 3),
                "weight": W_DATABASE,
                "details": phone_info,
            },
            "phobert": {
                "score": round(phobert_score, 3),
                "weight": W_PHOBERT,
                "details": phobert,
            },
            "gemini": {
                "score": round(gemini_score, 3),
                "weight": W_GEMINI,
            },
        },
        "explanation": "; ".join(explanation_parts),
    }
