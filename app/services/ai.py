from app.models.scam_number import ScamType, RiskLevel
from app.services.preprocessor import preprocessor
import json
import os
import time
from typing import List, Dict, Optional
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Mappings based on typically trained models.
SCAM_CLASSES = ["harmless", "scam"]

class AIService:
    # Triggered reload to load fine-tuned model
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"DEBUG: Initializing PhoBERT on {self.device}")
        
        # In a real scenario, this would point to the fine-tuned local weights.
        local_model_path = os.path.join(os.getcwd(), "phobert_scam_model")
        if os.path.exists(local_model_path):
            self.model_name = local_model_path
        else:
            self.model_name = "vinai/phobert-base" 
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name, num_labels=2)
            self.model.to(self.device)
            self.model.eval()
            self.is_ready = True
            print("✅ PhoBERT loaded successfully")
        except Exception as e:
            print(f"❌ Error loading PhoBERT: {e}")
            self.is_ready = False

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
            # 3. Tokenize input
            inputs = self.tokenizer(combined_text, return_tensors="pt", truncation=True, max_length=256, padding=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # 4. Inference
            with torch.no_grad():
                outputs = self.model(**inputs)
                logits = outputs.logits
                probs = torch.nn.functional.softmax(logits, dim=-1)
                
                # Get prediction
                confidence, predicted_class_idx = torch.max(probs, dim=-1)
                
                conf_val = confidence.item()
                class_idx = predicted_class_idx.item()
                
                # Check mapping (1 is scam, 0 is harmless)
                is_scam = (class_idx == 1)
                
                # Since PhoBERT predicts Scam vs Not_Scam, use keyword analysis to find scam type
                info = self._mock_analysis(combined_text)
                predicted_class = info['scam_type'] if is_scam else "unknown"
                
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
                    "summary": f"Dự đoán bằng PhoBERT ({'Có Lừa Đảo' if is_scam else 'An Toàn'}). (Conf: {conf_val:.2f})",
                    "confidence": conf_val
                }
                print(f"DEBUG: PhoBERT Prediction: {result}")
                return result
                
        except Exception as e:
            print(f"DEBUG: PhoBERT Inference Error: {e}")
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
