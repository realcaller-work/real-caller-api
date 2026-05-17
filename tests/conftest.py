import os
import sys
from pathlib import Path

# Ensure project root on sys.path BEFORE app import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Provide minimal env so settings load without a real .env
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
os.environ.setdefault("HF_TOKEN", "")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("FIREBASE_CREDENTIALS_JSON", "")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.models.base import Base  # noqa: E402
# Import all models so metadata sees them
from app.models import user as _user_model  # noqa: F401,E402
from app.models import device as _device_model  # noqa: F401,E402
from app.models import scam_number as _scam_number_model  # noqa: F401,E402
from app.models import scam_report as _scam_report_model  # noqa: F401,E402
from app.models import chat_history as _chat_history_model  # noqa: F401,E402
from app.models.user import User  # noqa: E402
from app.api.deps import get_current_user  # noqa: E402


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def TestSession(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db(TestSession):
    s = TestSession()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client(TestSession):
    def _override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def test_user(db):
    user = User(phone="+84900000001", fullName="Test User", email="test@example.com")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def authed_client(client, test_user):
    """A TestClient whose get_current_user resolves test_user from the request's own DB session."""
    from fastapi import Depends as _Depends
    from sqlalchemy.orm import Session as _Session

    phone = test_user.phone

    def _override_with_session(db: _Session = _Depends(get_db)):
        return db.query(User).filter(User.phone == phone).first()

    app.dependency_overrides[get_current_user] = _override_with_session
    yield client
    app.dependency_overrides.pop(get_current_user, None)
