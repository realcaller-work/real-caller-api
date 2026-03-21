from fastapi import APIRouter
from app.api.v1.endpoints import health, device, scam

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(device.router, prefix="/device", tags=["device"])
api_router.include_router(scam.router, prefix="/scam", tags=["scam"])
