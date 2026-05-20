# Hướng dẫn tự setup & deploy `real-caller-api` (Local → Render)

Tài liệu này hướng dẫn bạn tự tay setup từ đầu để hiểu luồng triển khai backend.

## 1) Chuẩn bị môi trường

Yêu cầu:
- Python 3.10+
- PostgreSQL 14+ (khuyến nghị)

Tạo virtualenv và cài dependencies:

```bash
cd /path/to/real-caller-api
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 2) Cấu hình biến môi trường

Tạo file `.env` từ mẫu:

```bash
cd /path/to/real-caller-api
cp .env.example .env
```

### Bộ `.env` mẫu để chạy local nhanh

> Thay các giá trị thật theo máy của bạn.

```dotenv
PROJECT_NAME="Check Phone Scam API"
API_V1_STR="/api/v1"
PORT=8000

# BẮT BUỘC
SECRET_KEY=replace_with_a_long_random_secret_key
SQLALCHEMY_DATABASE_URI=postgresql://postgres:postgres@localhost:5432/check-phone-scam

# CORS (đổi theo frontend của bạn)
BACKEND_CORS_ORIGINS=["http://localhost","http://localhost:3000"]

# Tuỳ chọn: AI scam check qua HuggingFace
HF_TOKEN=
HF_API_URL=

# Tuỳ chọn: Firebase auth (chọn 1 trong 2)
FIREBASE_CREDENTIALS_PATH=firebase-adminsdk.json
FIREBASE_CREDENTIALS_JSON=base64_encoded_json_here

# Tuỳ chọn: Gemini chatbot
GEMINI_API_KEY=

# Token config (mặc định)
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=365
```

## 3) Khởi tạo PostgreSQL & chạy migration

Tạo DB rỗng (ví dụ local):

```bash
psql -U postgres -h localhost -c "CREATE DATABASE \"check-phone-scam\";"
```

Chạy migration:

```bash
cd /path/to/real-caller-api
source .venv/bin/activate
alembic upgrade head
```

## 4) Chạy backend local

```bash
cd /path/to/real-caller-api
source .venv/bin/activate
uvicorn app.main:app --reload
```

Kiểm tra nhanh:
- Root: `GET http://localhost:8000/`
- Health: `GET http://localhost:8000/api/v1/health/ping`
- OpenAPI: `http://localhost:8000/docs`

## 5) Dữ liệu test (tuỳ chọn)

Tạo user test:

```bash
cd /path/to/real-caller-api
source .venv/bin/activate
python create_test_user.py
```

Seed dữ liệu:

```bash
cd /path/to/real-caller-api
source .venv/bin/activate
python seed.py
```

Reset DB (cẩn thận, xoá sạch schema `public`):

```bash
cd /path/to/real-caller-api
source .venv/bin/activate
python reset_db.py
```

## 6) Kiểm thử

```bash
cd /path/to/real-caller-api
source .venv/bin/activate
pytest
```

## 7) Deploy lên Render

1. Tạo **Web Service** mới trên Render và connect repository.
2. Environment: **Python**.
3. Build Command:
   ```bash
   pip install -r requirements.txt
   ```
4. Start Command:
   ```bash
   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
5. Set environment variables (giống local, tối thiểu phải có):
   - `SQLALCHEMY_DATABASE_URI` (Render Postgres URL)
   - `SECRET_KEY`
   - `FIREBASE_CREDENTIALS_JSON` hoặc Secret File tương ứng `FIREBASE_CREDENTIALS_PATH`
   - `HF_TOKEN`, `HF_API_URL` (nếu dùng AI scam check)
   - `GEMINI_API_KEY` (nếu dùng chatbot)

Sau deploy, test lại:
- `/api/v1/auth/login`
- `/api/v1/auth/refresh`
- `/api/v1/scam/check-phones`
- `/api/v1/scam/check-conversations`
- `/api/v1/scam/report`
- `/api/v1/user/profile`

## 8) Vận hành sau deploy

- Mỗi lần đổi schema: tạo migration mới rồi deploy để `alembic upgrade head` chạy tự động.
- Trước migration phá hủy dữ liệu (drop/rename): backup DB trên Render trước.
- Theo dõi logs khi boot app để kiểm tra Firebase init và API key đã nạp đúng.
