"""Conversational chatbot service — 4-layer pipeline.

Layer 1 — Preprocess: extract entities (phones, URLs) + run PhoBERT baseline on the message text.
Layer 2 — Context retrieval: prefetch DB info for each extracted phone (RAG-style grounding).
Layer 3 — Gemini agent: tool-calling loop. Gemini decides whether to chat freely or call tools.
Layer 4 — Verdict fusion + final synthesis: aggregate DB + PhoBERT + Gemini signals for each phone
          that surfaced in conversation, attach to response alongside the natural-language reply.

Falls back to a regex + DB lookup if GEMINI_API_KEY is missing — so the chatbot remains
functional offline (degraded UX, but tests can run without external services).
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chat_history import ChatHistory
from app.models.user import User
from app.schemas.chatbot import ChatResponse, PhoneVerdict
from app.services import chatbot_tools
from app.services.chatbot_fusion import fuse_verdict
from app.services.utils import normalize_phone

MAX_HISTORY = 30
MAX_TOOL_ITERATIONS = 6  # safety cap on Gemini ↔ tool round-trips


SYSTEM_INSTRUCTION = """Bạn là Real Caller — trợ lý AI thân thiện, giúp người Việt vừa trò chuyện
hàng ngày vừa phòng tránh lừa đảo qua điện thoại.

QUY TẮC BẮT BUỘC:
1. Khi người dùng nhắc đến MỘT SỐ ĐIỆN THOẠI cụ thể → LUÔN gọi tool `lookup_phone` để
   tra cứu trước khi trả lời. Không bao giờ tự suy đoán xem số đó có an toàn không.
2. Khi người dùng dán/forward một đoạn tin nhắn dài đáng ngờ → gọi `analyze_text_for_scam`
   để PhoBERT đánh giá.
3. Khi người dùng XÁC NHẬN muốn báo cáo một số → gọi `submit_report` (phải xác nhận lại
   số + lý do trước, không tự ý gọi).
4. Khi câu hỏi là tán gẫu/thông thường (không có phone hay text đáng ngờ) → trả lời tự nhiên
   không gọi tool nào.

PHONG CÁCH:
- Tiếng Việt, ngắn gọn 2-4 câu, thân thiện như bạn bè.
- Khi cảnh báo scam: rõ ràng, nêu lý do (loại scam, mức rủi ro, số báo cáo) — không doạ quá.
- Khi số an toàn / không có dữ liệu: nói rõ giới hạn ("chưa có thông tin" ≠ "an toàn 100%").
- Nếu bị hỏi ngoài lề (chính trị, y tế, pháp lý chi tiết) → lịch sự khéo léo chuyển hướng
  về chủ đề an toàn điện thoại.
"""


class ChatbotService:
    def __init__(self):
        self.model_name = "gemini-2.5-pro"
        self.client = None
        self.is_ready = bool(settings.GEMINI_API_KEY)
        if self.is_ready:
            from google import genai
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
            print(f"Gemini configured (model={self.model_name})")
        else:
            print("GEMINI_API_KEY missing - chatbot falls back to regex + DB lookup only.")

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

    # ── Layer 1 — preprocess ──────────────────────────────────────────────

    _PHONE_REGEX = re.compile(r"(?:\+84|0)[235789]\d{8}")

    def _extract_phones(self, text: str) -> list[str]:
        if not text:
            return []
        compact = text.replace(" ", "").replace("-", "")
        return list(dict.fromkeys(self._PHONE_REGEX.findall(compact)))

    def _preprocess(self, message: str) -> dict[str, Any]:
        phones = self._extract_phones(message)
        # Baseline scam analysis on the whole message, regardless of intent.
        baseline = chatbot_tools.analyze_text_for_scam_impl(message)
        return {"phones": phones, "baseline_phobert": baseline}

    # ── Layer 2 — context retrieval ───────────────────────────────────────

    def _gather_context(self, phones: list[str], db: Session) -> dict[str, Any]:
        phone_info = {p: chatbot_tools.lookup_phone_impl(p, db=db) for p in phones}
        return {"phone_info": phone_info}

    # ── Fallback (no Gemini) ──────────────────────────────────────────────

    def _fallback_reply(
        self,
        message: str,
        preprocess: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        phones = preprocess["phones"]
        if not phones:
            return "Bạn cung cấp số điện thoại để mình kiểm tra giúp nhé!"

        lines = []
        for p in phones:
            info = context["phone_info"].get(p, {})
            if info.get("in_blacklist"):
                lines.append(
                    f"⚠️ Số {p} ĐÃ trong danh sách đen (loại {info.get('scam_type')}, "
                    f"rủi ro {info.get('risk_level')}, {info.get('report_count')} báo cáo). Cẩn thận nhé!"
                )
            elif info.get("is_known_user"):
                lines.append(
                    f"Số {p} thuộc về người dùng Real Caller đã đăng ký. Chưa có báo cáo lừa đảo."
                )
            else:
                lines.append(f"Số {p} chưa có thông tin trong hệ thống. Hãy thận trọng.")
        return "\n".join(lines)

    # ── Layer 3 — Gemini tool-calling loop ────────────────────────────────

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
        preprocess: dict[str, Any],
        context: dict[str, Any],
        db: Session,
        current_user: User,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Run the agent loop. Returns (final_reply, tool_call_log)."""
        from google.genai import types as genai_types

        # Build a "context block" of prefetched data so Gemini doesn't have to call
        # tools redundantly when the answer is already obvious.
        precomputed = {
            "phones_detected_in_message": preprocess["phones"],
            "phobert_baseline_on_message": preprocess["baseline_phobert"],
            "phone_lookup_prefetch": context["phone_info"],
        }
        context_note = (
            "DỮ LIỆU ĐÃ TRA SẴN cho tin nhắn này (bạn có thể dùng luôn, không cần gọi tool lại):\n"
            f"{json.dumps(precomputed, ensure_ascii=False, indent=2)}"
        )

        tools_decl = [
            genai_types.Tool(function_declarations=chatbot_tools.TOOL_DECLARATIONS)
        ]

        config = genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools_decl,
        )

        # Build contents: history → context_note → user message
        contents = []
        for h in history:
            role = "user" if h["role"] == "user" else "model"
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part.from_text(text=h["content"])])
            )
        contents.append(
            genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=context_note)])
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
                # Final natural-language answer
                text_parts = [getattr(p, "text", "") for p in parts if getattr(p, "text", None)]
                return ("\n".join(text_parts).strip() or "Mình chưa rõ ý bạn, có thể hỏi lại không?", tool_log)

            # Append the model's tool-request turn
            contents.append(resp.candidates[0].content)

            # Execute each requested function call
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

    # ── Layer 4 — fusion + response synthesis ─────────────────────────────

    def _build_verdicts(
        self,
        preprocess: dict[str, Any],
        context: dict[str, Any],
        tool_log: list[dict[str, Any]],
    ) -> list[PhoneVerdict]:
        # Collect every phone we have evidence for: detected in message + any
        # phone Gemini explicitly looked up via tool.
        candidates: dict[str, dict[str, Any]] = {}
        for p in preprocess["phones"]:
            candidates[normalize_phone(p)] = context["phone_info"].get(p)
        for call in tool_log:
            if call["name"] == "lookup_phone":
                info = call["result"]
                if isinstance(info, dict) and info.get("phone_normalized"):
                    candidates[info["phone_normalized"]] = info

        if not candidates:
            return []

        # PhoBERT baseline applies to the whole message — only attach if it indicates scam.
        phobert_baseline = preprocess["baseline_phobert"]
        phobert_for_fusion = phobert_baseline if phobert_baseline.get("is_scam") else None

        verdicts: list[PhoneVerdict] = []
        for norm, info in candidates.items():
            v = fuse_verdict(
                phone=norm,
                phone_info=info,
                phobert=phobert_for_fusion,
                gemini_likelihood=None,
            )
            verdicts.append(PhoneVerdict(**v))
        return verdicts

    # ── Entry point ────────────────────────────────────────────────────────

    def process_message(self, message: str, db: Session, current_user: User) -> ChatResponse:
        history = self._load_history(db, current_user.id)
        self._save(db, current_user.id, "user", message)

        # Layer 1 + 2 — always
        preprocess = self._preprocess(message)
        context = self._gather_context(preprocess["phones"], db)

        tool_log: list[dict[str, Any]] = []

        if self.is_ready:
            try:
                reply, tool_log = self._run_gemini_agent(
                    message=message,
                    history=history,
                    preprocess=preprocess,
                    context=context,
                    db=db,
                    current_user=current_user,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[chatbot] Gemini agent failed: {e}")
                reply = self._fallback_reply(message, preprocess, context)
        else:
            reply = self._fallback_reply(message, preprocess, context)

        verdicts = self._build_verdicts(preprocess, context, tool_log)

        self._save(db, current_user.id, "chatbot", reply)
        db.commit()

        return ChatResponse(reply=reply, verdicts=verdicts)


chatbot_service = ChatbotService()
