def test_get_profile_returns_current_user(authed_client, test_user):
    res = authed_client.get("/api/v1/user/profile")
    assert res.status_code == 200
    body = res.json()
    assert body["phone"] == test_user.phone
    assert body["fullName"] == test_user.fullName
    # is_verified should NOT be in the response anymore
    assert "is_verified" not in body


def test_update_profile_partial(authed_client, db, test_user):
    res = authed_client.put(
        "/api/v1/user/profile",
        json={"fullName": "New Name", "email": "new@example.com"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["fullName"] == "New Name"
    assert body["email"] == "new@example.com"

    db.refresh(test_user)
    assert test_user.fullName == "New Name"
    assert test_user.email == "new@example.com"


def test_update_profile_ignores_none_fields(authed_client, db, test_user):
    original_email = test_user.email
    res = authed_client.put(
        "/api/v1/user/profile",
        json={"fullName": "Solo Update"},
    )
    assert res.status_code == 200
    db.refresh(test_user)
    assert test_user.fullName == "Solo Update"
    assert test_user.email == original_email
