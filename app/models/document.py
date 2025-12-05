from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    Enum,
    JSON,
    ForeignKey,
    Table,
)
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin


class DocumentType(str, PyEnum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    STATEMENT = "statement"
    UNKNOWN = "unknown"


class DocumentStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    REJECTED = "rejected"


class DocumentDestination(str, PyEnum):
    ACCOUNT_PAYABLE = "account_payable"
    ACCOUNT_RECEIVABLE = "account_receivable"
    UNASSIGNED = "unassigned"


class ProcessingStatus(str, PyEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    SCANNING = "scanning"
    EXTRACTING = "extracting"
    CLASSIFYING = "classifying"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


# Many-to-many relationship table for documents and tags
document_tags = Table(
    "document_tags",
    Base.metadata,
    Column("document_id", Integer, ForeignKey("documents.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base, TimestampMixin):
    """Tags for categorizing documents."""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    color = Column(String(7), default="#6366f1")  # Hex color
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False)  # System tags cannot be deleted

    # Relationships
    documents = relationship("Document", secondary=document_tags, back_populates="tags")

    def __repr__(self):
        return f"<Tag(name='{self.name}')>"


class Document(Base, TimestampMixin):
    """Parsed document from email attachments."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Source information
    source_email = Column(String(255), nullable=True, index=True)
    source_email_subject = Column(Text, nullable=True)
    source_email_date = Column(DateTime, nullable=True)
    email_message_id = Column(String(255), nullable=True, unique=True)  # For deduplication
    
    # File information
    original_filename = Column(String(500), nullable=False)
    storage_path = Column(String(1000), nullable=False)  # S3 path
    storage_hash = Column(String(64), nullable=True)  # SHA-256 hash
    content_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)  # In bytes
    
    # Classification
    document_type = Column(Enum(DocumentType), default=DocumentType.UNKNOWN, nullable=False)
    destination = Column(Enum(DocumentDestination), default=DocumentDestination.UNASSIGNED, nullable=False)
    confidence_score = Column(Float, default=0.0)
    
    # Parsed fields (from OCR)
    vendor_name = Column(String(255), nullable=True, index=True)
    invoice_number = Column(String(100), nullable=True, index=True)
    invoice_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    total_amount = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    currency = Column(String(3), default="USD")
    
    # Raw extracted data
    parsed_fields = Column(JSON, nullable=True)  # Full JSON of all parsed fields
    ocr_text = Column(Text, nullable=True)  # Raw OCR text
    line_items = Column(JSON, nullable=True)  # Array of line items
    
    # Status
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True)
    processing_status = Column(Enum(ProcessingStatus), default=ProcessingStatus.QUEUED, nullable=False)
    error_message = Column(Text, nullable=True)
    
    # Flags
    is_draft = Column(Boolean, default=True)
    is_auto_posted = Column(Boolean, default=False)
    requires_review = Column(Boolean, default=False)
    virus_scanned = Column(Boolean, default=False)
    virus_clean = Column(Boolean, default=True)
    
    # Relationships
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")
    processing_job = relationship("EmailProcessingJob", back_populates="documents", uselist=False)
    
    # Foreign keys
    processing_job_id = Column(Integer, ForeignKey("email_processing_jobs.id"), nullable=True)

    def __repr__(self):
        return f"<Document(id={self.id}, filename='{self.original_filename}', type={self.document_type})>"


class EmailProcessingJob(Base, TimestampMixin):
    """Tracks email processing jobs."""
    __tablename__ = "email_processing_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Email information
    email_uid = Column(String(255), nullable=False, index=True)  # UID from mail server
    email_message_id = Column(String(255), nullable=True, unique=True)
    email_from = Column(String(255), nullable=False)
    email_to = Column(String(255), nullable=True)
    email_subject = Column(Text, nullable=True)
    email_date = Column(DateTime, nullable=True)
    email_body_preview = Column(Text, nullable=True)  # First 500 chars
    
    # Processing status
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.QUEUED, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # Celery task tracking
    celery_task_id = Column(String(255), nullable=True, index=True)
    
    # Statistics
    attachments_count = Column(Integer, default=0)
    documents_created = Column(Integer, default=0)
    
    # Relationships
    documents = relationship("Document", back_populates="processing_job")

    def __repr__(self):
        return f"<EmailProcessingJob(id={self.id}, from='{self.email_from}', status={self.status})>"


class AuditLog(Base):
    """Audit trail for document operations."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # What happened
    action = Column(String(100), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    
    # Who/what did it
    actor_type = Column(String(50), nullable=False)  # "system", "user", "celery"
    actor_id = Column(String(255), nullable=True)  # User ID or task ID
    actor_name = Column(String(255), nullable=True)
    
    # When
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Related document
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    document = relationship("Document", back_populates="audit_logs")

    def __repr__(self):
        return f"<AuditLog(action='{self.action}', timestamp={self.timestamp})>"


class Notification(Base, TimestampMixin):
    """Notifications for the notification center."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Content
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    
    # Classification
    notification_type = Column(String(50), nullable=False, index=True)  # email, excel, teller, manual
    severity = Column(String(20), default="info")  # success, warning, error, info
    
    # Reference
    reference_type = Column(String(50), nullable=True)  # document, transaction, etc.
    reference_id = Column(Integer, nullable=True)
    reference_code = Column(String(100), nullable=True)  # e.g., "TX-2193", "DOC-123"
    
    # Metadata
    amount = Column(String(50), nullable=True)
    source = Column(String(255), nullable=True)
    destination = Column(String(100), nullable=True)  # AP, AR, etc.
    link = Column(String(500), nullable=True)  # Link to view document
    
    # Actions (for review notifications)
    actions = Column(JSON, nullable=True)  # Array of action buttons
    
    # Status
    status = Column(String(20), default="unread", index=True)  # unread, read, dismissed
    dismissed = Column(Boolean, default=False)
    
    # User targeting (if null, visible to all)
    user_id = Column(String(255), nullable=True, index=True)

    def __repr__(self):
        return f"<Notification(id={self.id}, title='{self.title}', type={self.notification_type})>"

