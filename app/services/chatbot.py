"""Conversational chatbot — chat-first design.

Default behavior is normal conversation. The bot only invokes scam-detection tools
(`lookup_phone`, `analyze_text_for_scam`, `submit_report`) when the user *explicitly*
asks for one of those actions. Just mentioning a phone number while chatting is NOT
a trigger — the user must request a check.

Pipeline:
  1. Load last 30 messages of history.
  2. Save the user's message.
  3. If Gemini is configured → hand off to the tool-calling agent (no pre-emptive
     PhoBERT or DB lookups). Gemini decides intent and calls tools when needed.
     If not → fall back to a degraded phone-checker mode (regex + DB only).
  4. Build phone verdicts ONLY for phones Gemini explicitly looked up via tool.
  5. Save chatbot reply, return.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_history import ChatHistory
from app.models.user import User
from app.schemas.chatbot import ChatResponse, PhoneVerdict
from app.services import chatbot_tools
from app.services.chatbot_fusion import fuse_verdict

MAX_HISTORY = 30
MAX_TOOL_ITERATIONS = 6  # safety cap on Gemini ↔ tool round-trips


SYSTEM_INSTRUCTION = """Bạn là Real Caller — trợ lý AI tiếng Việt thân thiện. Bạn có thể trò chuyện
tự nhiên với người dùng về mọi chủ đề hàng ngày (thời tiết, lời khuyên, tâm sự, hỏi đáp...).

CHỈ gọi tool khi người dùng YÊU CẦU RÕ RÀNG một trong các hành động sau:

1. `lookup_phone` — chỉ gọi khi user yêu cầu kiểm tra/xác minh một số điện thoại cụ thể.
   Ví dụ trigger: "0988... có scam không?", "kiểm tra số này giúp", "số này có an toàn không?",
   "số này có phải lừa đảo?".
   KHÔNG gọi khi user chỉ nhắc số trong câu chuyện ("tôi mới đổi sang số 0988...", "gọi cho 098...").

2. `analyze_text_for_scam` — chỉ gọi khi user dán/forward một đoạn tin nhắn/hội thoại và hỏi
   nó có phải scam không.
   Ví dụ trigger: "tin này có lừa đảo không?", "đoạn chat này có vấn đề gì không?".
   KHÔNG gọi khi user chỉ kể lại một sự việc bằng lời.

3. `submit_report` — chỉ gọi khi user XÁC NHẬN muốn báo cáo. Trước khi gọi, phải hỏi lại
   user để confirm số điện thoại và lý do.

NGUYÊN TẮC:
- Nếu không thuộc 3 trường hợp trên → cứ trò chuyện bình thường, đừng gọi tool.
- Tiếng Việt, ngắn gọn 2-4 câu, thân thiện.
- Khi tool trả về kết quả scam → cảnh báo rõ ràng, nêu lý do (loại, mức rủi ro, số báo cáo).
- Khi tool trả về unknown/safe → không hứa hẹn "an toàn 100%", chỉ nói "chưa có thông tin".
- Tránh các chủ đề nhạy cảm (chính trị, y tế chuyên sâu) — khéo léo chuyển hướng nếu được hỏi.
"""


class ChatbotService:
    def __init__(self):
        self.model_name = "gemini-2.5-flash"
        self.client = None
        self.is_ready = bool(settings.GEMINI_API_KEY)
        if self.is_ready:
            from google import genai
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
            print(f"Gemini configured (model={self.model_name})")
        else:
            print("GEMINI_API_KEY missing - chatbot falls back to phone-checker mode only.")

    # ── History persistence ────────────────────────────────────────────────

    def _load_history(self, db: Session, user_id) -> list[dict[str, str]]:
        rows = (
            db.query(ChatHistory)
              .filter(ChatHistory.user_id == user_id)
              .order_by(ChatHistory.created_at.desc())
              .limit(MAX_HISTORY)
              .all()
        )
        rows.reverse()
        return [{"role": r.role, "content": r.content} for r in rows]

    def _save(self, db: Session, user_id, role: str, content: str) -> None:
        db.add(ChatHistory(user_id=user_id, role=role, content=content))

    # ── Phone regex (used only by fallback) ────────────────────────────────

    _PHONE_REGEX = re.compile(r"(?:\+84|0)[235789]\d{8}")

    def _extract_phones(self, text: str) -> list[str]:
        if not text:
            return []
        compact = text.replace(" ", "").replace("-", "")
        return list(dict.fromkeys(self._PHONE_REGEX.findall(compact)))

    # ── Fallback mode (no Gemini) ──────────────────────────────────────────

    def _fallback(self, message: str, db: Session) -> tuple[str, list[dict[str, Any]]]:
        """Degraded chat-less mode: only handles phone lookups."""
        phones = self._extract_phones(message)
        if not phones:
            return (
                "Chào bạn! Mình là Real Caller. Bạn gửi số điện thoại cần kiểm tra để mình tra cứu giúp nhé.",
                [],
            )

        tool_log: list[dict[str, Any]] = []
        lines = []
        for p in phones:
            info = chatbot_tools.lookup_phone_impl(p, db=db)
            tool_log.append({"name": "lookup_phone", "args": {"phone": p}, "result": info})
            if info.get("in_blacklist"):
                lines.append(
                    f"⚠️ Số {p} ĐÃ trong danh sách đen (loại {info.get('scam_type')}, "
                    f"rủi ro {info.get('risk_level')}, {info.get('report_count')} báo cáo)."
                )
            elif info.get("is_known_user"):
                lines.append(f"Số {p} thuộc user đã đăng ký, chưa có báo cáo lừa đảo.")
            else:
                lines.append(f"Số {p} chưa có thông tin trong hệ thống.")
        return "\n".join(lines), tool_log

    # ── Gemini agent ───────────────────────────────────────────────────────

    def _tool_dispatch(
        self,
        name: str,
        args: dict[str, Any],
        *,
        db: Session,
        current_user: User,
    ) -> dict[str, Any]:
        try:
            if name == "lookup_phone":
                return chatbot_tools.lookup_phone_impl(args["phone"], db=db)
            if name == "analyze_text_for_scam":
                return chatbot_tools.analyze_text_for_scam_impl(args.get("text", ""))
            if name == "submit_report":
                return chatbot_tools.submit_report_impl(
                    phone=args["phone"],
                    source=args.get("source", "USER_MANUAL"),
                    description=args.get("description", ""),
                    db=db,
                    current_user=current_user,
                )
            return {"error": f"unknown tool {name}"}
        except Exception as e:  # noqa: BLE001 — surface to Gemini so it can recover
            return {"error": str(e)}

    def _run_gemini_agent(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        db: Session,
        current_user: User,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Tool-calling loop. Returns (final_reply, tool_call_log)."""
        from google.genai import types as genai_types

        tools_decl = [genai_types.Tool(function_declarations=chatbot_tools.TOOL_DECLARATIONS)]
        config = genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools_decl,
        )

        contents = []
        for h in history:
            role = "user" if h["role"] == "user" else "model"
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part.from_text(text=h["content"])])
            )
        contents.append(
            genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=message)])
        )

        tool_log: list[dict[str, Any]] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            parts = resp.candidates[0].content.parts if resp.candidates else []
            function_calls = [p for p in parts if getattr(p, "function_call", None)]

            if not function_calls:
                text_parts = [getattr(p, "text", "") for p in parts if getattr(p, "text", None)]
                return (
                    "\n".join(text_parts).strip()
                    or "Mình chưa rõ ý bạn, có thể nói lại không?",
                    tool_log,
                )

            contents.append(resp.candidates[0].content)

            response_parts = []
            for p in function_calls:
                fc = p.function_call
                args = dict(fc.args or {})
                result = self._tool_dispatch(fc.name, args, db=db, current_user=current_user)
                tool_log.append({"name": fc.name, "args": args, "result": result})
                response_parts.append(
                    genai_types.Part.from_function_response(
                        name=fc.name, response={"result": result}
                    )
                )
            contents.append(genai_types.Content(role="tool", parts=response_parts))

        return ("Mình đang gặp chút trở ngại khi xử lý, bạn thử lại nhé.", tool_log)

    # ── Verdict builder — only from explicit lookup_phone calls ───────────

    def _build_verdicts(self, tool_log: list[dict[str, Any]]) -> list[PhoneVerdict]:
        # PhoBERT text analysis (if any) acts as a corroborating signal across all
        # phones looked up in the same turn.
        text_phobert = None
        for call in tool_log:
            if call["name"] == "analyze_text_for_scam":
                res = call["result"]
                if isinstance(res, dict) and res.get("is_scam"):
                    text_phobert = res
                    break

        verdicts: list[PhoneVerdict] = []
        seen_phones = set()
        for call in tool_log:
            if call["name"] != "lookup_phone":
                continue
            info = call["result"]
            if not isinstance(info, dict):
                continue
            norm = info.get("phone_normalized")
            if not norm or norm in seen_phones:
                continue
            seen_phones.add(norm)
            v = fuse_verdict(
                phone=norm,
                phone_info=info,
                phobert=text_phobert,
                gemini_likelihood=None,
            )
            verdicts.append(PhoneVerdict(**v))
        return verdicts

    # ── Entry point ────────────────────────────────────────────────────────

    def process_message(self, message: str, db: Session, current_user: User) -> ChatResponse:
        history = self._load_history(db, current_user.id)
        self._save(db, current_user.id, "user", message)

        tool_log: list[dict[str, Any]] = []

        if self.is_ready:
            try:
                reply, tool_log = self._run_gemini_agent(
                    message=message,
                    history=history,
                    db=db,
                    current_user=current_user,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[chatbot] Gemini agent failed: {e}")
                reply, tool_log = self._fallback(message, db)
        else:
            reply, tool_log = self._fallback(message, db)

        verdicts = self._build_verdicts(tool_log)

        self._save(db, current_user.id, "chatbot", reply)
        db.commit()

        return ChatResponse(reply=reply, verdicts=verdicts)


chatbot_service = ChatbotService()
