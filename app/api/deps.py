from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.user import User
from app.models.device import Device

security = HTTPBearer()

def decode_token(auth: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = auth.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise HTTPException(status_code=401, detail="Invalid auth token")
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user_id(payload: dict = Depends(decode_token)) -> str:
    return str(payload["sub"])

def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def get_current_device(
    payload: dict = Depends(decode_token),
    db: Session = Depends(get_db)
) -> Device:
    subject = str(payload.get("sub"))
    
    # Try to find user first
    user = db.query(User).filter(User.id == subject).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get the latest device for this user
    device = db.query(Device).filter(Device.user_id == user.id).order_by(Device.lastActive.desc()).first()
    
    if not device:
        # If no device exists, create a default one to avoid foreign key errors
        device = Device(
            deviceId=f"default-{user.id}",
            user_id=user.id,
            platform="OTHER"
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        
    return device
