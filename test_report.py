import asyncio
import httpx
import uuid

async def test_scam_report():
    print("🚀 Đang khởi chạy bài test REPORT SCAM con người...")
    base_url = "http://localhost:8888/api/v1"
    
    device_id = f"tester-{uuid.uuid4().hex[:6]}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Đăng ký thiết bị để lấy Token
        print(f"📱 Bước 1: Đăng ký thiết bị giả lập ({device_id})...")
        reg_res = await client.post(
            f"{base_url}/device/register",
            json={
                "deviceId": device_id,
                "platform": "web",
                "phone": "+84111222333"
            }
        )
        
        if reg_res.status_code != 200:
            print(f"❌ Đăng ký thất bại: {reg_res.text}")
            return
            
        token = reg_res.json().get("accessToken")
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ Đăng ký thành công, đã nhận JWT Token.")

        # 2. Gửi báo cáo lừa đảo mẫu (Report)
        print("\n📤 Bước 2: Đang gửi báo cáo lừa đảo mẫu lên Server...")
        
        # Dữ liệu mẫu mạo danh cục thuế (Context này cực kỳ giống thực tế)
        report_data = {
            "phone": "+84944555666",
            "content": "Đối tượng mạo danh cán bộ thuế gọi điện hù dọa và gửi link lạ.",
            "scam_type": "impersonation", # Mạo danh
            "messages": [
                {"sender": "Kẻ lừa đảo", "content": "Chào anh, tôi là cán bộ chi cục thuế. Anh có khoản nợ thuế thu nhập cá nhân chưa quyết toán."},
                {"sender": "Bạn", "content": "Tôi đã nộp hết rồi mà?"},
                {"sender": "Kẻ lừa đảo", "content": "Hệ thống đang lỗi, anh cần cài app 'Tổng Cục Thuế' tại link thue.gov-vn.xyz/app.apk để tự đối soát và nhận hoàn tiền."},
                {"sender": "Kẻ lừa đảo", "content": "Nếu không làm ngay tài khoản ngân hàng của anh sẽ bị phong tỏa."}
            ]
        }

        report_res = await client.post(
            f"{base_url}/scam/report",
            json=report_data,
            headers=headers
        )

        if report_res.status_code == 200:
            print("✅ Gửi REPORT thành công!")
            data = report_res.json()
            print("\n--- PHẢN HỒI TỪ SERVER (AI PHÂN TÍCH) ---")
            print(f"ID Report: {data.get('id')}")
            print(f"Loại hình (AI nhãn): {data.get('scam_type')}")
            print(f"Mức độ rủi ro: {data.get('risk_level')}")
            
            # Kiểm tra xem dữ liệu có thực sự vào DB chưa bằng cách Check lại số này
            print("\n🔍 Bước 3: Kiểm tra lại số điện thoại vừa báo cáo...")
            check_res = await client.post(
                f"{base_url}/scam/check",
                json={"phones": ["+84944555666"]},
                headers=headers
            )
            
            if check_res.status_code == 200:
                results = check_res.json().get("results", [])
                for r in results:
                    if r.get('isScam'):
                        print(f"✅ XÁC NHẬN: Số {r.get('phone')} đã nằm trong danh sách ĐEN của Database.")
        else:
            print(f"❌ Gửi báo cáo thất bại: {report_res.status_code} - {report_res.text}")

if __name__ == "__main__":
    asyncio.run(test_scam_report())
