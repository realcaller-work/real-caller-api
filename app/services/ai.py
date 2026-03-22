from app.models.scam_number import ScamType, RiskLevel
from app.services.preprocessor import preprocessor
from app.core.config import settings
import json
import os
import time
import requests
from typing import List, Dict, Optional

# Mappings based on typically trained models.
SCAM_CLASSES = ["harmless", "scam"]

class AIService:
    # Triggered reload to load fine-tuned model
    def __init__(self):
        self.is_ready = bool(settings.HF_TOKEN)
        if self.is_ready:
            print(f"✅ HF Inference API configured with endpoint: {settings.HF_API_URL}")
        else:
            print("❌ Error: HF_TOKEN is missing. AI Service will use fallback mock analysis.")

    def analyze_scam_report(
        self, 
        description: str, 
        messages: List[Dict], 
        evidence_urls: List[str]
    ) -> Dict:
        """
        Analyze evidence using Gemini with PhoBERT-style preprocessing.
        """
        log_path = os.path.join(os.getcwd(), "ai_debug.log")
        
        # 1. Preprocess evidence (as recommended in the AI Training report)
        clean_description = preprocessor.clean_text(description or "")
        
        clean_messages = []
        for m in (messages or []):
            clean_content = preprocessor.clean_text(m.get('content', ''))
            clean_messages.append({
                "sender": m.get('sender', 'Unknown'),
                "content": clean_content
            })

        if not self.is_ready:
            return self._mock_analysis(description)

        # 2. Build combined text for inference
        combined_text = clean_description
        if clean_messages:
            combined_text += " " + " ".join([m.get('content', '') for m in clean_messages])
            
        # If text is empty after cleaning
        if not combined_text.strip():
             return self._mock_analysis(description)

        try:
            # 3. Request HF API
            headers = {
                "Accept" : "application/json",
                "Authorization": f"Bearer {settings.HF_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": combined_text,
                "parameters": {}
            }
            
            response = requests.post(settings.HF_API_URL, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            
            # 4. Parse output
            api_result = response.json()
            print(f"DEBUG: HF API Raw Result: {api_result}")
            
            # Assuming output format: [[{"label": "LABEL_1", "score": 0.9}, {"label": "LABEL_0", "score": 0.1}]]
            # Or: [{"label": "LABEL_1", "score": 0.9}]
            if isinstance(api_result, list):
                if len(api_result) > 0 and isinstance(api_result[0], list):
                    predictions = api_result[0]
                else:
                    predictions = api_result
            else:
                predictions = []

            is_scam = False
            conf_val = 0.0
            
            if predictions:
                # Get prediction with highest score
                best_pred = max(predictions, key=lambda x: x.get('score', 0))
                conf_val = best_pred.get('score', 0)
                label = best_pred.get('label', '').upper()
                
                # Based on standard SequenceClassification models, 'LABEL_1' or 'SCAM' or '1' is scam
                if label in ["LABEL_1", "SCAM", "1", "TRUE"]:
                    is_scam = True
                    
            # 5. Extract specific Scam Type using fallback strategy (since primary only returns binary)
            info = self._mock_analysis(combined_text)
            predicted_class = info['scam_type'] if is_scam else "none"
            
            # Assign Risk Based on Confidence
            risk = "low"
            if is_scam:
                risk = "medium"
                if conf_val > 0.8:
                    risk = "critical"
                elif conf_val > 0.6:
                    risk = "high"
                
            result = {
                "is_scam": is_scam,
                "scam_type": predicted_class if is_scam else "none",
                "risk_level": risk,
                "summary": f"Dự đoán bằng Hugging Face ({'Có Lừa Đảo' if is_scam else 'An Toàn'}). (Conf: {conf_val:.2f})",
                "confidence": conf_val
            }
            print(f"DEBUG: Hugging Face Prediction: {result}")
            return result
                
        except Exception as e:
            print(f"DEBUG: HF API Inference Error: {e}")
            return self._mock_analysis(description)

    def _mock_analysis(self, description: str) -> Dict:
        # Simple rule-based mock for fallback
        desc_lower = (description or "").lower()
        stype = "other"
        if "đầu tư" in desc_lower or "tiền ảo" in desc_lower or "chứng khoán" in desc_lower:
            stype = "investment"
        elif "vay" in desc_lower or "tín dụng" in desc_lower:
            stype = "loan"
        elif "việc làm" in desc_lower or "tuyển dụng" in desc_lower:
            stype = "recruitment"
        elif "công an" in desc_lower or "ngân hàng" in desc_lower or "giả danh" in desc_lower:
            stype = "impersonation"
            
        return {
            "is_scam": True,
            "scam_type": stype,
            "risk_level": "high",
            "summary": "Phân tích dự phòng dựa trên từ khóa (Mock Mode).",
            "confidence": 0.5
        }

ai_service = AIService()
