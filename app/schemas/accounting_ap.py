"""Accounts Payable schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.accounting.enums import BillStatus


class APBillCreate(BaseModel):
    """Schema for creating an AP bill."""
    company_id: UUID
    bill_number: str = Field(..., max_length=100)
    bill_date: date
    due_date: date
    currency: str = Field(default="USD", max_length=10)
    total_amount: Decimal = Field(..., decimal_places=2)
    contact_id: UUID


class APBillResponse(BaseModel):
    """Schema for AP bill response."""
    id: UUID
    company_id: UUID
    bill_number: str
    bill_date: date
    due_date: date
    status: BillStatus
    currency: str
    total_amount: Decimal
    balance_amount: Decimal
    contact_id: UUID
    journal_entry_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class APPaymentCreate(BaseModel):
    """Schema for creating an AP payment."""
    company_id: UUID
    payment_number: str = Field(..., max_length=100)
    payment_date: date
    amount: Decimal = Field(..., decimal_places=2)
    payment_method: str = Field(..., max_length=50)
    contact_id: UUID
    bill_id: Optional[UUID] = None


class APPaymentResponse(BaseModel):
    """Schema for AP payment response."""
    id: UUID
    company_id: UUID
    payment_number: str
    payment_date: date
    amount: Decimal
    payment_method: str
    contact_id: UUID
    bill_id: Optional[UUID] = None
    journal_entry_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PostBillResponse(BaseModel):
    """Response after posting a bill."""
    bill: APBillResponse
    journal_entry_id: UUID


class PostPaymentResponse(BaseModel):
    """Response after posting a payment."""
    payment: APPaymentResponse
    journal_entry_id: UUID
    bill_balance: Optional[Decimal] = None
    bill_status: Optional[BillStatus] = None


