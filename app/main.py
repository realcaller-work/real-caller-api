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
    if settings.FIREBASE_CREDENTIALS_JSON:
        # Load from base64 string
        try:
            cred_dict = json.loads(base64.b64decode(settings.FIREBASE_CREDENTIALS_JSON).decode('utf-8'))
        except (ValueError, TypeError, base64.binascii.Error):
            # Fallback to direct json string parse
            cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
            
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin initialized from Secret Env (FIREBASE_CREDENTIALS_JSON).")
    elif os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin initialized from file.")
    else:
        print("⚠️ Warning: Firebase credentials not found.")
except ValueError:
    pass # App already initialized (sometimes occurs in hot reload)

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
