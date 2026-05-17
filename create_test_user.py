"""Create a test user and print a long-lived token pair for manual API testing.

The access token here is intentionally extended to 30 days so testers don't have to
keep refreshing. Production tokens use the shorter ACCESS_TOKEN_EXPIRE_MINUTES default.
"""
import os
import sys
from datetime import timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
)
from app.db.session import SessionLocal
from app.models.refresh_token import RefreshToken
from app.models.user import User


def create_test_user():
    db: Session = SessionLocal()
    phone = "+84123456789"

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        user = User(
            phone=phone,
            fullName="Baobs Test",
            email="baobs@test.com",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[+] Created new User: {user.id}")
    else:
        print(f"[+] User already exists: {user.id}")

    # Long-lived access token (30 days) for convenience
    access = create_access_token(subject=str(user.id), expires_delta=timedelta(days=30))

    # Refresh token (1 year), stored hashed
    raw_refresh = generate_refresh_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        device_id="MANUAL_TEST_SCRIPT",
        expires_at=refresh_token_expiry(),
    ))
    db.commit()

    print("=" * 72)
    print(f"Phone:        {phone}")
    print(f"User ID:      {user.id}")
    print()
    print("ACCESS TOKEN (30 days, paste as 'Authorization: Bearer <token>'):")
    print(access)
    print()
    print("REFRESH TOKEN (1 year):")
    print(raw_refresh)
    print("=" * 72)


if __name__ == "__main__":
    create_test_user()
