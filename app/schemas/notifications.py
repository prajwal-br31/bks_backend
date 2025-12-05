"""Notification-related schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class NotificationResponse(BaseModel):
    """Notification response schema."""
    id: str
    title: str
    message: str
    reference: str
    amount: str
    source: str
    type: str
    status: str  # read, unread
    dismissed: bool
    createdAt: str
    actions: Optional[List[Dict[str, Any]]] = None
    severity: str
    
    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Notification list response."""
    items: List[NotificationResponse]
    total: int
    unread_count: int


class NotificationActionRequest(BaseModel):
    """Request to perform action on notification."""
    action: str  # mark_read, dismiss, classify, reject, retry
    params: Optional[Dict[str, Any]] = None

