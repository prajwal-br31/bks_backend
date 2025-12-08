"""Bank Feed models for transaction import and matching."""

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
)
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin


class TransactionType(str, PyEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class TransactionStatus(str, PyEnum):
    PENDING = "pending"
    MATCHED = "matched"
    REVIEWED = "reviewed"
    CLEARED = "cleared"
    RECONCILED = "reconciled"
    EXCLUDED = "excluded"


class MatchedEntityType(str, PyEnum):
    AR = "ar"  # Account Receivable
    AP = "ap"  # Account Payable
    EXPENSE = "expense"


class FileStatus(str, PyEnum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REPROCESSING = "reprocessing"


class ClassificationStatus(str, PyEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"


class BankFile(Base, TimestampMixin):
    """Uploaded bank statement file."""
    __tablename__ = "bank_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # File information
    original_filename = Column(String(500), nullable=False)
    storage_path = Column(String(1000), nullable=False)  # S3 path
    file_size = Column(Integer, nullable=True)
    content_type = Column(String(100), nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA-256
    
    # Processing info
    status = Column(Enum(FileStatus, native_enum=False, length=50), default=FileStatus.UPLOADING, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    
    # Parse results
    total_rows = Column(Integer, default=0)
    parsed_rows = Column(Integer, default=0)
    skipped_rows = Column(Integer, default=0)
    
    # Metadata
    bank_name = Column(String(100), nullable=True)  # e.g., "Chase", "Bank of America"
    account_number_last4 = Column(String(4), nullable=True)
    statement_start_date = Column(DateTime, nullable=True)
    statement_end_date = Column(DateTime, nullable=True)
    
    # User info
    uploaded_by = Column(String(255), nullable=True)
    
    # AI Classification
    classification_status = Column(Enum(ClassificationStatus, native_enum=False, length=50), default=ClassificationStatus.PENDING, nullable=False)
    classification_progress = Column(Integer, default=0, nullable=False)  # 0-100
    last_classification_error = Column(Text, nullable=True)
    
    # Relationships
    transactions = relationship("BankTransaction", back_populates="bank_file", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<BankFile(id={self.id}, filename='{self.original_filename}', status={self.status})>"


class BankTransaction(Base, TimestampMixin):
    """Individual bank transaction from imported file."""
    __tablename__ = "bank_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Source file
    bank_file_id = Column(Integer, ForeignKey("bank_files.id"), nullable=False, index=True)
    bank_file = relationship("BankFile", back_populates="transactions")
    
    # Transaction details
    external_id = Column(String(255), nullable=True, index=True)  # Bank's transaction ID if available
    date = Column(DateTime, nullable=False, index=True)
    post_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(Enum(TransactionType, native_enum=False, length=50), nullable=False)
    balance = Column(Float, nullable=True)
    
    # Categorization
    category = Column(String(100), nullable=True)
    memo = Column(Text, nullable=True)
    check_number = Column(String(50), nullable=True)
    
    # Status
    status = Column(Enum(TransactionStatus, native_enum=False, length=50), default=TransactionStatus.PENDING, nullable=False, index=True)
    
    # AI Classification
    ai_category = Column(String(100), nullable=True)  # e.g. "BANK_FEE", "CARD_PAYMENT", "VENDOR_PAYMENT"
    ai_subcategory = Column(String(200), nullable=True)  # e.g. "BacklotCars - Auto Purchase"
    ai_confidence = Column(Float, nullable=True)  # 0.0 to 1.0
    ai_ledger_hint = Column(String(50), nullable=True)  # e.g. "OPERATING_EXPENSE", "OWNER_DRAW"
    classification_status = Column(Enum(ClassificationStatus, native_enum=False, length=50), default=ClassificationStatus.PENDING, nullable=False, index=True)
    
    # Raw data
    raw_data = Column(JSON, nullable=True)  # Original row data
    row_number = Column(Integer, nullable=True)  # Row number in source file
    
    # Relationships
    match = relationship("BankMatch", back_populates="bank_transaction", uselist=False)

    def __repr__(self):
        return f"<BankTransaction(id={self.id}, date='{self.date}', amount={self.amount}, status={self.status})>"


class BankMatch(Base, TimestampMixin):
    """Match between bank transaction and AP/AR/Expense."""
    __tablename__ = "bank_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Bank transaction
    bank_transaction_id = Column(Integer, ForeignKey("bank_transactions.id"), nullable=False, unique=True, index=True)
    bank_transaction = relationship("BankTransaction", back_populates="match")
    
    # Matched entity
    matched_type = Column(Enum(MatchedEntityType, native_enum=False, length=50), nullable=False)
    matched_id = Column(Integer, nullable=False)  # ID in the matched table
    matched_reference = Column(String(100), nullable=True)  # e.g., Invoice number
    matched_name = Column(String(255), nullable=True)  # e.g., Vendor name
    
    # Match details
    match_confidence = Column(Float, nullable=True)  # 0.0 to 1.0 for auto-matches
    is_auto_matched = Column(Boolean, default=False)
    matched_by = Column(String(255), nullable=True)  # User who confirmed match
    matched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Notes
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return f"<BankMatch(id={self.id}, type={self.matched_type}, entity_id={self.matched_id})>"


class BankFeedAuditLog(Base):
    """Audit trail for bank feed operations."""
    __tablename__ = "bank_feed_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # What happened
    action = Column(String(100), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    
    # Who/what did it
    actor_type = Column(String(50), nullable=False)  # "user", "system", "api"
    actor_id = Column(String(255), nullable=True)
    actor_name = Column(String(255), nullable=True)
    
    # When
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Related entities
    bank_file_id = Column(Integer, ForeignKey("bank_files.id"), nullable=True, index=True)
    bank_transaction_id = Column(Integer, ForeignKey("bank_transactions.id"), nullable=True, index=True)
    bank_match_id = Column(Integer, ForeignKey("bank_matches.id"), nullable=True, index=True)

    def __repr__(self):
        return f"<BankFeedAuditLog(action='{self.action}', timestamp={self.timestamp})>"
