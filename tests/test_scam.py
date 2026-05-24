from app.models.scam_number import ScamNumber, ScamType, RiskLevel
from app.models.scam_report import ScamReport, ReportSource
from app.models.user import User
from app.services import ai as ai_module


def _mock_ai(monkeypatch, *, is_scam: bool, confidence: float, scam_type: str = "OTHER"):
    monkeypatch.setattr(
        ai_module.ai_service,
        "analyze_scam_report",
        lambda **kw: {
            "is_scam": is_scam,
            "scam_type": scam_type,
            "risk_level": "MEDIUM",
            "confidence": confidence,
        },
    )


def test_check_phones_known_scam(authed_client, db):
    db.add(ScamNumber(
        phone="+84988888888",
        scam_type=ScamType.IMPERSONATION,
        risk_level=RiskLevel.CRITICAL,
        reportCount=42,
    ))
    db.commit()

    res = authed_client.post(
        "/api/v1/scam/check-phones",
        json={"phones": ["+84988888888"]},
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert len(results) == 1
    r = results[0]
    assert r["phone"] == "+84988888888"
    assert r["type"] == "scam"
    assert r["scam_info"]["reports"] == 42
    assert r["scam_info"]["risk_level"] == "CRITICAL"


def test_check_phones_normal_user_excludes_is_verified(authed_client, db):
    db.add(User(phone="+84977777777", fullName="Real User"))
    db.commit()

    res = authed_client.post(
        "/api/v1/scam/check-phones",
        json={"phones": ["+84977777777"]},
    )
    assert res.status_code == 200
    r = res.json()["results"][0]
    assert r["type"] == "normal"
    assert r["user_info"]["fullName"] == "Real User"
    # The dropped field must NOT appear in response
    assert "is_verified" not in r["user_info"]


def test_check_phones_unknown(authed_client):
    res = authed_client.post(
        "/api/v1/scam/check-phones",
        json={"phones": ["+84966666666"]},
    )
    assert res.status_code == 200
    assert res.json()["results"][0]["type"] == "unknown"


def test_check_phones_deduplicates_normalized_input(authed_client, db):
    db.add(ScamNumber(
        phone="+84912345678", scam_type=ScamType.OTHER,
        risk_level=RiskLevel.LOW, reportCount=1,
    ))
    db.commit()

    res = authed_client.post(
        "/api/v1/scam/check-phones",
        json={"phones": ["0912345678", "+84912345678", "84912345678"]},
    )
    assert res.status_code == 200
    # All three normalize to same number; dedup keeps one
    assert len(res.json()["results"]) == 1


def test_check_conversations_uses_ai_for_unknown_phone(authed_client, monkeypatch):
    monkeypatch.setattr(
        ai_module.ai_service,
        "analyze_scam_report",
        lambda **kw: {
            "is_scam": True,
            "scam_type": "IMPERSONATION",
            "risk_level": "HIGH",
            "confidence": 0.9,
        },
    )
    res = authed_client.post(
        "/api/v1/scam/check-conversations",
        json={
            "conversations": [
                {
                    "phone": "+84955555555",
                    "messages": [{"sender": "X", "content": "tải app công an apk này về"}],
                }
            ]
        },
    )
    assert res.status_code == 200
    r = res.json()["results"][0]
    assert r["type"] == "scam"
    assert r["scam_info"]["scam_type"] == "IMPERSONATION"
    assert r["scam_info"]["ai_confidence"] == 0.9


def test_check_conversations_skips_ai_when_phone_already_blacklisted(authed_client, db, monkeypatch):
    """If the phone is already in scam_numbers, AI must not be invoked."""
    db.add(ScamNumber(
        phone="+84955500001",
        scam_type=ScamType.LOAN,
        risk_level=RiskLevel.HIGH,
        reportCount=7,
    ))
    db.commit()

    calls = {"n": 0}

    def _spy(**kw):
        calls["n"] += 1
        return {"is_scam": True, "scam_type": "OTHER", "risk_level": "LOW", "confidence": 0.9}

    monkeypatch.setattr(ai_module.ai_service, "analyze_scam_report", _spy)

    res = authed_client.post(
        "/api/v1/scam/check-conversations",
        json={
            "conversations": [
                {
                    "phone": "+84955500001",
                    "messages": [{"sender": "X", "content": "có tin nhắn"}],
                }
            ]
        },
    )
    assert res.status_code == 200
    assert calls["n"] == 0, "AI should be skipped when phone is already on the blacklist"
    r = res.json()["results"][0]
    # DB values win — not the (unrequested) AI ones
    assert r["scam_info"]["risk_level"] == "HIGH"
    assert r["scam_info"]["reports"] == 7


def test_check_conversations_persists_new_scam_when_ai_flags(authed_client, db, monkeypatch):
    """AI flags a fresh phone → must be inserted into scam_numbers."""
    _mock_ai(monkeypatch, is_scam=True, confidence=0.85, scam_type="IMPERSONATION")
    # Override risk_level too (mock helper hard-codes MEDIUM)
    monkeypatch.setattr(
        ai_module.ai_service,
        "analyze_scam_report",
        lambda **kw: {
            "is_scam": True,
            "scam_type": "IMPERSONATION",
            "risk_level": "HIGH",
            "confidence": 0.85,
        },
    )

    assert db.query(ScamNumber).filter(ScamNumber.phone == "+84955500002").count() == 0

    res = authed_client.post(
        "/api/v1/scam/check-conversations",
        json={
            "conversations": [
                {
                    "phone": "+84955500002",
                    "messages": [{"sender": "X", "content": "tải app công an apk này về"}],
                }
            ]
        },
    )
    assert res.status_code == 200

    inserted = db.query(ScamNumber).filter(ScamNumber.phone == "+84955500002").first()
    assert inserted is not None, "AI-detected scam should be persisted to scam_numbers"
    assert inserted.scam_type == ScamType.IMPERSONATION
    assert inserted.risk_level == RiskLevel.HIGH


def test_check_conversations_ai_not_scam_does_not_insert(authed_client, db, monkeypatch):
    """AI says not scam → no row added."""
    _mock_ai(monkeypatch, is_scam=False, confidence=0.1)

    res = authed_client.post(
        "/api/v1/scam/check-conversations",
        json={
            "conversations": [
                {
                    "phone": "+84955500003",
                    "messages": [{"sender": "X", "content": "hi"}],
                }
            ]
        },
    )
    assert res.status_code == 200
    assert db.query(ScamNumber).filter(ScamNumber.phone == "+84955500003").count() == 0


def test_report_increments_existing_scam(authed_client, db, monkeypatch):
    db.add(ScamNumber(
        phone="+84944444444",
        scam_type=ScamType.LOAN,
        risk_level=RiskLevel.HIGH,
        reportCount=5,
    ))
    db.commit()

    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84944444444", "type": "LOAN", "description": "lừa vay"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["action_taken"] == "REPORT_COUNT_INCREMENTED"
    assert body["updated_risk_level"] == "HIGH"

    updated = db.query(ScamNumber).filter(ScamNumber.phone == "+84944444444").first()
    assert updated.reportCount == 6
    log = db.query(ScamReport).filter(ScamReport.phone == "+84944444444").one()
    assert log.source == ReportSource.USER_MANUAL  # default when client omits source


def test_report_new_phone_user_manual_high_ai_confidence_blacklists(authed_client, db, monkeypatch):
    # USER_MANUAL trust = 0.4; ai_confidence 0.95 → combined = 0.38 — just below threshold
    # Use 0.99 to ensure crossing 0.4 with weight 0.4 → 0.396, still below…
    # We need confidence >= 1.0 — impossible. So USER_MANUAL alone CANNOT blacklist.
    # Confirm that even very high AI confidence + USER_MANUAL stays LOGGED_ONLY.
    _mock_ai(monkeypatch, is_scam=True, confidence=0.95, scam_type="INVESTMENT")
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84933000001", "source": "USER_MANUAL", "description": "đầu tư"},
    )
    assert res.status_code == 200
    assert res.json()["action_taken"] == "LOGGED_ONLY"
    assert db.query(ScamNumber).filter(ScamNumber.phone == "+84933000001").count() == 0


def test_report_new_phone_sms_inbox_lower_confidence_still_blacklists(authed_client, db, monkeypatch):
    # SMS_INBOX trust = 1.0; ai_confidence 0.5 → combined = 0.5 (>= 0.4 threshold)
    _mock_ai(monkeypatch, is_scam=True, confidence=0.5, scam_type="IMPERSONATION")
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84933000002", "source": "SMS_INBOX", "description": "lừa thuế"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["action_taken"] == "AI_EVALUATED_AND_ADDED"
    assert body["updated_risk_level"] == "MEDIUM"  # combined 0.5 → MEDIUM
    inserted = db.query(ScamNumber).filter(ScamNumber.phone == "+84933000002").first()
    assert inserted is not None
    assert inserted.scam_type == ScamType.IMPERSONATION
    # Source persisted in the report log
    log = db.query(ScamReport).filter(ScamReport.phone == "+84933000002").one()
    assert log.source == ReportSource.SMS_INBOX


def test_report_sms_inbox_max_confidence_marks_critical(authed_client, db, monkeypatch):
    _mock_ai(monkeypatch, is_scam=True, confidence=0.95, scam_type="LOAN")
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84933000003", "source": "SMS_INBOX"},
    )
    assert res.status_code == 200
    assert res.json()["updated_risk_level"] == "CRITICAL"  # combined 0.95 → CRITICAL


def test_report_sms_inbox_promotes_existing_risk_to_critical(authed_client, db, monkeypatch):
    db.add(ScamNumber(
        phone="+84933000004",
        scam_type=ScamType.OTHER,
        risk_level=RiskLevel.MEDIUM,
        reportCount=2,
    ))
    db.commit()

    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84933000004", "source": "SMS_INBOX"},
    )
    assert res.status_code == 200
    assert res.json()["updated_risk_level"] == "CRITICAL"
    updated = db.query(ScamNumber).filter(ScamNumber.phone == "+84933000004").first()
    assert updated.risk_level == RiskLevel.CRITICAL


def test_report_user_manual_does_not_promote_existing_risk(authed_client, db, monkeypatch):
    db.add(ScamNumber(
        phone="+84933000005",
        scam_type=ScamType.OTHER,
        risk_level=RiskLevel.MEDIUM,
        reportCount=2,
    ))
    db.commit()

    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84933000005", "source": "USER_MANUAL"},
    )
    assert res.status_code == 200
    assert res.json()["updated_risk_level"] == "MEDIUM"  # not promoted


def test_report_new_phone_ai_not_scam_only_logged(authed_client, db, monkeypatch):
    _mock_ai(monkeypatch, is_scam=False, confidence=0.1)
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84922000000", "type": "OTHER"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["action_taken"] == "LOGGED_ONLY"
    assert body["updated_risk_level"] is None
    assert db.query(ScamNumber).filter(ScamNumber.phone == "+84922000000").count() == 0
    assert db.query(ScamReport).filter(ScamReport.phone == "+84922000000").count() == 1


def _seed_distinct_reporters(db, phone: str, count: int):
    """Insert `count` ScamReport rows for `phone` each from a different fake user."""
    for i in range(count):
        u = User(phone=f"+8470{phone[-6:]}{i:02d}", fullName=f"Fake{i}")
        db.add(u)
        db.flush()
        db.add(ScamReport(
            phone=phone,
            source=ReportSource.USER_MANUAL,
            user_id=u.id,
        ))
    db.commit()


def test_consensus_path_blacklists_after_5_distinct_reporters(authed_client, db, monkeypatch):
    phone = "+84933000010"
    # 4 prior distinct reporters; this request adds the 5th (test_user)
    _seed_distinct_reporters(db, phone, 4)

    # AI says scam but confidence × USER_MANUAL trust < 0.4 → direct path fails
    _mock_ai(monkeypatch, is_scam=True, confidence=0.5, scam_type="IMPERSONATION")
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": phone, "source": "USER_MANUAL"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["action_taken"] == "AI_EVALUATED_AND_ADDED"
    # Consensus floor is MEDIUM
    assert body["updated_risk_level"] == "MEDIUM"
    assert "cộng đồng" in body["message"].lower()

    entry = db.query(ScamNumber).filter(ScamNumber.phone == phone).first()
    assert entry is not None
    assert entry.reportCount == 5


def test_consensus_blocked_below_threshold(authed_client, db, monkeypatch):
    phone = "+84933000011"
    # Only 3 prior + this one = 4 distinct → below threshold
    _seed_distinct_reporters(db, phone, 3)

    _mock_ai(monkeypatch, is_scam=True, confidence=0.5)
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": phone, "source": "USER_MANUAL"},
    )
    assert res.status_code == 200
    assert res.json()["action_taken"] == "LOGGED_ONLY"
    assert db.query(ScamNumber).filter(ScamNumber.phone == phone).count() == 0


def test_single_user_spam_does_not_trigger_consensus(authed_client, db, monkeypatch):
    phone = "+84933000012"
    _mock_ai(monkeypatch, is_scam=True, confidence=0.5)

    last = None
    for _ in range(7):
        last = authed_client.post(
            "/api/v1/scam/report",
            json={"phone": phone, "source": "USER_MANUAL"},
        )
    assert last.json()["action_taken"] == "LOGGED_ONLY"
    assert db.query(ScamNumber).filter(ScamNumber.phone == phone).count() == 0
    # 7 reports recorded but all from same user → distinct=1
    assert db.query(ScamReport).filter(ScamReport.phone == phone).count() == 7


def test_consensus_requires_ai_agreement(authed_client, db, monkeypatch):
    phone = "+84933000013"
    _seed_distinct_reporters(db, phone, 9)

    # 10 distinct reporters but AI says NOT scam → veto
    _mock_ai(monkeypatch, is_scam=False, confidence=0.05)
    res = authed_client.post(
        "/api/v1/scam/report",
        json={"phone": phone, "source": "USER_MANUAL"},
    )
    assert res.status_code == 200
    assert res.json()["action_taken"] == "LOGGED_ONLY"
    assert db.query(ScamNumber).filter(ScamNumber.phone == phone).count() == 0


def test_report_persists_user_id(authed_client, db, test_user, monkeypatch):
    _mock_ai(monkeypatch, is_scam=False, confidence=0.0)
    authed_client.post(
        "/api/v1/scam/report",
        json={"phone": "+84933000014", "source": "USER_MANUAL"},
    )
    log = db.query(ScamReport).filter(ScamReport.phone == "+84933000014").one()
    assert str(log.user_id) == str(test_user.id)


def test_get_scam_detail_known_scam(authed_client, db):
    db.add(ScamNumber(
        phone="+84911000000", scam_type=ScamType.OTHER,
        risk_level=RiskLevel.HIGH, reportCount=3,
    ))
    db.commit()

    res = authed_client.get("/api/v1/scam/+84911000000")
    assert res.status_code == 200
    assert res.json()["type"] == "scam"


def test_get_scam_detail_medium_risk_falls_through_to_unknown(authed_client, db):
    """MEDIUM risk lives in DB but is hidden from clients."""
    db.add(ScamNumber(
        phone="+84911000001", scam_type=ScamType.OTHER,
        risk_level=RiskLevel.MEDIUM, reportCount=2,
    ))
    db.commit()

    res = authed_client.get("/api/v1/scam/+84911000001")
    assert res.status_code == 200
    # No user, MEDIUM is not surfaced as scam → unknown
    assert res.json()["type"] == "unknown"


def test_get_scam_detail_unknown(authed_client):
    res = authed_client.get("/api/v1/scam/+84900099999")
    assert res.status_code == 200
    assert res.json()["type"] == "unknown"
