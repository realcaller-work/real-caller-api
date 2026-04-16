import re
import json
from google import genai
from sqlalchemy.orm import Session
from app.core.config import settings
from app.api.v1.endpoints.scam import get_scam_detail
from app.models.user import User
from app.models.scam_number import ScamNumber, RiskLevel
from app.schemas.scam import ScamCheckResult
from app.schemas.chatbot import ChatResponse
from app.services.utils import normalize_phone

class ChatbotService:
    def __init__(self):
        self.is_ready = bool(settings.GEMINI_API_KEY)
        if self.is_ready:
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
            self.model_name = 'gemini-2.5-flash'
            print("✅ Gemini API configured for Chatbot (google-genai)")
        else:
            print("❌ GEMINI_API_KEY missing. Chatbot will use basic Regex.")

    def _extract_phone_regex(self, text: str):
        # Basic Regex
        pattern = r'(?:\+84|0)[235789]\d{8}'
        matches = re.findall(pattern, text.replace(' ', '').replace('-', ''))
        return matches[0] if matches else None

    def _generate_intent(self, user_msg: str, history: list) -> dict:
        """
        Ask Gemini to extract intent and phone number using history context.
        """
        if not self.is_ready:
           phone = self._extract_phone_regex(user_msg)
           if phone:
               return {"phone": phone}
           return {"reply": "Bạn vui lòng cung cấp số điện thoại để mình kiểm tra nhé!"}

        hist_str = ""
        if history:
            for h in history[-5:]: # Chỉ lấy 5 tin nhắn gần nhất để đỡ loạn
                role_name = "Người dùng" if h.role == "user" else "Chatbot"
                hist_str += f"{role_name}: {h.content}\n"

        prompt = f"""
        Bạn là hệ thống kiểm tra lừa đảo Real Caller. Người dùng đang chat với bạn.
        Nhiệm vụ: 
        1. Đọc tin nhắn hiện tại và lịch sử chat để xác định người dùng đang ám chỉ đến SỐ ĐIỆN THOẠI VIỆT NAM nào.
        2. Nếu tìm ra được SĐT mục tiêu, CHỈ trả về đúng chuỗi JSON: {{"phone": "số_điện_thoại_đó"}}
        3. Nếu không xác định được SĐT nào để kiểm tra, hãy trả lời tự nhiên theo ngữ cảnh, kiểu JSON: {{"reply": "câu_trả_lời_của bạn"}}
        
        Lịch sử cuộc trò chuyện gần đây:
        {hist_str}
        
        Tin nhắn hiện tại: "{user_msg}"
        
        Lưu ý: Chỉ trả ra đúng 1 JSON object. Không giải thích thêm.
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            text = response.text.strip()
            
            # Clean markdown codeblocks
            text = re.sub(r'^```[a-zA-Z]*\n', '', text)
            text = re.sub(r'```$', '', text).strip()
            
            # Find json boundaries
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                 text = text[start:end+1]
                 
            return json.loads(text)
        except Exception as e:
            print("Gemini Intent Error:", e)
            phone = self._extract_phone_regex(user_msg)
            if phone:
                return {"phone": phone}
            return {"reply": "Lỗi AI phần đọc ý định. Vui lòng gõ lại đầy đủ số điện thoại nhé."}

    def _generate_human_reply(self, scam_result: dict, original_msg: str, history: list) -> str:
        if not self.is_ready:
            t = scam_result.get('type')
            if t in ['scam', 'spam']:
                return "Cẩn thận! Số điện thoại này nằm trong danh sách rủi ro."
            elif t == 'normal':
                return "Số điện thoại này thuộc về người dùng an toàn."
            return "Số này chưa có thông tin trong hệ thống."

        hist_str = ""
        if history:
            for h in history[-3:]: # Lấy 3 câu gần nhất
                role_name = "Người dùng" if h.role == "user" else "Chatbot"
                hist_str += f"{role_name}: {h.content}\n"

        prompt = f"""
        Bạn là trợ lý kiểm tra lừa đảo của app Real Caller. AI lõi vừa phân tích số điện thoại quy chiếu và ra kết quả sau:
        {json.dumps(scam_result, ensure_ascii=False)}
        
        Lịch sử cuộc trò chuyện (để tham khảo lại ngữ cảnh):
        {hist_str}
        
        Câu hỏi hiện tại của người dùng là: "{original_msg}"
        
        Dựa vào kết quả kiểm tra (type: scam là lừa đảo, spam là làm phiền, normal là người dùng bình thường, unknown là số lạ chưa có thông tin), 
        hãy viết 1 câu trả lời ngắn gọn, nối tiếp tự nhiên với cuộc nói chuyện để thông báo cho người dùng biết kết quả.
        Tập trung nhắc nhở cảnh cáo nếu là scam/spam (có báo cáo hoặc risk_level cao).
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return response.text.strip()
        except:
            return "Đã kiểm tra xong. Bạn xem dữ liệu chi tiết bên dưới nhé!"

    def process_message(self, message: str, history: list, db: Session) -> ChatResponse:
        # Lớp 1: Bóc tách/Intent với History
        intent_data = self._generate_intent(message, history)
        phone = intent_data.get("phone")
        
        # Không có số điện thoại
        if not phone:
            return ChatResponse(
                reply=intent_data.get("reply", "Bạn cần cung cấp số điện thoại muốn kiểm tra."),
                detected_phone=None,
                scam_info=None
            )
            
        # Lớp 2: Có số điện thoại -> Dò Core DB
        norm_phone = normalize_phone(phone)
        scam_num = db.query(ScamNumber).filter(ScamNumber.phone == norm_phone).first()
        db_user = db.query(User).filter(User.phone == norm_phone).first()
        
        scam_result = {
            "phone": phone,
            "type": "unknown",
            "scam_info": None,
            "user_info": None
        }
        
        if scam_num:
            t = "scam" if scam_num.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL") else "spam"
            scam_result["type"] = t
            scam_result["scam_info"] = {
                "scam_type": scam_num.scam_type,
                "risk_level": scam_num.risk_level,
                "reports": scam_num.reportCount,
                "ai_confidence": 0.0
            }
        elif db_user:
            scam_result["type"] = "normal"
            scam_result["user_info"] = {
                "fullName": db_user.fullName,
                "email": db_user.email,
                "birthday": db_user.birthday,
                "gender": db_user.gender,
                "is_verified": db_user.is_verified
            }
        else:
            # Lớp 2.5: Phân tích bằng mô hình AI nếu không có trong DB
            from app.services.ai import ai_service
            
            ai_result = ai_service.analyze_scam_report(
                description=message, # Gửi toàn bộ câu nói của ng dùng sang model
                messages=[],
                evidence_urls=[]
            )
            
            is_scam = ai_result.get("is_scam", False) if ai_result else False
            if is_scam:
                scam_enum_vals = ["INVESTMENT", "LOAN", "RECRUITMENT", "IMPERSONATION", "OTHER"]
                raw_type = str(ai_result.get("scam_type", "OTHER")).upper()
                scam_type = raw_type if raw_type in scam_enum_vals else "OTHER"
                    
                risk_level = str(ai_result.get("risk_level", "MEDIUM")).upper()
                confidence = ai_result.get("confidence", 0.0)
                
                t = "scam" if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL, "HIGH", "CRITICAL") else "spam"
                scam_result["type"] = t
                scam_result["scam_info"] = {
                    "scam_type": scam_type,
                    "risk_level": risk_level,
                    "reports": 0, # Số 0 ám chỉ chưa có report, đây là do AI tự phân tích
                    "ai_confidence": confidence
                }
            
        # Lớp 3: Generate human response (cũng có history để nói nối tiếp)
        final_reply = self._generate_human_reply(scam_result, message, history)
        
        # Cấu trúc ScamCheckResult xài chung cho app Pydantic
        scam_res_obj = ScamCheckResult(**scam_result)
        
        return ChatResponse(
            reply=final_reply,
            detected_phone=norm_phone,
            scam_info=scam_res_obj
        )

chatbot_service = ChatbotService()
