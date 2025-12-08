"""Accounts Payable models."""

from datetime import datetime, date
from uuid import uuid4, UUID
from sqlalchemy import String, Date, Enum, Numeric
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.base import Base
from app.domain.accounting.enums import BillStatus


class APBill(Base):
    """Accounts Payable Bill model."""
    
    __tablename__ = "ap_bills"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    
    bill_number: Mapped[str] = mapped_column(String(100), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus), 
        default=BillStatus.DRAFT,
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


class APPayment(Base):
    """Accounts Payable Payment model."""
    
    __tablename__ = "ap_payments"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    
    payment_number: Mapped[str] = mapped_column(String(100), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    bill_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    journal_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )
