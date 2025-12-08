from fastapi import APIRouter

from .endpoints import documents, notifications, admin, health, websocket, bank_feed, reports, accounting_ar, accounting_ap, accounting_documents, dashboard

api_router = APIRouter()

api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(websocket.router, prefix="/ws", tags=["websocket"])
api_router.include_router(bank_feed.router, prefix="/bank-feed", tags=["bank-feed"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(accounting_ar.router, prefix="/ar", tags=["accounts-receivable"])
api_router.include_router(accounting_ap.router, prefix="/ap", tags=["accounts-payable"])
api_router.include_router(accounting_documents.router, prefix="/accounting", tags=["accounting-documents"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
