from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.chat_history import ChatHistory
from app.models.scam_number import ScamNumber, ScamType, RiskLevel
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
    """Force is_ready=True with a stub client + stub google.genai.types."""
    monkeypatch.setattr(chatbot_service, "is_ready", True)
    fake_client = MagicMock()
    monkeypatch.setattr(chatbot_service, "client", fake_client)
    monkeypatch.setattr(chatbot_service, "model_name", "gemini-test")

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
    """Stub the HF call so analyze_text_for_scam is deterministic."""
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


def test_fusion_blacklist_medium_returns_spam():
    v = fuse_verdict(
        phone="+84988111111",
        phone_info={"in_blacklist": True, "risk_level": "MEDIUM", "report_count": 5, "scam_type": "OTHER"},
        phobert=None,
    )
    assert v["verdict"] == "spam"


def test_fusion_unknown_phone():
    v = fuse_verdict(
        phone="+84988222222",
        phone_info={"in_blacklist": False, "is_known_user": False, "report_count": 0},
        phobert=None,
    )
    assert v["verdict"] == "unknown"


# ─── Chat-first behavior (Gemini path) ───────────────────────────────────────

def test_small_talk_no_tool_no_verdict(db, test_user, gemini_on, mock_phobert):
    """Just chatting — Gemini replies directly, no tool calls, no phone verdicts."""
    gemini_on.models.generate_content.return_value = _text_response("Chào bạn! Hôm nay thế nào?")
    res = chatbot_service.process_message("hello", db, test_user)
    assert res.reply.startswith("Chào")
    assert res.verdicts == []
    assert gemini_on.models.generate_content.call_count == 1


def test_phone_mentioned_in_chat_no_check_no_verdict(db, test_user, gemini_on, mock_phobert):
    """User mentions a phone in passing without asking to check it — no verdict."""
    db.add(ScamNumber(
        phone="+84988123456",
        scam_type=ScamType.LOAN,
        risk_level=RiskLevel.HIGH,
        reportCount=10,
    ))
    db.commit()

    gemini_on.models.generate_content.return_value = _text_response(
        "Ok, chúc bạn dùng số mới vui vẻ nhé!"
    )
    res = chatbot_service.process_message(
        "tôi mới đổi sang số 0988123456", db, test_user
    )
    # Bot replied as normal chat — even though the number IS in blacklist, no verdict
    # because the bot decided no check was requested.
    assert res.verdicts == []
    assert gemini_on.models.generate_content.call_count == 1


def test_explicit_check_request_triggers_lookup(db, test_user, gemini_on, mock_phobert):
    db.add(ScamNumber(
        phone="+84988555555",
        scam_type=ScamType.LOAN,
        risk_level=RiskLevel.CRITICAL,
        reportCount=100,
    ))
    db.commit()

    gemini_on.models.generate_content.side_effect = [
        _function_call_response("lookup_phone", {"phone": "0988555555"}),
        _text_response("Cẩn thận! Số 0988555555 là scam cấp CRITICAL."),
    ]
    res = chatbot_service.process_message(
        "kiểm tra số 0988555555 giúp", db, test_user
    )
    assert "Cẩn thận" in res.reply
    assert len(res.verdicts) == 1
    assert res.verdicts[0].phone == "+84988555555"
    assert res.verdicts[0].verdict == "scam"


def test_explicit_check_unknown_phone_returns_unknown_verdict(db, test_user, gemini_on, mock_phobert):
    gemini_on.models.generate_content.side_effect = [
        _function_call_response("lookup_phone", {"phone": "0988999999"}),
        _text_response("Số này chưa có trong hệ thống của mình."),
    ]
    res = chatbot_service.process_message(
        "0988999999 có lừa đảo không?", db, test_user
    )
    assert len(res.verdicts) == 1
    assert res.verdicts[0].verdict == "unknown"


def test_analyze_text_only_produces_no_phone_verdict(db, test_user, gemini_on, mock_phobert):
    """If only analyze_text_for_scam is called (no phone lookup), no phone verdict."""
    gemini_on.models.generate_content.side_effect = [
        _function_call_response("analyze_text_for_scam", {"text": "Chào anh tôi là cán bộ thuế..."}),
        _text_response("Tin này có dấu hiệu lừa đảo, hãy cảnh giác."),
    ]
    res = chatbot_service.process_message(
        "tin này có scam không: 'Chào anh tôi là cán bộ thuế...'",
        db, test_user,
    )
    assert "lừa đảo" in res.reply
    assert res.verdicts == []  # no phone was looked up


def test_analyze_text_corroborates_phone_lookup(db, test_user, gemini_on, mock_phobert):
    """When BOTH lookup_phone and analyze_text_for_scam happen, phobert signal fuses in."""
    gemini_on.models.generate_content.side_effect = [
        _function_call_response("lookup_phone", {"phone": "0988777777"}),
        _function_call_response("analyze_text_for_scam", {"text": "lừa đảo thuế"}),
        _text_response("Cảnh báo: số này và tin nhắn đều có dấu hiệu scam."),
    ]
    res = chatbot_service.process_message(
        "kiểm tra số 0988777777 với tin 'lừa đảo thuế'", db, test_user
    )
    assert len(res.verdicts) == 1
    v = res.verdicts[0]
    # PhoBERT signal should now be > 0 in the fusion result
    assert v.sources["phobert"]["score"] > 0


def test_gemini_failure_falls_back(db, test_user, gemini_on, mock_phobert):
    """Gemini raises → fall back to phone-checker."""
    gemini_on.models.generate_content.side_effect = RuntimeError("Gemini exploded")
    res = chatbot_service.process_message("0988111000 có scam không?", db, test_user)
    # Fallback always checks any phone in the message
    assert "0988111000" in res.reply or "+84988111000" in res.reply
    assert len(res.verdicts) == 1


def test_gemini_agent_caps_iterations(db, test_user, gemini_on, mock_phobert):
    gemini_on.models.generate_content.side_effect = lambda **kw: _function_call_response(
        "lookup_phone", {"phone": "0988000000"}
    )
    res = chatbot_service.process_message("test loop", db, test_user)
    assert "trở ngại" in res.reply.lower()


# ─── Fallback mode (no Gemini) ───────────────────────────────────────────────

def test_fallback_no_phone_prompts_user(db, test_user, gemini_off, mock_phobert):
    res = chatbot_service.process_message("hello bạn", db, test_user)
    assert "số điện thoại" in res.reply.lower()
    assert res.verdicts == []


def test_fallback_phone_in_message_gets_checked(db, test_user, gemini_off, mock_phobert):
    db.add(ScamNumber(
        phone="+84988600600",
        scam_type=ScamType.IMPERSONATION,
        risk_level=RiskLevel.HIGH,
        reportCount=15,
    ))
    db.commit()
    res = chatbot_service.process_message("0988600600 thế nào?", db, test_user)
    assert "DANH SÁCH ĐEN".lower() in res.reply.lower()
    assert len(res.verdicts) == 1
    assert res.verdicts[0].verdict == "scam"


# ─── History persistence ─────────────────────────────────────────────────────

def test_history_persisted(db, test_user, gemini_off, mock_phobert):
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


# ─── Tool implementations ────────────────────────────────────────────────────

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


def test_submit_report_tool_uses_consensus_logic(db, test_user, mock_phobert):
    result = chatbot_tools.submit_report_impl(
        phone="+84988303030",
        source="USER_MANUAL",
        description="lừa thuế",
        db=db,
        current_user=test_user,
    )
    # USER_MANUAL with 1 reporter → LOGGED_ONLY (consensus path consistency)
    assert result["action_taken"] == "LOGGED_ONLY"
