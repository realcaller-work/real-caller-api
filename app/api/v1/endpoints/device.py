from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.device import Device
from app.schemas import device as device_schema
from app.core.security import create_access_token

router = APIRouter()

@router.post("/register", response_model=device_schema.Token)
def register_device(
    device_in: device_schema.DeviceCreate,
    db: Session = Depends(get_db)
):
    device = db.query(Device).filter(Device.deviceId == device_in.deviceId).first()
    if not device:
        device = Device(
            deviceId=device_in.deviceId,
            platform=device_in.platform,
            phone=device_in.phone
        )
        db.add(device)
        db.commit()
        db.refresh(device)
    else:
        # Update phone if it changed
        if device_in.phone and device.phone != device_in.phone:
            device.phone = device_in.phone
            db.commit()
            db.refresh(device)
    
    access_token = create_access_token(subject=device.deviceId)
    return {"accessToken": access_token, "tokenType": "bearer"}
