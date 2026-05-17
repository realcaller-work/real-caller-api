import asyncio
import httpx
import uuid
import sys
import os
sys.path.append(os.getcwd())
from app.core.config import settings

async def test_report():
    print("🚀 Starting AI-Powered Report Test with local PhoBERT...")
    base_url = settings.TEST_API_BASE_URL
    
    device_id = f"test-device-{uuid.uuid4().hex[:8]}"
    print(f"📱 Registering device: {device_id}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Register Device
        reg_response = await client.post(
            f"{base_url}/device/register",
            json={"deviceId": device_id, "platform": "web", "phone": "+84123456789"}
        )
        if reg_response.status_code != 200:
            print(f"❌ Registration failed: {reg_response.text}")
            return
            
        token = reg_response.json().get("accessToken")
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Check Scam via the new Conversations feature
        print("📤 Submitting multi-conversation checks for AI analysis...")
        check_data = {
            "conversations": [
                {
                    "phone": "+84912345678",
                    "messages": [
                        {"sender": "Scammer", "content": "Em chào anh, em gọi từ chi cục thuế Cầu Giấy. Anh có khoản hoàn thuế 35 triệu cần nhận."},
                        {"sender": "You", "content": "Thế tôi cần làm gì để nhận được?"},
                        {"sender": "Scammer", "content": "Anh tải app Tổng Cục Thuế theo link e_tax.apk này về cài đặt và đăng nhập nhé."}
                    ]
                },
                {
                    "phone": "0987654321",
                    "messages": [
                        {"sender": "Friend", "content": "Alo cậu ơi đang làm gì đó? Đi cafe không?"},
                        {"sender": "You", "content": "Đang bận xíu, lát đi nha."}
                    ]
                }
            ]
        }

        check_res = await client.post(
            f"{base_url}/scam/check-conversations",
            json=check_data,
            headers=headers
        )
        
        if check_res.status_code == 200:
            print("✅ Check submitted successfully")
            print(f"\n--- PHO-BERT ANALYSIS RESULT ---")
            
            data = check_res.json()
            results = data.get("results", [])
            for res in results:
                print("-" * 20)
                print(f"Number: {res.get('phone')}")
                print(f"Is Scam: {res.get('isScam')}")
                print(f"Scam Type: {res.get('scam_type', 'N/A')}")
                print(f"Risk Level: {res.get('risk_level', 'N/A')}")
                print(f"AI Confidence: {res.get('ai_confidence', 0)}")
        else:
            print(f"❌ Check failed: {check_res.status_code} - {check_res.text}")

if __name__ == "__main__":
    asyncio.run(test_report())
