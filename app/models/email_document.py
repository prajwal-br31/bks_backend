from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, 
    ForeignKey, Enum, JSON, Index
)
from sqlalchemy.orm import relationship
import enum

from .base import Base, TimestampMixin


class DocumentType(str, enum.Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    STATEMENT = "statement"
    UNKNOWN = "unknown"


class DocumentDestination(str, enum.Enum):
    ACCOUNT_PAYABLE = "account_payable"
    ACCOUNT_RECEIVABLE = "account_receivable"
    NEEDS_REVIEW = "needs_review"


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    VIRUS_DETECTED = "virus_detected"


class EmailMessage(Base, TimestampMixin):
    """Stores ingested email messages."""
    __tablename__ = "email_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Email identifiers
    message_id = Column(String(512), unique=True, nullable=False, index=True)
    thread_id = Column(String(256), nullable=True)
    
    # Email metadata
    from_address = Column(String(320), nullable=False)
    to_addresses = Column(Text, nullable=True)  # JSON array
    cc_addresses = Column(Text, nullable=True)  # JSON array
    subject = Column(Text, nullable=True)
    received_date = Column(DateTime, nullable=False)
    
    # Email content
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    
    # Processing info
    source_folder = Column(String(256), nullable=True)
    source_provider = Column(String(50), nullable=False)  # imap or gmail
    processing_status = Column(
        Enum(ProcessingStatus), 
        default=ProcessingStatus.PENDING,
        nullable=False
    )
    processed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Relationships
    documents = relationship("EmailDocument", back_populates="email", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_email_messages_received_date', 'received_date'),
        Index('ix_email_messages_from_address', 'from_address'),
    )


class EmailDocument(Base, TimestampMixin):
    """Stores extracted documents from emails."""
    __tablename__ = "email_documents"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Reference to email
    email_id = Column(Integer, ForeignKey("email_messages.id"), nullable=False)
    email = relationship("EmailMessage", back_populates="documents")
    
    # File information
    original_filename = Column(String(512), nullable=False)
    content_type = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False)  # bytes
    file_hash = Column(String(64), nullable=False)  # SHA-256
    
    # Storage
    storage_path = Column(String(1024), nullable=False)  # S3 key
    storage_bucket = Column(String(256), nullable=False)
    
    # Classification
    document_type = Column(
        Enum(DocumentType), 
        default=DocumentType.UNKNOWN,
        nullable=False
    )
    destination = Column(
        Enum(DocumentDestination), 
        default=DocumentDestination.NEEDS_REVIEW,
        nullable=False
    )
    classification_confidence = Column(Float, default=0.0, nullable=False)
    
    # Parsed data
    parsed_fields = Column(JSON, nullable=True)
    """
    Expected structure:
    {
        "vendor_name": str,
        "invoice_number": str,
        "date": str,
        "due_date": str,
        "total_amount": float,
        "tax_amount": float,
        "currency": str,
        "line_items": [
            {"description": str, "quantity": int, "unit_price": float, "amount": float}
        ]
    }
    """
    
    # OCR
    ocr_text = Column(Text, nullable=True)
    ocr_provider = Column(String(50), nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    
    # Processing
    processing_status = Column(
        Enum(ProcessingStatus), 
        default=ProcessingStatus.PENDING,
        nullable=False
    )
    processed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Virus scan
    virus_scanned = Column(Boolean, default=False, nullable=False)
    virus_scan_result = Column(String(256), nullable=True)
    virus_scanned_at = Column(DateTime, nullable=True)
    
    # Auto-posting
    is_draft = Column(Boolean, default=True, nullable=False)
    posted_at = Column(DateTime, nullable=True)
    posted_by = Column(String(256), nullable=True)
    
    # Relationships
    tags = relationship("DocumentTag", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_email_documents_document_type', 'document_type'),
        Index('ix_email_documents_processing_status', 'processing_status'),
        Index('ix_email_documents_file_hash', 'file_hash'),
    )


class Tag(Base, TimestampMixin):
    """Available tags for documents."""
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    color = Column(String(7), default="#6366f1", nullable=False)  # Hex color
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)  # System tags can't be deleted
    
    # Relationships
    documents = relationship("DocumentTag", back_populates="tag", cascade="all, delete-orphan")


class DocumentTag(Base):
    """Many-to-many relationship between documents and tags."""
    __tablename__ = "document_tags"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("email_documents.id"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    added_by = Column(String(256), nullable=True)  # User or "system"
    
    # Relationships
    document = relationship("EmailDocument", back_populates="tags")
    tag = relationship("Tag", back_populates="documents")
    
    __table_args__ = (
        Index('ix_document_tags_document_id', 'document_id'),
        Index('ix_document_tags_tag_id', 'tag_id'),
    )


class AuditLog(Base):
    """Audit trail for document processing and changes."""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Reference
    document_id = Column(Integer, ForeignKey("email_documents.id"), nullable=True)
    document = relationship("EmailDocument", back_populates="audit_logs")
    
    # Event details
    event_type = Column(String(100), nullable=False)
    """
    Event types:
    - email_received
    - attachment_extracted
    - virus_scanned
    - ocr_processed
    - classified
    - uploaded_to_storage
    - notification_sent
    - manual_review
    - tag_added
    - tag_removed
    - reprocessed
    - posted
    - rejected
    """
    
    event_data = Column(JSON, nullable=True)
    actor = Column(String(256), nullable=True)  # User ID or "system"
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('ix_audit_logs_document_id', 'document_id'),
        Index('ix_audit_logs_event_type', 'event_type'),
        Index('ix_audit_logs_timestamp', 'timestamp'),
    )


class Notification(Base, TimestampMixin):
    """Notifications for the notification center."""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Reference
    document_id = Column(Integer, ForeignKey("email_documents.id"), nullable=True)
    
    # Notification content
    title = Column(String(256), nullable=False)
    message = Column(Text, nullable=False)
    
    # Type and severity
    notification_type = Column(String(50), nullable=False)  # email, excel, teller, manual
    severity = Column(String(20), default="info", nullable=False)  # success, warning, error, info
    
    # Status
    is_read = Column(Boolean, default=False, nullable=False)
    is_dismissed = Column(Boolean, default=False, nullable=False)
    
    # Quick actions (JSON array)
    actions = Column(JSON, nullable=True)
    """
    Example:
    [
        {"label": "View Document", "action": "view", "url": "/documents/123"},
        {"label": "Mark as Invoice", "action": "classify", "params": {"type": "invoice"}},
        {"label": "Reject", "action": "reject"}
    ]
    """
    
    # Metadata
    reference_id = Column(String(100), nullable=True)  # e.g., "TX-2024-001"
    amount = Column(String(50), nullable=True)  # Formatted amount
    source = Column(String(256), nullable=True)  # e.g., "Mailbox automation"
    
    # Target user (null = all users)
    user_id = Column(String(256), nullable=True)
    
    __table_args__ = (
        Index('ix_notifications_user_id', 'user_id'),
        Index('ix_notifications_is_read', 'is_read'),
        Index('ix_notifications_created_at', 'created_at'),
    )

