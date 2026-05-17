from fastapi import APIRouter
from app.api.v1.endpoints import health, scam, auth, user, chatbot

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(user.router, prefix="/user", tags=["user"])
api_router.include_router(scam.router, prefix="/scam", tags=["scam"])
api_router.include_router(chatbot.router, prefix="/chatbot", tags=["chatbot"])
