"""Accounts Receivable models."""

from datetime import datetime, date
from uuid import uuid4, UUID
from sqlalchemy import String, Date, Enum, Numeric
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import Base
from app.domain.accounting.enums import InvoiceStatus


class ARInvoice(Base):
    """Accounts Receivable Invoice model."""
    
    __tablename__ = "ar_invoices"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus), 
        default=InvoiceStatus.DRAFT,
        nullable=False
    )
    
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    balance_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    journal_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )


class ARReceipt(Base):
    """Accounts Receivable Receipt (Payment) model."""
    
    __tablename__ = "ar_receipts"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    
    receipt_number: Mapped[str] = mapped_column(String(100), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    invoice_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    journal_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )
