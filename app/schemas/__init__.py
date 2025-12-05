"""Pydantic schemas for API requests and responses."""

from .documents import (
    DocumentBase,
    DocumentResponse,
    DocumentListResponse,
    DocumentClassifyRequest,
    EmailMessageResponse,
)
from .notifications import (
    NotificationResponse,
    NotificationListResponse,
    NotificationActionRequest,
)
from .admin import (
    ProcessingStatsResponse,
    ReprocessRequest,
    ManualTagRequest,
)

__all__ = [
    "DocumentBase",
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentClassifyRequest",
    "EmailMessageResponse",
    "NotificationResponse",
    "NotificationListResponse",
    "NotificationActionRequest",
    "ProcessingStatsResponse",
    "ReprocessRequest",
    "ManualTagRequest",
]

