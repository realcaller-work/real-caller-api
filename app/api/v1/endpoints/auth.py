from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    LogoutRequest,
    LogoutResponse,
)
from app.models.user import User
from app.models.device import Device
from app.models.refresh_token import RefreshToken
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
)
from app.services.utils import normalize_phone
import firebase_admin.auth

router = APIRouter()


def _issue_token_pair(db: Session, user: User, device_id: str | None) -> dict:
    """Create a fresh access JWT + opaque refresh token (stored hashed)."""
    access = create_access_token(subject=str(user.id))
    raw_refresh = generate_refresh_token()

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        device_id=device_id,
        expires_at=refresh_token_expiry(),
    ))

    return {
        "accessToken": access,
        "refreshToken": raw_refresh,
        "tokenType": "bearer",
        "accessTokenExpiresIn": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/login", response_model=LoginResponse)
def login_with_firebase(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    try:
        decoded_token = firebase_admin.auth.verify_id_token(request.idToken)
        raw_phone = decoded_token.get("phone_number")
        if not raw_phone:
            raise HTTPException(status_code=400, detail="No phone number found in Firebase token")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Firebase Token: {str(e)}")

    phone = normalize_phone(raw_phone)

    user = db.query(User).filter(User.phone == phone).first()
    needs_update = False
    if not user:
        user = User(phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)
        needs_update = True
    elif not user.fullName:
        needs_update = True

    device = db.query(Device).filter(Device.deviceId == request.deviceId).first()
    if not device:
        device = Device(deviceId=request.deviceId, user_id=user.id)
        db.add(device)
    else:
        device.user_id = user.id

    tokens = _issue_token_pair(db, user, request.deviceId)
    db.commit()

    return {**tokens, "needsProfileUpdate": needs_update}


@router.post("/refresh", response_model=RefreshResponse)
def refresh_session(
    request: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Rotate the refresh token: revoke the old one and issue a fresh pair."""
    token_hash = hash_refresh_token(request.refreshToken)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if record is None or record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Compare both sides as timezone-aware UTC to avoid naive/aware mix.
    expiry = record.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.query(User).filter(User.id == record.user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")

    record.revoked_at = datetime.now(timezone.utc)
    tokens = _issue_token_pair(db, user, record.device_id)
    db.commit()

    return tokens


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: LogoutRequest,
    db: Session = Depends(get_db),
):
    """Revoke a refresh token. Idempotent — unknown / already-revoked tokens still return success."""
    token_hash = hash_refresh_token(request.refreshToken)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"success": True}
