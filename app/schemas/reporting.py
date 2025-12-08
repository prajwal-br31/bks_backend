"""Reporting schemas for accounting reports."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# Profit & Loss Schemas
class PnLAccountPeriodAmounts(BaseModel):
    """Period amounts for a P&L account."""
    period: str
    amount: float


class PnLAccountRow(BaseModel):
    """A single account row in P&L report."""
    account_id: str
    code: str
    name: str
    type: str  # "REVENUE" or "EXPENSE"
    period_amounts: Dict[str, float] = Field(default_factory=dict)
    total: float


class PnLResponse(BaseModel):
    """Profit & Loss report response."""
    periods: List[str]
    accounts: List[PnLAccountRow]
    totals: Dict[str, float]  # revenue, expenses, net_profit


# Balance Sheet Schemas
class BalanceSheetAccount(BaseModel):
    """A single account in balance sheet."""
    code: str
    name: str
    balance: float


class BalanceSheetSection(BaseModel):
    """A section in balance sheet (Assets, Liabilities, Equity)."""
    name: str
    total: float
    accounts: List[BalanceSheetAccount]


class BalanceSheetResponse(BaseModel):
    """Balance Sheet report response."""
    as_of: str
    sections: List[BalanceSheetSection]
    check: Dict[str, float]  # assets, liabilities_plus_equity


# Cash Flow Schemas
class CashFlowCategoryBreakdown(BaseModel):
    """Breakdown for a cash flow category."""
    inflows: float
    outflows: float
    net: float


class CashFlowResponse(BaseModel):
    """Cash Flow report response."""
    period: Dict[str, str]  # from, to
    opening_cash: float
    closing_cash: float
    categories: Dict[str, CashFlowCategoryBreakdown]  # OPERATING, INVESTING, FINANCING
    net_change_in_cash: float


