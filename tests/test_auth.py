from datetime import datetime, timedelta, timezone

import firebase_admin.auth as fb_auth

from app.core.security import hash_refresh_token
from app.models.device import Device
from app.models.refresh_token import RefreshToken
from app.models.user import User


def _login(client, monkeypatch, phone="+84911111111", device_id="dev-abc"):
    monkeypatch.setattr(fb_auth, "verify_id_token", lambda _t: {"phone_number": phone})
    return client.post(
        "/api/v1/auth/login",
        json={"idToken": "fake-token", "deviceId": device_id},
    )


def test_login_returns_token_pair(client, db, monkeypatch):
    res = _login(client, monkeypatch)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tokenType"] == "bearer"
    assert body["accessToken"]
    assert body["refreshToken"]
    assert body["accessTokenExpiresIn"] > 0
    assert body["needsProfileUpdate"] is True

    user = db.query(User).filter(User.phone == "+84911111111").first()
    assert user is not None
    device = db.query(Device).filter(Device.deviceId == "dev-abc").first()
    assert str(device.user_id) == str(user.id)

    stored = db.query(RefreshToken).filter(RefreshToken.user_id == user.id).all()
    assert len(stored) == 1
    assert stored[0].revoked_at is None
    assert stored[0].token_hash == hash_refresh_token(body["refreshToken"])
    assert stored[0].device_id == "dev-abc"


def test_login_existing_user_no_profile_update(client, db, monkeypatch):
    db.add(User(phone="+84922222222", fullName="Existing"))
    db.commit()
    res = _login(client, monkeypatch, phone="+84922222222", device_id="dev-xyz")
    assert res.status_code == 200
    assert res.json()["needsProfileUpdate"] is False


def test_login_fails_when_firebase_token_invalid(client, monkeypatch):
    def _raise(_t):
        raise ValueError("bad token")
    monkeypatch.setattr(fb_auth, "verify_id_token", _raise)
    res = client.post(
        "/api/v1/auth/login",
        json={"idToken": "broken", "deviceId": "dev-1"},
    )
    assert res.status_code == 401


def test_login_fails_when_no_phone_in_token(client, monkeypatch):
    monkeypatch.setattr(fb_auth, "verify_id_token", lambda _t: {})
    res = client.post(
        "/api/v1/auth/login",
        json={"idToken": "fake", "deviceId": "dev-1"},
    )
    assert res.status_code == 400


def test_refresh_rotates_token(client, db, monkeypatch):
    res = _login(client, monkeypatch)
    old_refresh = res.json()["refreshToken"]
    old_access = res.json()["accessToken"]

    res2 = client.post("/api/v1/auth/refresh", json={"refreshToken": old_refresh})
    assert res2.status_code == 200, res2.text
    body = res2.json()
    assert body["refreshToken"] != old_refresh
    assert body["accessToken"]

    # Old refresh now revoked
    old_record = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(old_refresh)
    ).first()
    assert old_record is not None
    assert old_record.revoked_at is not None

    # New refresh exists, not revoked
    new_record = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(body["refreshToken"])
    ).first()
    assert new_record is not None
    assert new_record.revoked_at is None


def test_refresh_with_revoked_token_fails(client, monkeypatch):
    res = _login(client, monkeypatch)
    rt = res.json()["refreshToken"]

    # Use once → revokes it
    client.post("/api/v1/auth/refresh", json={"refreshToken": rt})
    # Use again → must fail
    res2 = client.post("/api/v1/auth/refresh", json={"refreshToken": rt})
    assert res2.status_code == 401


def test_refresh_with_unknown_token_fails(client):
    res = client.post("/api/v1/auth/refresh", json={"refreshToken": "no-such-token"})
    assert res.status_code == 401


def test_refresh_with_expired_token_fails(client, db, monkeypatch):
    res = _login(client, monkeypatch)
    rt = res.json()["refreshToken"]

    record = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(rt)
    ).first()
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    res2 = client.post("/api/v1/auth/refresh", json={"refreshToken": rt})
    assert res2.status_code == 401


def test_logout_revokes_refresh_token(client, db, monkeypatch):
    res = _login(client, monkeypatch)
    rt = res.json()["refreshToken"]

    logout = client.post("/api/v1/auth/logout", json={"refreshToken": rt})
    assert logout.status_code == 200
    assert logout.json()["success"] is True

    record = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(rt)
    ).first()
    assert record.revoked_at is not None

    # Subsequent refresh attempt must fail
    res2 = client.post("/api/v1/auth/refresh", json={"refreshToken": rt})
    assert res2.status_code == 401


def test_logout_is_idempotent_for_unknown_token(client):
    res = client.post("/api/v1/auth/logout", json={"refreshToken": "non-existent"})
    assert res.status_code == 200
    assert res.json()["success"] is True
