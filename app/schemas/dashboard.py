"""Dashboard schemas for summary API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    """Key Performance Indicators for dashboard."""
    revenue: Decimal = Decimal("0.00")
    expenses: Decimal = Decimal("0.00")
    net_profit: Decimal = Decimal("0.00")
    cash_balance: Decimal = Decimal("0.00")
    ar_total_open: Decimal = Decimal("0.00")
    ap_total_open: Decimal = Decimal("0.00")
    ar_overdue: Decimal = Decimal("0.00")
    ap_overdue: Decimal = Decimal("0.00")
    ar_count_open: int = 0
    ap_count_open: int = 0


class RecentInvoice(BaseModel):
    """Recent AR Invoice summary."""
    id: UUID
    invoice_number: str
    invoice_date: date
    due_date: date
    total_amount: Decimal
    balance_amount: Decimal
    status: str
    currency: str

    class Config:
        from_attributes = True


class RecentBill(BaseModel):
    """Recent AP Bill summary."""
    id: UUID
    bill_number: str
    bill_date: date
    due_date: date
    total_amount: Decimal
    balance_amount: Decimal
    status: str
    currency: str

    class Config:
        from_attributes = True


class RecentBankTransaction(BaseModel):
    """Recent bank transaction summary."""
    id: int
    date: datetime
    description: str
    amount: float
    type: str
    balance: Optional[float] = None

    class Config:
        from_attributes = True


class RecentActivity(BaseModel):
    """Recent activity items."""
    invoices: List[RecentInvoice] = []
    bills: List[RecentBill] = []
    bank_transactions: List[RecentBankTransaction] = []


class DashboardSummaryResponse(BaseModel):
    """Dashboard summary response."""
    as_of: date
    company_id: UUID
    kpis: DashboardKPIs
    recent: RecentActivity



