from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.scam_number import ScamNumber, RiskLevel
from app.schemas import scam as scam_schema
from app.services.utils import normalize_phone
from app.services.ai import ai_service
from app.services.scam_report_service import submit_report

router = APIRouter()


def _user_info(db_user: User) -> dict:
    return {
        "fullName": db_user.fullName,
        "email": db_user.email,
        "birthday": db_user.birthday,
        "gender": db_user.gender,
    }


def _scam_type_of(risk_level) -> str:
    return "scam" if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL") else "spam"


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

        if db_scam:
            results.append({
                "phone": phone,
                "type": _scam_type_of(db_scam.risk_level),
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
    for conv in request.conversations:
        norm = normalize_phone(conv.phone)
        db_scam = scam_map.get(norm)
        db_user = user_map.get(norm)

        ai_res = None
        if conv.messages:
            messages_dict = [m.model_dump() for m in conv.messages]
            ai_res = ai_service.analyze_scam_report(
                description="",
                messages=messages_dict,
                evidence_urls=[],
            )

        is_scam = False
        scam_type = None
        risk_level = None
        reports = 0
        confidence = 0.0

        if db_scam:
            is_scam = True
            scam_type = db_scam.scam_type
            risk_level = db_scam.risk_level
            reports = db_scam.reportCount

        if ai_res and ai_res.get("is_scam"):
            is_scam = True
            scam_enum_vals = ["INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER"]
            raw_type = str(ai_res.get("scam_type", "OTHER")).upper()
            scam_type = raw_type if raw_type in scam_enum_vals else "OTHER"
            risk_level = str(ai_res.get("risk_level", "MEDIUM")).upper()
            confidence = ai_res.get("confidence", 0.0)

        if is_scam:
            results.append({
                "phone": conv.phone,
                "type": _scam_type_of(risk_level),
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

    return {"results": results}


@router.post("/report", response_model=scam_schema.ScamReportResponse)
def report_scam(
    report_in: scam_schema.ScamReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return submit_report(
        db=db,
        current_user=current_user,
        phone=report_in.phone,
        source=report_in.source,
        description=report_in.description or "",
        messages=report_in.messages or [],
        scam_type_fallback=str(report_in.type),
    )


@router.get("/{phone}", response_model=scam_schema.ScamCheckResult)
def get_scam_detail(
    phone: str,
    db: Session = Depends(get_db),
):
    norm_phone = normalize_phone(phone)
    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    db_user = db.query(User).filter(User.phone == norm_phone).first()

    if scam_num:
        return {
            "phone": phone,
            "type": _scam_type_of(scam_num.risk_level),
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
