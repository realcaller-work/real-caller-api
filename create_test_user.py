import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.user import User
from app.models.device import Device
from app.core.security import create_access_token

def create_test_user():
    db: Session = SessionLocal()
    phone = "+84123456789"
    
    # Kiem tra neu co roi
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        user = User(
            phone=phone,
            fullName="Baobs Test",
            email="baobs@test.com",
            is_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print("Created new User:", user.id)
    else:
        print("User already exists:", user.id)
        
    token = create_access_token(subject=str(user.id))
    print("=" * 40)
    print("Phone:", phone)
    print("ACCESS TOKEN:")
    print(token)
    print("=" * 40)

if __name__ == "__main__":
    create_test_user()
