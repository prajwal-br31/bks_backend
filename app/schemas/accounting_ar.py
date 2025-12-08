"""Accounts Receivable schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.accounting.enums import InvoiceStatus


class ARInvoiceCreate(BaseModel):
    """Schema for creating an AR invoice."""
    company_id: UUID
    invoice_number: str = Field(..., max_length=100)
    invoice_date: date
    due_date: date
    currency: str = Field(default="USD", max_length=10)
    total_amount: Decimal = Field(..., decimal_places=2)
    contact_id: UUID


class ARInvoiceResponse(BaseModel):
    """Schema for AR invoice response."""
    id: UUID
    company_id: UUID
    invoice_number: str
    invoice_date: date
    due_date: date
    status: InvoiceStatus
    currency: str
    total_amount: Decimal
    balance_amount: Decimal
    contact_id: UUID
    journal_entry_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ARReceiptCreate(BaseModel):
    """Schema for creating an AR receipt."""
    company_id: UUID
    receipt_number: str = Field(..., max_length=100)
    receipt_date: date
    amount: Decimal = Field(..., decimal_places=2)
    payment_method: str = Field(..., max_length=50)
    contact_id: UUID
    invoice_id: Optional[UUID] = None


class ARReceiptResponse(BaseModel):
    """Schema for AR receipt response."""
    id: UUID
    company_id: UUID
    receipt_number: str
    receipt_date: date
    amount: Decimal
    payment_method: str
    contact_id: UUID
    invoice_id: Optional[UUID] = None
    journal_entry_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PostInvoiceResponse(BaseModel):
    """Response after posting an invoice."""
    invoice: ARInvoiceResponse
    journal_entry_id: UUID


class PostReceiptResponse(BaseModel):
    """Response after posting a receipt."""
    receipt: ARReceiptResponse
    journal_entry_id: UUID
    invoice_balance: Optional[Decimal] = None
    invoice_status: Optional[InvoiceStatus] = None



