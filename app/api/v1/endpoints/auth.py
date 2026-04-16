from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.models.user import User
from app.models.device import Device
from app.core.security import create_access_token
from app.services.utils import normalize_phone
import firebase_admin.auth

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
def login_with_firebase(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    # Verify Firebase token
    try:
        decoded_token = firebase_admin.auth.verify_id_token(request.idToken)
        raw_phone = decoded_token.get("phone_number")
        if not raw_phone:
            raise HTTPException(status_code=400, detail="No phone number found in Firebase token")
    except Exception as e:
        # Trong môi trường dev, nếu chưa có firebase json, user có thể bypass bằng hardcode (nếu bạn cần).
        # Nhưng ở đây ta cứ catch exception và báo lỗi.
        raise HTTPException(status_code=401, detail=f"Invalid Firebase Token: {str(e)}")
        
    phone = normalize_phone(raw_phone)
    
    # Check if User exists
    user = db.query(User).filter(User.phone == phone).first()
    needs_update = False
    
    if not user:
        user = User(phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)
        needs_update = True
    else:
        if not user.fullName:
            needs_update = True
            
    # Link Device
    device = db.query(Device).filter(Device.deviceId == request.deviceId).first()
    if not device:
        device = Device(
            deviceId=request.deviceId, 
            platform=request.platform, 
            user_id=user.id,
            phone=phone # keeping this for backward compatibility
        )
        db.add(device)
    else:
        device.user_id = user.id
        device.platform = request.platform
        device.phone = phone
    
    db.commit()
    
    # Create System JWT
    access_token = create_access_token(subject=str(user.id))
    
    return {
        "accessToken": access_token,
        "tokenType": "bearer",
        "needsProfileUpdate": needs_update
    }
