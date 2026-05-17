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

### 4. Chạy tests

```bash
pytest
```

---

## 🛰️ Danh sách API & Body mẫu

> Tất cả endpoint (trừ `/auth/login` và `/health/ping`) yêu cầu header:
> `Authorization: Bearer <accessToken>`

### 1. Đăng nhập (Firebase) — lấy Token

- **Endpoint**: `POST /api/v1/auth/login`
- **Body Mẫu**:

```json
{
  "idToken": "<firebase_id_token>",
  "deviceId": "unique_device_uuid_123"
}
```

- **Response**:

```json
{
  "accessToken": "<short-lived JWT, 1h>",
  "refreshToken": "<long-lived opaque token, 1y>",
  "tokenType": "bearer",
  "accessTokenExpiresIn": 3600,
  "needsProfileUpdate": true
}
```

### 1b. Làm mới phiên (Refresh)

Khi `accessToken` hết hạn (401), client gọi:

- **Endpoint**: `POST /api/v1/auth/refresh`
- **Body**: `{ "refreshToken": "<current refresh token>" }`
- **Response**: cặp token mới. **Lưu ý:** Mỗi lần refresh, refresh token cũ bị revoke → client phải lưu refresh token mới ngay.

### 1c. Đăng xuất (Logout)

- **Endpoint**: `POST /api/v1/auth/logout`
- **Body**: `{ "refreshToken": "<current refresh token>" }`
- **Response**: `{ "success": true }` (idempotent)

> **Cơ chế phiên vĩnh viễn**: `accessToken` ngắn hạn (1h) đảm bảo an toàn — nếu rò rỉ, chỉ dùng được 1h. `refreshToken` dài hạn (1y) được lưu ở DB dưới dạng hash, **rotate mỗi lần dùng**. Client chỉ cần lưu refresh token, gọi `/auth/refresh` khi access token hết hạn → người dùng không bao giờ phải Firebase login lại trừ khi logout chủ động hoặc revoke từ server.

### 2. Kiểm tra danh sách SĐT (Check Phones)

- **Endpoint**: `POST /api/v1/scam/check-phones`
- **Body Mẫu**:

```json
{
  "phones": ["0944555666", "0987654321"]
}
```

### 3. Kiểm tra phân tích hội thoại (Check Conversations)

Phân tích AI kết hợp check nhanh cho đoạn chat.

- **Endpoint**: `POST /api/v1/scam/check-conversations`
- **Body Mẫu**:

```json
{
  "conversations": [
    {
      "phone": "0987654321",
      "messages": [
        { "sender": "Kẻ lạ", "content": "Anh có khoản nợ thuế cần nộp gấp..." },
        { "sender": "Bạn", "content": "Tôi nộp rồi mà?" }
      ]
    }
  ]
}
```

### 4. Báo cáo lừa đảo (Report)

- **Endpoint**: `POST /api/v1/scam/report`
- **Body Mẫu**:

```json
{
  "phone": "+84944555666",
  "type": "IMPERSONATION",
  "source": "SMS_INBOX",
  "description": "Đối tượng mạo danh cán bộ thuế gọi điện hù dọa.",
  "messages": [
    { "sender": "Đối tượng", "content": "Chào anh, tôi là cán bộ thuế..." },
    { "sender": "Bạn", "content": "Link gì đây?" }
  ]
}
```

#### Trường `source` — chống fake report

Client nên gắn `source` chính xác theo cách thu thập dữ liệu. Server dùng `source` để tính độ tin cậy khi quyết định blacklist:

| `source` | Trust | Mô tả | Mobile gợi ý gắn khi |
|---|---:|---|---|
| `SMS_INBOX` | 1.0 | Tin nhắn đọc trực tiếp từ inbox hệ thống | App có `READ_SMS` permission và tự đọc |
| `USER_MANUAL` | 0.4 | User tự gõ tay (default) | Form report thông thường |

**Logic quyết định blacklist** (cho số chưa có trong DB):

Số được đưa vào blacklist khi đáp ứng **một trong hai** đường, **VÀ** AI đồng tình (`is_scam=True`):

1. **Direct path (AI + source uy tín)**: `combined_score = ai_confidence × source_trust ≥ 0.4`.
2. **Consensus path (cộng đồng)**: ≥ **5 user khác nhau** đã từng report số này.

Nếu cả 2 đường đều không đạt → `LOGGED_ONLY`.

| Tình huống | Direct path | Consensus path | Kết quả |
|---|---|---|---|
| `SMS_INBOX`, AI conf 0.5 | ✅ (0.5 ≥ 0.4) | — | blacklist (MEDIUM) |
| `USER_MANUAL`, AI conf 0.9, 1 reporter | ❌ (0.36) | ❌ | LOGGED_ONLY |
| `USER_MANUAL`, AI conf 0.5, 5+ reporters distinct | ❌ | ✅ | blacklist (MEDIUM) |
| `USER_MANUAL`, AI conf 0.0 (AI veto) | ❌ | ❌ | LOGGED_ONLY |
| 1 user spam 100 lần USER_MANUAL | ❌ | ❌ (distinct=1) | LOGGED_ONLY |

**Chống abuse**: 
- 1 user gõ tay (USER_MANUAL) không thể một mình blacklist số mới — direct path không qua (max combined = 0.4 < threshold), consensus cần distinct user.
- 1 user spam nhiều lần cũng vô tác dụng — đếm theo `distinct(user_id)`.
- AI luôn giữ quyền veto — `is_scam=False` thì bất kể bao nhiêu reporters cũng không blacklist.

**Logic cho số đã có trong blacklist**: mọi report đều `reportCount += 1`. Source `SMS_INBOX` bổ sung promotion risk_level lên `CRITICAL` (không bao giờ downgrade).

### 5. Profile

- `GET /api/v1/user/profile` — lấy thông tin user hiện tại
- `PUT /api/v1/user/profile` — update `fullName`, `avatar`, `email`, `birthday`, `gender`

### 6. Chatbot

- `POST /api/v1/chatbot/chat` — body `{ "message": "..." }`

---

## 🧠 Quản lý AI Model

### Huấn luyện lại (Retraining)

Tự động lấy dữ liệu từ những báo cáo thực tế trong Database để dạy cho AI:

```bash
python train_phobert.py
```

---

## 🚀 Deployment (Render — Free tier)

1.  Create a new **Web Service** on Render.
2.  Connect your repository.
3.  Select **Python** as the environment.
4.  **Build Command**:
    ```bash
    pip install -r requirements.txt
    ```
5.  **Start Command** (chạy migration tự động trước khi start app):
    ```bash
    alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
    ```
6.  Add **Environment Variables**:
    *   `SQLALCHEMY_DATABASE_URI`: PostgreSQL connection string.
    *   `SECRET_KEY`: long random string for JWT.
    *   `ACCESS_TOKEN_EXPIRE_MINUTES`: optional, default 60.
    *   `REFRESH_TOKEN_EXPIRE_DAYS`: optional, default 365.
    *   `FIREBASE_CREDENTIALS_JSON`: base64-encoded Firebase service account JSON.
    *   `HF_TOKEN`, `HF_API_URL`: Hugging Face Inference API.
    *   `GEMINI_API_KEY`: Google Gemini API key (optional, for chatbot NLP).

### Ghi chú về auto-migration

- `alembic upgrade head` là **idempotent**: nếu DB đã ở version mới nhất, alembic skip ngay (≈1s overhead).
- Nếu migration fail → app **không start** → instance cũ tiếp tục phục vụ traffic, không có downtime.
- **Trước khi deploy migration ảnh hưởng dữ liệu (drop column / rename)**: backup DB qua Render Dashboard → Postgres → **Backups** → Manual backup.

Render sẽ tự cung cấp biến `$PORT`.
