from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import engine
from app.models.base import Base
# Import models to ensure they are registered with Base
from app.models.device import Device
from app.models.scam_number import ScamNumber
from app.models.scam_report import ScamReport
from app.models.user import User
from app.models.chat_history import ChatHistory

import os
import json
import base64
import firebase_admin
from firebase_admin import credentials

try:
    firebase_json_value = settings.FIREBASE_CREDENTIALS_JSON
    firebase_file_path = settings.FIREBASE_CREDENTIALS_PATH
    
    # Render Secret Files: /etc/secrets/<filename>
    render_secret_path = f"/etc/secrets/{os.path.basename(firebase_file_path)}"
    
    print(f"[Firebase] FIREBASE_CREDENTIALS_JSON length: {len(firebase_json_value)}")
    print(f"[Firebase] FIREBASE_CREDENTIALS_PATH: {firebase_file_path} (exists: {os.path.exists(firebase_file_path)})")
    print(f"[Firebase] Render Secret File: {render_secret_path} (exists: {os.path.exists(render_secret_path)})")
    
    if firebase_json_value and firebase_json_value != "base64_encoded_json_here":
        # Priority 1: Load from env var (base64 or raw JSON)
        cred_dict = None
        try:
            cred_dict = json.loads(base64.b64decode(firebase_json_value).decode('utf-8'))
            print("[Firebase] Decoded from Base64 successfully.")
        except (ValueError, TypeError, base64.binascii.Error):
            pass
        
        if cred_dict is None:
            try:
                cred_dict = json.loads(firebase_json_value)
                print("[Firebase] Parsed as raw JSON string successfully.")
            except json.JSONDecodeError as e:
                print(f"[Firebase] ERROR: Failed to parse FIREBASE_CREDENTIALS_JSON: {e}")
        
        if cred_dict:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            print("Firebase Admin initialized from Env (FIREBASE_CREDENTIALS_JSON).")
        else:
            print("Warning: FIREBASE_CREDENTIALS_JSON is set but could not be parsed.")
    elif os.path.exists(render_secret_path):
        # Priority 2: Render Secret Files (/etc/secrets/<filename>)
        cred = credentials.Certificate(render_secret_path)
        firebase_admin.initialize_app(cred)
        print(f"Firebase Admin initialized from Render Secret File ({render_secret_path}).")
    elif os.path.exists(firebase_file_path):
        # Priority 3: Local file (for development)
        cred = credentials.Certificate(firebase_file_path)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin initialized from local file.")
    else:
        print("Warning: Firebase credentials not found. Upload Secret File on Render or set FIREBASE_CREDENTIALS_JSON.")
except ValueError:
    pass # App already initialized (sometimes occurs in hot reload)
except Exception as e:
    print(f"Firebase init error: {e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Removed static mount for uploads since the API is redundant

# Removed startup event trying to recreate tables (handled by Alembic)
# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {"message": "Welcome to Check Phone Scam API"}

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", settings.PORT))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
