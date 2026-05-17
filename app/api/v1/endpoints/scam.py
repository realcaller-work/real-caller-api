from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.config import settings
from app.api.deps import get_current_user, get_current_device
from app.models.user import User
from app.models.device import Device
from app.models.scam_number import ScamNumber, RiskLevel
from app.models.scam_report import ScamReport
from app.schemas import scam as scam_schema
from app.services.utils import normalize_phone
from app.services.ai import ai_service

router = APIRouter()
@router.post("/check-phones", response_model=scam_schema.ScamCheckResponse)
def check_phones(
    request: scam_schema.ScamCheckPhonesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    normalized_phones = list(set([normalize_phone(p) for p in request.phones]))
    scam_entries = db.query(ScamNumber).filter(ScamNumber.phone.in_(normalized_phones)).all()
    scam_map = {entry.phone: entry for entry in scam_entries}
    
    user_entries = db.query(User).filter(User.phone.in_(normalized_phones)).all()
    user_map = {entry.phone: entry for entry in user_entries}
    
    results = []
    processed_phones = set()
    
    for phone in request.phones:
        norm = normalize_phone(phone)
        if norm in processed_phones:
            continue
        
        processed_phones.add(norm)
        db_scam = scam_map.get(norm)
        db_user = user_map.get(norm)
        
        if db_scam:
            # Determine if scaffolded as scam or spam based on risk_level
            t = "scam" if db_scam.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL") else "spam"
            results.append({
                "phone": phone,
                "type": t,
                "scam_info": {
                    "scam_type": db_scam.scam_type,
                    "risk_level": db_scam.risk_level,
                    "reports": db_scam.reportCount,
                    "ai_confidence": 0.0
                },
                "user_info": None
            })
        elif db_user:
            results.append({
                "phone": phone,
                "type": "normal",
                "scam_info": None,
                "user_info": {
                    "fullName": db_user.fullName,
                    "email": db_user.email,
                    "birthday": db_user.birthday,
                    "gender": db_user.gender,
                    "is_verified": db_user.is_verified
                }
            })
        else:
            results.append({
                "phone": phone,
                "type": "unknown",
                "scam_info": None,
                "user_info": None
            })
            
    return {"results": results}

@router.post("/check-conversations", response_model=scam_schema.ScamCheckResponse)
def check_conversations(
    request: scam_schema.ScamCheckConversationsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    all_phones = [c.phone for c in request.conversations]
    normalized_phones = list(set([normalize_phone(p) for p in all_phones]))
    
    scam_entries = db.query(ScamNumber).filter(ScamNumber.phone.in_(normalized_phones)).all()
    scam_map = {entry.phone: entry for entry in scam_entries}
    
    user_entries = db.query(User).filter(User.phone.in_(normalized_phones)).all()
    user_map = {entry.phone: entry for entry in user_entries}
    
    results = []
    processed_phones = set()
    
    for conv in request.conversations:
        norm = normalize_phone(conv.phone)
        processed_phones.add(norm)
        db_scam = scam_map.get(norm)
        db_user = user_map.get(norm)
        
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
            scam_enum_vals = ["INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER"]
            raw_type = str(ai_res.get("scam_type", "OTHER")).upper()
            scam_type = raw_type if raw_type in scam_enum_vals else "OTHER"
            risk_level = str(ai_res.get("risk_level", "MEDIUM")).upper()
            confidence = ai_res.get("confidence", 0.0)
            
        if is_scam:
            t = "scam" if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL") else "spam"
            results.append({
                "phone": conv.phone,
                "type": t,
                "scam_info": {
                    "scam_type": scam_type,
                    "risk_level": risk_level,
                    "reports": reports,
                    "ai_confidence": confidence
                },
                "user_info": None
            })
        elif db_user:
            results.append({
                "phone": conv.phone,
                "type": "normal",
                "scam_info": None,
                "user_info": {
                    "fullName": db_user.fullName,
                    "email": db_user.email,
                    "birthday": db_user.birthday,
                    "gender": db_user.gender,
                    "is_verified": db_user.is_verified
                }
            })
        else:
            results.append({
                "phone": conv.phone,
                "type": "unknown",
                "scam_info": None,
                "user_info": None
            })
            
    return {"results": results}

@router.post("/report", response_model=scam_schema.ScamReportResponse)
def report_scam(
    report_in: scam_schema.ScamReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device)
):
    norm_phone = normalize_phone(report_in.phone)
    
    # 1. Look up in both DB tables first
    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    
    if scam_num:
        # Vẫn tăng biến đếm và lưu log report của user hiện tại
        scam_num.reportCount += 1
        report_log = ScamReport(
            phone=norm_phone,
            deviceId=current_device.deviceId,
            reportType=report_in.type,
            description=report_in.description,
            evidence_urls=report_in.evidence_urls,
            messages=report_in.messages
        )
        db.add(report_log)
        db.commit()
        db.refresh(report_log)
        
        return {
            "success": True,
            "message": "Cảm ơn bạn đã báo cáo. Số điện thoại này đã nằm trong danh sách đen, chúng tôi đã ghi nhận thêm.",
            "report_id": str(report_log.id),
            "action_taken": "REPORT_COUNT_INCREMENTED",
            "updated_risk_level": scam_num.risk_level
        }
        
    # 2. Nếu chưa có trong danh sách đen -> Dùng AI check phone hoặc tin nhắn
    ai_result = ai_service.analyze_scam_report(
        description=report_in.description or "",
        messages=report_in.messages or [],
        evidence_urls=report_in.evidence_urls or []
    )
    
    # Lưu report log chung để Admin theo dõi
    report_log = ScamReport(
        phone=norm_phone,
        deviceId=current_device.deviceId,
        reportType=report_in.type,
        description=report_in.description,
        evidence_urls=report_in.evidence_urls,
        messages=report_in.messages
    )
    db.add(report_log)
    
    # Xác định theo AI
    is_scam = ai_result.get("is_scam", True) if ai_result else True
    
    if is_scam:
        # Lừa đảo hoặc spam -> Lưu vào dữ liệu lừa đảo hoặc spam theo dữ liệu AI
        scam_enum_vals = ["INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER"]
        raw_type_in = ai_result.get("scam_type", report_in.type) if ai_result else report_in.type
        raw_type = str(raw_type_in).upper()
        scam_type = raw_type if raw_type in scam_enum_vals else "OTHER"
            
        risk_level = str(ai_result.get("risk_level", "MEDIUM") if ai_result else "MEDIUM").upper()

        new_scam_num = ScamNumber(
            phone=norm_phone, 
            scam_type=scam_type, 
            risk_level=risk_level,
            reportCount=1,
            is_ai_vetted=True,
            metadata_info=ai_result
        )
        db.add(new_scam_num)
        db.commit()
        db.refresh(report_log)
        
        return {
            "success": True,
            "message": "Báo cáo thành công. Hệ thống AI xác nhận đây là số có rủi ro lừa đảo/làm phiền và đã thêm vào danh sách đen.",
            "report_id": str(report_log.id),
            "action_taken": "AI_EVALUATED_AND_ADDED",
            "updated_risk_level": risk_level
        }
    else:
        # Không làm gì nữa (Không ghi vào bảng ScamNumber blacklist)
        db.commit()
        db.refresh(report_log)
        
        return {
            "success": True,
            "message": "Đã ghi nhận báo cáo. Hệ thống AI đánh giá rủi ro thấp, số này sẽ được đưa vào diện theo dõi thêm.",
            "report_id": str(report_log.id),
            "action_taken": "LOGGED_ONLY",
            "updated_risk_level": None
        }

@router.get("/{phone}", response_model=scam_schema.ScamCheckResult)
def get_scam_detail(
    phone: str,
    db: Session = Depends(get_db)
):
    norm_phone = normalize_phone(phone)
    scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
    db_user = db.query(User).filter(User.phone == norm_phone).first()
    
    if scam_num:
        t = "scam" if scam_num.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL") else "spam"
        return {
            "phone": phone,
            "type": t,
            "scam_info": {
                "scam_type": scam_num.scam_type,
                "risk_level": scam_num.risk_level,
                "reports": scam_num.reportCount,
                "ai_confidence": 0.0
            },
            "user_info": None
        }
    elif db_user:
        return {
            "phone": phone,
            "type": "normal",
            "scam_info": None,
            "user_info": {
                "fullName": db_user.fullName,
                "email": db_user.email,
                "birthday": db_user.birthday,
                "gender": db_user.gender,
                "is_verified": db_user.is_verified
            }
        }
    
    return {
        "phone": phone,
        "type": "unknown",
        "scam_info": None,
        "user_info": None
    }
