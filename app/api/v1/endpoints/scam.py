from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt
from app.db.session import get_db
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.scam_number import ScamNumber, RiskLevel
from app.models.scam_report import ScamReport
from app.schemas import scam as scam_schema
from app.services.utils import normalize_phone
from app.services.ai import ai_service

router = APIRouter()
security = HTTPBearer()

def get_current_device_id(auth: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = auth.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/check", response_model=scam_schema.ScamCheckResponse)
def check_scam(
    request: scam_schema.ScamCheckRequest,
    db: Session = Depends(get_db),
    device_id: str = Depends(get_current_device_id)
):
    # Extract all phones to query DB
    all_phones = []
    if request.phones:
        all_phones.extend(request.phones)
    if request.conversations:
        all_phones.extend([c.phone for c in request.conversations])
        
    normalized_phones = list(set([normalize_phone(p) for p in all_phones]))
    
    scam_entries = db.query(ScamNumber).filter(ScamNumber.phone.in_(normalized_phones)).all()
    scam_map = {entry.phone: entry for entry in scam_entries}
    
    results = []
    processed_phones = set()
    
    # Run conversations through AI if provided
    if request.conversations:
        for conv in request.conversations:
            norm = normalize_phone(conv.phone)
            processed_phones.add(norm)
            db_scam = scam_map.get(norm)
            
            # Use AI if there are messages
            ai_res = None
            if conv.messages:
                # Convert the typed objects into dictionaries for AI service
                messages_dict = [m.model_dump() for m in conv.messages]
                
                ai_res = ai_service.analyze_scam_report(
                    description="",
                    messages=messages_dict,
                    evidence_urls=[]
                )
            
            # Combine DB result and AI result
            is_scam = False
            scam_type = None
            risk_level = None
            reports = 0
            confidence = 0.0
            
            # Read from DB first
            if db_scam:
                is_scam = True
                scam_type = db_scam.scam_type
                risk_level = db_scam.risk_level
                reports = db_scam.reportCount
                
            # If AI evaluates to scam, it supplements or overrides
            if ai_res and ai_res.get("is_scam"):
                is_scam = True
                scam_enum_vals = ["investment", "loan", "recruitment", "impersonation", "other"]
                raw_type = ai_res.get("scam_type", "other")
                scam_type = raw_type if raw_type in scam_enum_vals else "other"
                risk_level = ai_res.get("risk_level", "medium")
                confidence = ai_res.get("confidence", 0.0)
                
            results.append({
                "phone": conv.phone,
                "isScam": is_scam,
                "scam_type": scam_type,
                "risk_level": risk_level,
                "reports": reports,
                "ai_confidence": confidence
            })
            
    # Also handle the bare request.phones ensuring no duplicates
    if request.phones:
        for phone in request.phones:
            norm = normalize_phone(phone)
            if norm in processed_phones:
                continue
            
            processed_phones.add(norm)
            if norm in scam_map:
                entry = scam_map[norm]
                results.append({
                    "phone": phone,
                    "isScam": True,
                    "scam_type": entry.scam_type,
                    "risk_level": entry.risk_level,
                    "reports": entry.reportCount,
                    "ai_confidence": 0.0
                })
            else:
                results.append({
                    "phone": phone,
                    "isScam": False,
                    "ai_confidence": 0.0
                })
            
    return {"results": results}

@router.post("/report")
def report_scam(
    report_in: scam_schema.ScamReportCreate,
    db: Session = Depends(get_db),
    device_id: str = Depends(get_current_device_id)
):
    norm_phone = normalize_phone(report_in.phone)
    
    # 1. AI Analysis
    ai_result = ai_service.analyze_scam_report(
        description=report_in.description or "",
        messages=report_in.messages or [],
        evidence_urls=report_in.evidence_urls or []
    )
    
    # Use AI classification directly
    scam_type = report_in.type
    risk_level = RiskLevel.MEDIUM
    is_ai_vetted = True
    
    if ai_result:
        is_scam = ai_result.get("is_scam", True)
        # Fallback to OTHER if PhoBERT classifies as harmless or returns invalid type
        scam_enum_vals = ["investment", "loan", "recruitment", "impersonation", "other"]
        raw_type = ai_result.get("scam_type", scam_type)
        scam_type = raw_type if raw_type in scam_enum_vals else "other"
            
        risk_level = ai_result.get("risk_level", "medium") if is_scam else "low"

    # 2. Update/Create ScamNumber
    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    if scam_num:
        scam_num.reportCount += 1
        if is_ai_vetted:
            scam_num.scam_type = scam_type
            scam_num.risk_level = risk_level
            scam_num.is_ai_vetted = True
            scam_num.metadata_info = ai_result # Store full result
    else:
        scam_num = ScamNumber(
            phone=norm_phone, 
            scam_type=scam_type, 
            risk_level=risk_level,
            reportCount=1,
            is_ai_vetted=is_ai_vetted,
            metadata_info=ai_result if is_ai_vetted else None
        )
        db.add(scam_num)
        
    # 3. Save Detailed Report Log
    report_log = ScamReport(
        phone=norm_phone,
        deviceId=device_id,
        reportType=scam_type,
        description=report_in.description,
        evidence_urls=report_in.evidence_urls,
        messages=report_in.messages
    )
    db.add(report_log)
    db.commit()
    
    return {
        "message": "Report submitted and analyzed by AI successfully",
        "ai_analysis": ai_result if is_ai_vetted else None
    }

@router.get("/{phone}", response_model=scam_schema.ScamCheckResult)
def get_scam_detail(
    phone: str,
    db: Session = Depends(get_db)
):
    norm_phone = normalize_phone(phone)
    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    if not scam_num:
        return {"phone": phone, "isScam": False}
    
    return {
        "phone": phone,
        "isScam": True,
        "scam_type": scam_num.scam_type,
        "risk_level": scam_num.risk_level,
        "reports": scam_num.reportCount
    }
