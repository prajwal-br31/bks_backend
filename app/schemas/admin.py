"""Admin-related schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class ProcessingStatsResponse(BaseModel):
    """Processing statistics response."""
    total_emails: int
    total_documents: int
    processed_count: int
    failed_count: int
    pending_count: int
    needs_review_count: int
    avg_processing_time_seconds: Optional[float]
    documents_by_type: Dict[str, int]
    documents_by_destination: Dict[str, int]


class ReprocessRequest(BaseModel):
    """Request to reprocess a document."""
    document_id: int


class ManualTagRequest(BaseModel):
    """Request to add/remove tags."""
    tag_name: str
    action: str = "add"  # add, remove


class EmailProcessingEntry(BaseModel):
    """Entry for email processing list."""
    id: int
    message_id: str
    from_address: str
    subject: Optional[str]
    received_date: datetime
    processing_status: str
    document_count: int
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class EmailProcessingListResponse(BaseModel):
    """Response for admin email list."""
    items: List[EmailProcessingEntry]
    total: int

