from fastapi import APIRouter

from .endpoints import documents, notifications, admin, health, websocket, bank_feed

api_router = APIRouter()

api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(websocket.router, prefix="/ws", tags=["websocket"])
api_router.include_router(bank_feed.router, prefix="/bank-feed", tags=["bank-feed"])
