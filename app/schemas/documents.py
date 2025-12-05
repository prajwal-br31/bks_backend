"""Document-related schemas."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class DocumentBase(BaseModel):
    """Base document schema."""
    original_filename: str
    content_type: str
    file_size: int


class DocumentResponse(DocumentBase):
    """Document response schema."""
    id: int
    email_id: int
    file_hash: str
    storage_path: str
    document_type: str
    destination: str
    classification_confidence: float
    parsed_fields: Optional[Dict[str, Any]] = None
    ocr_text: Optional[str] = None
    processing_status: str
    processed_at: Optional[datetime] = None
    is_draft: bool
    virus_scanned: bool
    virus_scan_result: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tags: List[str] = []
    
    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Paginated document list response."""
    items: List[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentClassifyRequest(BaseModel):
    """Request to manually classify a document."""
    document_type: str  # invoice, receipt
    destination: Optional[str] = None  # account_payable, account_receivable


class EmailMessageResponse(BaseModel):
    """Email message response schema."""
    id: int
    message_id: str
    from_address: str
    subject: Optional[str]
    received_date: datetime
    processing_status: str
    processed_at: Optional[datetime]
    document_count: int
    
    class Config:
        from_attributes = True

