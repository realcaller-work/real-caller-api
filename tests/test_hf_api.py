import sys
import os
sys.path.append(os.getcwd())

from app.services.ai import ai_service
from app.core.config import settings

print(f"Token loaded (first 5 chars): {settings.HF_TOKEN[:5] if settings.HF_TOKEN else 'None'}")
print(f"Service Ready: {ai_service.is_ready}")

res = ai_service.analyze_scam_report(
    description="Cán bộ chi cục thuế yêu cầu cài app VNeID giả mạo",
    messages=[{"sender": "Lừa đảo", "content": "Tải app theo link này nhé: etax.apk"}],
    evidence_urls=[]
)
print("\nKết quả:", res)
