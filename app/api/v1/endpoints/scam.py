from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.scam_number import ScamNumber, RiskLevel
from app.schemas import scam as scam_schema
from app.services.utils import normalize_phone
from app.services.ai import ai_service, AIServiceUnavailable
from app.services.scam_report_service import submit_report

SCAM_ENUM_VALS = ("INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER")
SCAM_RISK_LEVELS = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL"})

router = APIRouter()


def _user_info(db_user: User) -> dict:
    return {
        "fullName": db_user.fullName,
        "email": db_user.email,
        "birthday": db_user.birthday,
        "gender": db_user.gender,
    }


def _is_scam_risk(risk_level) -> bool:
    """Only HIGH/CRITICAL is reported as scam to clients. LOW/MEDIUM falls through."""
    return risk_level in SCAM_RISK_LEVELS


@router.post("/check-phones", response_model=scam_schema.ScamCheckResponse)
def check_phones(
    request: scam_schema.ScamCheckPhonesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    normalized_phones = list({normalize_phone(p) for p in request.phones})
    scam_map = {e.phone: e for e in db.query(ScamNumber).filter(ScamNumber.phone.in_(normalized_phones)).all()}
    user_map = {e.phone: e for e in db.query(User).filter(User.phone.in_(normalized_phones)).all()}

    results = []
    seen = set()
    for phone in request.phones:
        norm = normalize_phone(phone)
        if norm in seen:
            continue
        seen.add(norm)

        db_scam = scam_map.get(norm)
        db_user = user_map.get(norm)

        if db_scam and _is_scam_risk(db_scam.risk_level):
            results.append({
                "phone": phone,
                "type": "scam",
                "scam_info": {
                    "scam_type": db_scam.scam_type,
                    "risk_level": db_scam.risk_level,
                    "reports": db_scam.reportCount,
                    "ai_confidence": 0.0,
                },
                "user_info": None,
            })
        elif db_user:
            results.append({
                "phone": phone,
                "type": "normal",
                "scam_info": None,
                "user_info": _user_info(db_user),
            })
        else:
            results.append({
                "phone": phone,
                "type": "unknown",
                "scam_info": None,
                "user_info": None,
            })

    return {"results": results}


@router.post("/check-conversations", response_model=scam_schema.ScamCheckResponse)
def check_conversations(
    request: scam_schema.ScamCheckConversationsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_phones = [c.phone for c in request.conversations]
    normalized_phones = list({normalize_phone(p) for p in all_phones})

    scam_map = {e.phone: e for e in db.query(ScamNumber).filter(ScamNumber.phone.in_(normalized_phones)).all()}
    user_map = {e.phone: e for e in db.query(User).filter(User.phone.in_(normalized_phones)).all()}

    results = []
    needs_commit = False
    for conv in request.conversations:
        norm = normalize_phone(conv.phone)
        db_scam = scam_map.get(norm)
        db_user = user_map.get(norm)

        # Already on the blacklist at scam level (HIGH/CRITICAL) → trust DB, skip AI.
        # LOW/MEDIUM entries still go through AI so a fresh check can escalate them.
        already_scam = db_scam is not None and _is_scam_risk(db_scam.risk_level)

        ai_res = None
        if not already_scam and conv.messages:
            messages_dict = [m.model_dump() for m in conv.messages]
            try:
                ai_res = ai_service.analyze_scam_report(
                    description="",
                    messages=messages_dict,
                    evidence_urls=[],
                )
            except AIServiceUnavailable:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="AI analysis is temporarily unavailable. Please try again later.",
                )

        is_scam = False
        scam_type = None
        risk_level = None
        reports = 0
        confidence = 0.0

        if already_scam:
            is_scam = True
            scam_type = db_scam.scam_type
            risk_level = db_scam.risk_level
            reports = db_scam.reportCount

        if not is_scam and ai_res and ai_res.get("is_scam"):
            raw_risk = str(ai_res.get("risk_level", "HIGH")).upper()
            # Only HIGH/CRITICAL is surfaced as scam — lower risk is silently dropped.
            if _is_scam_risk(raw_risk):
                is_scam = True
                raw_type = str(ai_res.get("scam_type", "OTHER")).upper()
                scam_type = raw_type if raw_type in SCAM_ENUM_VALS else "OTHER"
                risk_level = raw_risk
                confidence = ai_res.get("confidence", 0.0)

                # Persist so future /check-* calls hit the DB and skip AI.
                if db_scam is None:
                    try:
                        with db.begin_nested():
                            new_entry = ScamNumber(
                                phone=norm,
                                scam_type=scam_type,
                                risk_level=risk_level,
                                reportCount=1,
                            )
                            db.add(new_entry)
                        scam_map[norm] = new_entry
                        reports = new_entry.reportCount
                        needs_commit = True
                    except IntegrityError:
                        existing = db.query(ScamNumber).filter(ScamNumber.phone == norm).first()
                        if existing:
                            scam_map[norm] = existing
                            reports = existing.reportCount
                else:
                    # Existing LOW/MEDIUM entry escalated by AI → upgrade in place.
                    db_scam.risk_level = risk_level
                    db_scam.scam_type = scam_type
                    reports = db_scam.reportCount
                    needs_commit = True

        if is_scam:
            results.append({
                "phone": conv.phone,
                "type": "scam",
                "scam_info": {
                    "scam_type": scam_type,
                    "risk_level": risk_level,
                    "reports": reports,
                    "ai_confidence": confidence,
                },
                "user_info": None,
            })
        elif db_user:
            results.append({
                "phone": conv.phone,
                "type": "normal",
                "scam_info": None,
                "user_info": _user_info(db_user),
            })
        else:
            results.append({
                "phone": conv.phone,
                "type": "unknown",
                "scam_info": None,
                "user_info": None,
            })

    if needs_commit:
        db.commit()

    return {"results": results}


@router.post("/report", response_model=scam_schema.ScamReportResponse)
def report_scam(
    report_in: scam_schema.ScamReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return submit_report(
            db=db,
            current_user=current_user,
            phone=report_in.phone,
            source=report_in.source,
            description=report_in.description or "",
            messages=report_in.messages or [],
            scam_type_fallback=str(report_in.type),
        )
    except AIServiceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI analysis is temporarily unavailable. Please try again later.",
        )


@router.get("/{phone}", response_model=scam_schema.ScamCheckResult)
def get_scam_detail(
    phone: str,
    db: Session = Depends(get_db),
):
    norm_phone = normalize_phone(phone)
    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    db_user = db.query(User).filter(User.phone == norm_phone).first()

    if scam_num and _is_scam_risk(scam_num.risk_level):
        return {
            "phone": phone,
            "type": "scam",
            "scam_info": {
                "scam_type": scam_num.scam_type,
                "risk_level": scam_num.risk_level,
                "reports": scam_num.reportCount,
                "ai_confidence": 0.0,
            },
            "user_info": None,
        }
    elif db_user:
        return {
            "phone": phone,
            "type": "normal",
            "scam_info": None,
            "user_info": _user_info(db_user),
        }

    return {
        "phone": phone,
        "type": "unknown",
        "scam_info": None,
        "user_info": None,
    }
