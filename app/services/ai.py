from app.services.preprocessor import preprocessor
from app.core.config import settings
import requests
from typing import List, Dict


class AIServiceUnavailable(RuntimeError):
    """Raised when the AI inference backend cannot produce a result."""


class AIService:
    def __init__(self):
        self.is_ready = bool(settings.HF_TOKEN) and bool(settings.HF_API_URL)

    def analyze_scam_report(
        self,
        description: str,
        messages: List[Dict],
        evidence_urls: List[str],
    ) -> Dict:
        if not self.is_ready:
            raise AIServiceUnavailable("AI inference is not configured")

        clean_description = preprocessor.clean_text(description or "")
        clean_messages = [
            preprocessor.clean_text(m.get("content", "")) for m in (messages or [])
        ]
        combined_text = " ".join(
            part for part in ([clean_description] + clean_messages) if part
        ).strip()

        if not combined_text:
            raise AIServiceUnavailable("No content to analyze")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.HF_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {"inputs": combined_text, "parameters": {}}

        try:
            response = requests.post(
                settings.HF_API_URL, headers=headers, json=payload, timeout=15
            )
            response.raise_for_status()
            api_result = response.json()
        except requests.RequestException as e:
            raise AIServiceUnavailable("AI inference request failed") from e
        except ValueError as e:
            raise AIServiceUnavailable("AI inference returned invalid response") from e

        if isinstance(api_result, list) and api_result and isinstance(api_result[0], list):
            predictions = api_result[0]
        elif isinstance(api_result, list):
            predictions = api_result
        else:
            predictions = []

        if not predictions:
            raise AIServiceUnavailable("AI inference returned no predictions")

        best_pred = max(predictions, key=lambda x: x.get("score", 0))
        conf_val = float(best_pred.get("score", 0.0))
        label = str(best_pred.get("label", "")).upper()
        is_scam = label in {"LABEL_1", "SCAM", "1", "TRUE"}

        if is_scam:
            if conf_val > 0.8:
                risk = "critical"
            elif conf_val > 0.6:
                risk = "high"
            else:
                risk = "medium"
        else:
            risk = "low"

        return {
            "is_scam": is_scam,
            "scam_type": "OTHER" if is_scam else "none",
            "risk_level": risk,
            "confidence": conf_val,
        }


ai_service = AIService()
