# 🛡️ real-caller-api (Chi Cục Thuế Anti-Scam API)

FastAPI backend for the Real Caller Android application. Hệ thống API phát hiện lừa đảo qua số điện thoại và nội dung hội thoại, sử dụng mô hình học sâu **PhoBERT** (Local) được tối ưu cho tiếng Việt.

## 🚀 Tính năng chính

- **Check Scam đa năng**: Kiểm tra danh sách số điện thoại (Database) kết hợp phân tích nội dung chat hai chiều (AI).
- **Phân tích hội thoại (AI-Powered)**: Sử dụng PhoBERT để hiểu ngữ cảnh lừa đảo.
- **Report Scam**: Người dùng báo cáo số điện thoại kèm toàn bộ đoạn hội thoại chat.
- **Migration tự động**: Tích hợp Alembic giúp cập nhật Database PostgreSQL trơn tru.

---

## 🛠️ Hướng dẫn cài đặt

### 1. Cài đặt Dependencies

```bash
pip install -r requirements.txt
```

### 2. Khởi tạo Database & Migration

```bash
# Tạo file migration & Nâng cấp DB
alembic revision --autogenerate -m "Update schema"
alembic upgrade head
```

### 3. Khởi chạy Server

```bash
uvicorn app.main:app --reload
```

---

## 🛰️ Danh sách API & Body mẫu

### 1. Đăng ký thiết bị (Lấy Token)

- **Endpoint**: `POST /api/v1/device/register`
- **Body Mẫu**:

```json
{
  "deviceId": "unique_device_uuid_123",
  "platform": "android",
  "phone": "+84912345678"
}
```

### 2. Kiểm tra danh sách SĐT (Check Phones)

Kiểm tra một danh sách các SĐT trong csdl.

- **Endpoint**: `POST /api/v1/scam/check-phones`
- **Body Mẫu**:

```json
{
  "phones": ["0944555666", "0987654321"]
}
```

### 3. Kiểm tra phân tích hội thoại chữ (Check Conversations)

Phân tích AI kết hợp check nhanh cho đoạn chat.

- **Endpoint**: `POST /api/v1/scam/check-conversations`
- **Body Mẫu**:

```json
{
  "conversations": [
    {
      "phone": "0987654321",
      "messages": [
        {
          "sender": "Kẻ lạ",
          "content": "Anh có khoản nợ thuế cần nộp gấp tại link này..."
        },
        { "sender": "Bạn", "content": "Tôi nộp rồi mà?" }
      ]
    }
  ]
}
```

### 3. Báo cáo lừa đảo (Report)

Gửi báo cáo kèm nội dung chat để AI tự học.

- **Endpoint**: `POST /api/v1/scam/report`
- **Body Mẫu**:

```json
{
  "phone": "+84944555666",
  "content": "Đối tượng mạo danh cán bộ thuế gọi điện hù dọa.",
  "scam_type": "impersonation",
  "messages": [
    { "sender": "Đối tượng", "content": "Chào anh, tôi là cán bộ thuế..." },
    { "sender": "Bạn", "content": "Link gì đây?" }
  ],
  "evidence_urls": ["https://imgur.com/screenshot1.png"]
}
```

---

## 🧠 Quản lý AI Model

### Huấn luyện lại (Retraining)

Tự động lấy dữ liệu từ những báo cáo thực tế trong Database để dạy cho AI:

```bash
python train_phobert.py
```

### Kiểm tra AI & Report (Test Scripts)

- Test tính năng Check AI: `python tests/test_ai_phobert.py`
- Test tính năng gửi Báo cáo: `python tests/test_report.py`

## Deployment (Render)

1.  Create a new **Web Service** on Render.
2.  Connect your repository.
3.  Select **Python** as the environment.
4.  **Build Command**: `pip install -r requirements.txt`
5.  **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6.  Add **Environment Variables**:
    *   `DATABASE_URL`: Your PostgreSQL connection string.
    *   `HF_TOKEN`: Your Hugging Face API token.
    *   `SECRET_KEY`: A long random string for JWT.

Render will automatically provide the `$PORT` variable, and the application is now configured to bind to it.

