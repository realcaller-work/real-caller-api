from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.schemas.user import UserProfileUpdate, UserProfileResponse
from app.models.user import User

router = APIRouter()

@router.get("/profile", response_model=UserProfileResponse)
def get_user_profile(
    current_user: User = Depends(get_current_user)
):
    return current_user

@router.put("/profile", response_model=UserProfileResponse)
def update_user_profile(
    user_in: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if user_in.fullName is not None:
        current_user.fullName = user_in.fullName
    if user_in.avatar is not None:
        current_user.avatar = user_in.avatar
    if user_in.email is not None:
        current_user.email = user_in.email
    if user_in.birthday is not None:
        current_user.birthday = user_in.birthday
    if user_in.gender is not None:
        current_user.gender = user_in.gender

    db.commit()
    db.refresh(current_user)
    return current_user
