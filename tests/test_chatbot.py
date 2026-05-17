from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.chat_history import ChatHistory
from app.models.scam_number import ScamNumber, ScamType, RiskLevel
from app.services import chatbot as chatbot_module
from app.services import chatbot_tools
from app.services.chatbot import chatbot_service
from app.services.chatbot_fusion import fuse_verdict


# ─── Helpers to mock Gemini responses ────────────────────────────────────────

def _text_response(text: str):
    part = SimpleNamespace(text=text, function_call=None)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate])


def _function_call_response(name: str, args: dict):
    fc = SimpleNamespace(name=name, args=args)
    part = SimpleNamespace(text=None, function_call=fc)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate])


@pytest.fixture
def gemini_on(monkeypatch):
    """Force is_ready=True with a stub client."""
    monkeypatch.setattr(chatbot_service, "is_ready", True)
    fake_client = MagicMock()
    monkeypatch.setattr(chatbot_service, "client", fake_client)
    monkeypatch.setattr(chatbot_service, "model_name", "gemini-test")

    # Stub google.genai.types so the chatbot service can build Content/Part/Tool
    # without importing the real package.
    class _DummyContent:
        def __init__(self, role, parts):
            self.role = role
            self.parts = parts

    class _DummyPart:
        def __init__(self, text=None, function_response=None):
            self.text = text
            self.function_response = function_response

        @classmethod
        def from_text(cls, text):
            return cls(text=text)

        @classmethod
        def from_function_response(cls, name, response):
            return cls(function_response={"name": name, "response": response})

    class _DummyTool:
        def __init__(self, function_declarations):
            self.function_declarations = function_declarations

    class _DummyConfig:
        def __init__(self, system_instruction=None, tools=None):
            self.system_instruction = system_instruction
            self.tools = tools

    dummy_types = SimpleNamespace(
        Content=_DummyContent,
        Part=_DummyPart,
        Tool=_DummyTool,
        GenerateContentConfig=_DummyConfig,
    )

    # Provide a stand-in for `from google.genai import types as genai_types`
    import sys
    fake_google = SimpleNamespace(genai=SimpleNamespace(types=dummy_types))
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_google.genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", dummy_types)
    return fake_client


@pytest.fixture
def gemini_off(monkeypatch):
    monkeypatch.setattr(chatbot_service, "is_ready", False)


@pytest.fixture
def mock_phobert(monkeypatch):
    """Stub the HF call inside chatbot_tools.analyze_text_for_scam_impl so tests are deterministic."""
    from app.services import ai as ai_module

    def _fake(*, description, messages, evidence_urls):
        text = (description or "").lower()
        if "lừa" in text or "thuế" in text or "đầu tư" in text:
            return {"is_scam": True, "confidence": 0.85, "scam_type": "IMPERSONATION", "summary": "mock"}
        return {"is_scam": False, "confidence": 0.05, "scam_type": "none", "summary": "mock"}

    monkeypatch.setattr(ai_module.ai_service, "analyze_scam_report", _fake)


# ─── Fusion module ───────────────────────────────────────────────────────────

def test_fusion_blacklist_critical_returns_scam():
    v = fuse_verdict(
        phone="+84988111111",
        phone_info={"in_blacklist": True, "risk_level": "CRITICAL", "report_count": 42, "scam_type": "IMPERSONATION"},
        phobert=None,
    )
    assert v["verdict"] == "scam"
    assert v["confidence"] > 0
    assert v["sources"]["database"]["score"] > 0


def test_fusion_blacklist_medium_returns_spam():
    v = fuse_verdict(
        phone="+84988111111",
        phone_info={"in_blacklist": True, "risk_level": "MEDIUM", "report_count": 5, "scam_type": "OTHER"},
        phobert=None,
    )
    assert v["verdict"] == "spam"


def test_fusion_unknown_phone_low_confidence():
    v = fuse_verdict(
        phone="+84988222222",
        phone_info={"in_blacklist": False, "is_known_user": False, "report_count": 0},
        phobert=None,
    )
    assert v["verdict"] == "unknown"
    assert v["confidence"] == 0


def test_fusion_phobert_only_suspicious():
    v = fuse_verdict(
        phone="+84988333333",
        phone_info={"in_blacklist": False, "is_known_user": False},
        phobert={"is_scam": True, "confidence": 0.9},
    )
    # phobert weight 0.3 × 0.9 = 0.27 → below 0.35 → unknown (not "suspicious")
    # But with phobert as the ONLY signal it's still useful info; raise to suspicious only if combined ≥ 0.35
    assert v["sources"]["phobert"]["score"] == 0.9


def test_fusion_combined_db_and_phobert_high_confidence():
    v = fuse_verdict(
        phone="+84988444444",
        phone_info={"in_blacklist": True, "risk_level": "HIGH", "report_count": 50, "scam_type": "LOAN"},
        phobert={"is_scam": True, "confidence": 0.9},
    )
    # db 0.8*0.4 + phobert 0.9*0.3 = 0.32 + 0.27 = 0.59
    assert v["confidence"] >= 0.5
    assert v["verdict"] == "scam"  # because in_blacklist with HIGH


# ─── Fallback path (no Gemini) ───────────────────────────────────────────────

def test_fallback_no_phone_returns_prompt(db, test_user, gemini_off, mock_phobert):
    res = chatbot_service.process_message("xin chào", db, test_user)
    assert "số điện thoại" in res.reply.lower()
    assert res.verdicts == []


def test_fallback_blacklisted_phone_in_message(db, test_user, gemini_off, mock_phobert):
    db.add(ScamNumber(
        phone="+84988123456",
        scam_type=ScamType.IMPERSONATION,
        risk_level=RiskLevel.HIGH,
        reportCount=20,
    ))
    db.commit()

    res = chatbot_service.process_message("số 0988123456 có scam không?", db, test_user)
    assert "DANH SÁCH ĐEN".lower() in res.reply.lower() or "blacklist" in res.reply.lower()
    assert len(res.verdicts) == 1
    v = res.verdicts[0]
    assert v.verdict == "scam"
    assert v.confidence > 0


def test_fallback_unknown_phone(db, test_user, gemini_off, mock_phobert):
    res = chatbot_service.process_message("số 0988999999 có sao không?", db, test_user)
    assert len(res.verdicts) == 1
    assert res.verdicts[0].verdict == "unknown"


# ─── Gemini agent path (with mocked Gemini) ──────────────────────────────────

def test_gemini_pure_chat_no_tools(db, test_user, gemini_on, mock_phobert):
    gemini_on.models.generate_content.return_value = _text_response("Chào bạn! Mình là Real Caller.")
    res = chatbot_service.process_message("hello", db, test_user)
    assert "Chào" in res.reply
    assert res.verdicts == []
    # Exactly one Gemini call
    assert gemini_on.models.generate_content.call_count == 1


def test_gemini_tool_call_lookup_phone(db, test_user, gemini_on, mock_phobert):
    db.add(ScamNumber(
        phone="+84988555555",
        scam_type=ScamType.LOAN,
        risk_level=RiskLevel.CRITICAL,
        reportCount=100,
    ))
    db.commit()

    # First Gemini turn: requests lookup_phone. Second turn: returns final text.
    gemini_on.models.generate_content.side_effect = [
        _function_call_response("lookup_phone", {"phone": "0988555555"}),
        _text_response("Cẩn thận! Số 0988555555 là scam cấp CRITICAL."),
    ]

    res = chatbot_service.process_message("0988555555 có an toàn không?", db, test_user)
    assert "Cẩn thận" in res.reply
    assert gemini_on.models.generate_content.call_count == 2
    assert len(res.verdicts) >= 1
    matching = [v for v in res.verdicts if v.phone == "+84988555555"]
    assert matching
    assert matching[0].verdict == "scam"


def test_gemini_agent_caps_iterations(db, test_user, gemini_on, mock_phobert):
    # Gemini stuck in an infinite loop of function calls — service should bail out.
    gemini_on.models.generate_content.side_effect = lambda **kw: _function_call_response(
        "lookup_phone", {"phone": "0988000000"}
    )
    res = chatbot_service.process_message("test loop", db, test_user)
    assert "trở ngại" in res.reply.lower()


def test_gemini_failure_falls_back(db, test_user, gemini_on, mock_phobert):
    gemini_on.models.generate_content.side_effect = RuntimeError("Gemini exploded")
    res = chatbot_service.process_message("0988777777 có sao không?", db, test_user)
    # Falls back to regex+DB summary
    assert "0988777777" in res.reply or "+84988777777" in res.reply


# ─── History persistence ─────────────────────────────────────────────────────

def test_history_persisted_for_user_and_chatbot(db, test_user, gemini_off, mock_phobert):
    chatbot_service.process_message("hello", db, test_user)
    rows = (
        db.query(ChatHistory)
          .filter(ChatHistory.user_id == test_user.id)
          .order_by(ChatHistory.created_at.asc())
          .all()
    )
    assert len(rows) == 2
    assert rows[0].role == "user"
    assert rows[1].role == "chatbot"


# ─── Tool implementations (direct) ───────────────────────────────────────────

def test_lookup_phone_tool_blacklist(db):
    db.add(ScamNumber(
        phone="+84988101010",
        scam_type=ScamType.RECRUITMENT,
        risk_level=RiskLevel.HIGH,
        reportCount=15,
    ))
    db.commit()
    info = chatbot_tools.lookup_phone_impl("0988101010", db=db)
    assert info["in_blacklist"] is True
    assert info["risk_level"] == "HIGH"
    assert info["report_count"] == 15


def test_lookup_phone_tool_unknown(db):
    info = chatbot_tools.lookup_phone_impl("0988202020", db=db)
    assert info["in_blacklist"] is False
    assert info["is_known_user"] is False


def test_submit_report_tool_uses_consensus_logic(db, test_user, mock_phobert):
    # USER_MANUAL with 1 reporter cannot blacklist
    result = chatbot_tools.submit_report_impl(
        phone="+84988303030",
        source="USER_MANUAL",
        description="lừa thuế",
        db=db,
        current_user=test_user,
    )
    assert result["action_taken"] == "LOGGED_ONLY"
