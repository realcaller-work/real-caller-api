import re
import json
from google import genai
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.user import User
from app.models.scam_number import ScamNumber, RiskLevel
from app.models.scam_report import ScamReport
from app.models.chat_history import ChatHistory
from app.schemas.chatbot import ChatResponse
from app.services.utils import normalize_phone

MAX_HISTORY = 10


class ChatbotService:
    def __init__(self):
        self.is_ready = bool(settings.GEMINI_API_KEY)
        if self.is_ready:
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
            self.model_name = 'gemini-2.5-flash'
            print("✅ Gemini API configured for Chatbot (google-genai)")
        else:
            print("❌ GEMINI_API_KEY missing. Chatbot will use basic Regex.")

    # ─── History ────────────────────────────────────────────────────────

    def _load_history(self, db: Session, user_id) -> list[dict]:
        rows = (
            db.query(ChatHistory)
            .filter(ChatHistory.user_id == user_id)
            .order_by(ChatHistory.created_at.desc())
            .limit(MAX_HISTORY)
            .all()
        )
        rows.reverse()
        return [{"role": r.role, "content": r.content} for r in rows]

    def _save_message(self, db: Session, user_id, role: str, content: str):
        db.add(ChatHistory(user_id=user_id, role=role, content=content))

    # ─── Phone regex ────────────────────────────────────────────────────

    def _extract_phone_regex(self, text: str):
        pattern = r'(?:\+84|0)[235789]\d{8}'
        matches = re.findall(pattern, text.replace(' ', '').replace('-', ''))
        return matches[0] if matches else None

    # ─── Lookup phone in DB ─────────────────────────────────────────────

    def _lookup_phone(self, phone: str, db: Session) -> str:
        """Return a plain-text summary about this phone number."""
        norm = normalize_phone(phone)
        scam = db.query(ScamNumber).filter(ScamNumber.phone == norm).first()
        user = db.query(User).filter(User.phone == norm).first()

        if scam:
            risk = str(scam.risk_level).replace("RiskLevel.", "")
            stype = str(scam.scam_type).replace("ScamType.", "")
            return (
                f"Số {phone} nằm trong DANH SÁCH ĐEN.\n"
                f"- Loại: {stype}\n"
                f"- Mức rủi ro: {risk}\n"
                f"- Số lượt báo cáo: {scam.reportCount}"
            )
        if user:
            name = user.fullName or "Không rõ tên"
            verified = "Đã xác minh" if user.is_verified else "Chưa xác minh"
            return f"Số {phone} thuộc về người dùng: {name} ({verified}). Không có báo cáo lừa đảo."

        return f"Số {phone} chưa có thông tin trong hệ thống. Chưa bị báo cáo."

    # ─── Report phone ───────────────────────────────────────────────────

    def _report_phone(self, phone: str, description: str, scam_type: str,
                      db: Session, current_user: User) -> str:
        """Execute report and return a plain-text summary."""
        norm = normalize_phone(phone)
        scam = db.query(ScamNumber).filter(ScamNumber.phone == norm).first()

        scam_enum_vals = ["INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER"]
        stype = scam_type.upper() if scam_type.upper() in scam_enum_vals else "OTHER"

        if scam:
            scam.reportCount += 1
            report_log = ScamReport(
                phone=norm, deviceId=str(current_user.id),
                reportType=stype, description=description,
                evidence_urls=[], messages=[]
            )
            db.add(report_log)
            db.commit()
            return (
                f"Đã ghi nhận thêm báo cáo cho số {phone}.\n"
                f"Tổng số lượt báo cáo hiện tại: {scam.reportCount}."
            )

        # Chưa có -> tạo mới
        from app.services.ai import ai_service
        ai_result = ai_service.analyze_scam_report(
            description=description, messages=[], evidence_urls=[]
        )

        report_log = ScamReport(
            phone=norm, deviceId=str(current_user.id),
            reportType=stype, description=description,
            evidence_urls=[], messages=[]
        )
        db.add(report_log)

        is_scam = ai_result.get("is_scam", True) if ai_result else True
        if is_scam:
            risk = str(ai_result.get("risk_level", "MEDIUM") if ai_result else "MEDIUM").upper()
            ai_type = str(ai_result.get("scam_type", stype)).upper() if ai_result else stype
            final_type = ai_type if ai_type in scam_enum_vals else "OTHER"

            db.add(ScamNumber(
                phone=norm, scam_type=final_type, risk_level=risk,
                reportCount=1, is_ai_vetted=True, metadata_info=ai_result
            ))
            db.commit()
            return (
                f"Báo cáo thành công! AI xác nhận số {phone} có rủi ro.\n"
                f"Đã thêm vào danh sách đen (Mức rủi ro: {risk})."
            )
        else:
            db.commit()
            return (
                f"Đã ghi nhận báo cáo cho số {phone}.\n"
                f"AI đánh giá rủi ro thấp, số này sẽ được theo dõi thêm."
            )

    # ─── Main ───────────────────────────────────────────────────────────

    def process_message(self, message: str, db: Session, current_user: User) -> ChatResponse:
        history = self._load_history(db, current_user.id)
        self._save_message(db, current_user.id, "user", message)

        # ── Nếu không có Gemini -> fallback regex ──
        if not self.is_ready:
            phone = self._extract_phone_regex(message)
            if phone:
                result = self._lookup_phone(phone, db)
                reply = result
            else:
                reply = "Bạn vui lòng cung cấp số điện thoại để mình kiểm tra nhé!"
            self._save_message(db, current_user.id, "chatbot", reply)
            db.commit()
            return ChatResponse(reply=reply)

        # ── Gemini: phân tích intent + tra cứu + tổng hợp ──
        hist_str = ""
        for h in (history or [])[-5:]:
            role_name = "Người dùng" if h["role"] == "user" else "Chatbot"
            hist_str += f"{role_name}: {h['content']}\n"

        # Bước 1: Bóc tách intent
        intent_prompt = f"""
Bạn là hệ thống kiểm tra lừa đảo Real Caller.

Nhiệm vụ:
1. Đọc tin nhắn và lịch sử để xác định ý định người dùng.
2. Trả về đúng 1 JSON:
   - Kiểm tra: {{"intent":"CHECK","phone":"số"}}
   - Báo cáo: {{"intent":"REPORT","phone":"số","scam_type":"INVESTMENT|LOAN|RECRUITMENT|IMPERSONATION|OTHER","description":"mô tả"}}
   - Khác: {{"intent":"CHAT","reply":"câu trả lời"}}

Lịch sử:
{hist_str}

Tin nhắn: "{message}"

Chỉ trả JSON. Không giải thích.
"""
        try:
            resp = self.client.models.generate_content(
                model=self.model_name, contents=intent_prompt
            )
            text = resp.text.strip()
            text = re.sub(r'^```[a-zA-Z]*\n', '', text)
            text = re.sub(r'```$', '', text).strip()
            start, end = text.find('{'), text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end + 1]
            intent_data = json.loads(text)
        except Exception as e:
            print("Gemini Intent Error:", e)
            phone = self._extract_phone_regex(message)
            if phone:
                intent_data = {"intent": "CHECK", "phone": phone}
            else:
                intent_data = {"intent": "CHAT", "reply": "Xin lỗi, mình chưa hiểu. Bạn gõ số điện thoại cần kiểm tra nhé!"}

        intent = intent_data.get("intent", "CHAT").upper()
        phone = intent_data.get("phone")

        # ── CHAT (không có phone) ──
        if intent == "CHAT" or not phone:
            reply = intent_data.get("reply", "Bạn cần cung cấp số điện thoại muốn kiểm tra hoặc báo cáo.")
            self._save_message(db, current_user.id, "chatbot", reply)
            db.commit()
            return ChatResponse(reply=reply)

        # ── CHECK hoặc REPORT -> lấy dữ liệu thực ──
        if intent == "REPORT":
            data_summary = self._report_phone(
                phone,
                intent_data.get("description", message),
                intent_data.get("scam_type", "OTHER"),
                db, current_user
            )
        else:
            data_summary = self._lookup_phone(phone, db)

        # Bước 2: Gemini tổng hợp thành reply tự nhiên
        reply_prompt = f"""
Bạn là trợ lý Real Caller. Dựa vào dữ liệu bên dưới, viết 1 câu trả lời ngắn gọn, thân thiện cho người dùng.

Dữ liệu:
{data_summary}

Lịch sử chat:
{hist_str}

Câu hỏi: "{message}"

Yêu cầu: Trả lời tự nhiên bằng tiếng Việt, 2-4 câu. Cảnh báo rõ nếu nguy hiểm. Không lặp lại toàn bộ dữ liệu thô.
"""
        try:
            resp = self.client.models.generate_content(
                model=self.model_name, contents=reply_prompt
            )
            reply = resp.text.strip()
        except:
            reply = data_summary  # Fallback: dùng dữ liệu thô

        self._save_message(db, current_user.id, "chatbot", reply)
        db.commit()
        return ChatResponse(reply=reply)


chatbot_service = ChatbotService()
