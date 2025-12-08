"""Dashboard API endpoints."""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.db.dependencies import get_db
from app.services.reporting_service import get_profit_and_loss
from app.models.accounting import (
    ChartOfAccount,
    JournalEntry,
    JournalLine,
    ARInvoice,
    APBill,
)
from app.models.bank_feed import BankTransaction
from app.domain.accounting.enums import (
    AccountType,
    JournalStatus,
    InvoiceStatus,
    BillStatus,
)
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    DashboardKPIs,
    RecentInvoice,
    RecentBill,
    RecentBankTransaction,
    RecentActivity,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def get_default_company_id() -> UUID:
    """Get default company ID for development."""
    return UUID("00000000-0000-0000-0000-000000000001")


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    company_id: Optional[UUID] = Query(None, description="Company ID"),
    as_of: Optional[date] = Query(None, description="As of date (default: today)"),
    db: Session = Depends(get_db),
):
    """
    Get dashboard summary with KPIs and recent activity.
    
    Args:
        company_id: Company UUID (uses default if not provided)
        as_of: As of date for calculations (defaults to today)
        db: Database session
    
    Returns:
        Dashboard summary with KPIs and recent activity
    """
    # Resolve company_id
    if not company_id:
        company_id = get_default_company_id()
    
    # Resolve as_of date
    if not as_of:
        as_of = date.today()
    
    # Calculate current period (current month)
    period_start = date(as_of.year, as_of.month, 1)
    period_end = as_of
    
    # 1) High-level metrics from P&L
    try:
        pnl_data = get_profit_and_loss(
            db=db,
            company_id=company_id,
            date_from=period_start,
            date_to=period_end,
            granularity="monthly",
        )
        
        total_revenue = Decimal(str(pnl_data.get("totals", {}).get("revenue", 0)))
        total_expenses = Decimal(str(pnl_data.get("totals", {}).get("expenses", 0)))
        net_profit = Decimal(str(pnl_data.get("totals", {}).get("net_profit", 0)))
    except Exception as e:
        logger.warning(f"Failed to get P&L data: {e}")
        total_revenue = Decimal("0.00")
        total_expenses = Decimal("0.00")
        net_profit = Decimal("0.00")
    
    # 2) Cash balance (sum of balances for cash accounts)
    # For asset accounts (cash), balance = sum(debit - credit)
    try:
        cash_query = (
            db.query(
                func.sum(JournalLine.debit - JournalLine.credit).label("balance")
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .join(ChartOfAccount, ChartOfAccount.id == JournalLine.account_id)
            .filter(
                ChartOfAccount.company_id == company_id,
                ChartOfAccount.is_cash == True,
                ChartOfAccount.is_active == True,
                JournalEntry.date <= as_of,
                JournalEntry.status == JournalStatus.POSTED,
            )
        )
        cash_result = cash_query.scalar()
        cash_balance = Decimal(str(cash_result)) if cash_result is not None else Decimal("0.00")
    except Exception as e:
        logger.warning(f"Failed to get cash balance: {e}")
        cash_balance = Decimal("0.00")
    
    # 3) AR metrics
    try:
        # Total open AR
        ar_open_query = (
            db.query(
                func.sum(ARInvoice.balance_amount).label("total"),
                func.count(ARInvoice.id).label("count")
            )
            .filter(
                ARInvoice.company_id == company_id,
                ARInvoice.status != InvoiceStatus.PAID,
                ARInvoice.status != InvoiceStatus.VOID,
            )
        )
        ar_open_result = ar_open_query.first()
        ar_total_open = Decimal(str(ar_open_result.total)) if ar_open_result and ar_open_result.total else Decimal("0.00")
        ar_count_open = ar_open_result.count if ar_open_result else 0
        
        # Overdue AR
        ar_overdue_query = (
            db.query(func.sum(ARInvoice.balance_amount).label("total"))
            .filter(
                ARInvoice.company_id == company_id,
                ARInvoice.due_date < as_of,
                ARInvoice.status != InvoiceStatus.PAID,
                ARInvoice.status != InvoiceStatus.VOID,
            )
        )
        ar_overdue_result = ar_overdue_query.scalar()
        ar_overdue = Decimal(str(ar_overdue_result)) if ar_overdue_result else Decimal("0.00")
    except Exception as e:
        logger.warning(f"Failed to get AR metrics: {e}")
        ar_total_open = Decimal("0.00")
        ar_overdue = Decimal("0.00")
        ar_count_open = 0
    
    # 4) AP metrics
    try:
        # Total open AP
        ap_open_query = (
            db.query(
                func.sum(APBill.balance_amount).label("total"),
                func.count(APBill.id).label("count")
            )
            .filter(
                APBill.company_id == company_id,
                APBill.status != BillStatus.PAID,
                APBill.status != BillStatus.VOID,
            )
        )
        ap_open_result = ap_open_query.first()
        ap_total_open = Decimal(str(ap_open_result.total)) if ap_open_result and ap_open_result.total else Decimal("0.00")
        ap_count_open = ap_open_result.count if ap_open_result else 0
        
        # Overdue AP
        ap_overdue_query = (
            db.query(func.sum(APBill.balance_amount).label("total"))
            .filter(
                APBill.company_id == company_id,
                APBill.due_date < as_of,
                APBill.status != BillStatus.PAID,
                APBill.status != BillStatus.VOID,
            )
        )
        ap_overdue_result = ap_overdue_query.scalar()
        ap_overdue = Decimal(str(ap_overdue_result)) if ap_overdue_result else Decimal("0.00")
    except Exception as e:
        logger.warning(f"Failed to get AP metrics: {e}")
        ap_total_open = Decimal("0.00")
        ap_overdue = Decimal("0.00")
        ap_count_open = 0
    
    # 5) Recent activity
    try:
        # Last 5 invoices
        recent_invoices = (
            db.query(ARInvoice)
            .filter(ARInvoice.company_id == company_id)
            .order_by(ARInvoice.invoice_date.desc())
            .limit(5)
            .all()
        )
        invoices_data = [
            RecentInvoice(
                id=inv.id,
                invoice_number=inv.invoice_number,
                invoice_date=inv.invoice_date,
                due_date=inv.due_date,
                total_amount=Decimal(str(inv.total_amount)),
                balance_amount=Decimal(str(inv.balance_amount)),
                status=inv.status.value,
                currency=inv.currency,
            )
            for inv in recent_invoices
        ]
    except Exception as e:
        logger.warning(f"Failed to get recent invoices: {e}")
        invoices_data = []
    
    try:
        # Last 5 bills
        recent_bills = (
            db.query(APBill)
            .filter(APBill.company_id == company_id)
            .order_by(APBill.bill_date.desc())
            .limit(5)
            .all()
        )
        bills_data = [
            RecentBill(
                id=bill.id,
                bill_number=bill.bill_number,
                bill_date=bill.bill_date,
                due_date=bill.due_date,
                total_amount=Decimal(str(bill.total_amount)),
                balance_amount=Decimal(str(bill.balance_amount)),
                status=bill.status.value,
                currency=bill.currency,
            )
            for bill in recent_bills
        ]
    except Exception as e:
        logger.warning(f"Failed to get recent bills: {e}")
        bills_data = []
    
    try:
        # Last 5 bank transactions
        recent_transactions = (
            db.query(BankTransaction)
            .order_by(BankTransaction.date.desc())
            .limit(5)
            .all()
        )
        transactions_data = [
            RecentBankTransaction(
                id=txn.id,
                date=txn.date,
                description=txn.description,
                amount=float(txn.amount),
                type=txn.type.value if hasattr(txn.type, 'value') else (str(txn.type) if txn.type else "unknown"),
                balance=float(txn.balance) if txn.balance else None,
            )
            for txn in recent_transactions
        ]
    except Exception as e:
        logger.warning(f"Failed to get recent bank transactions: {e}")
        transactions_data = []
    
    # Build response
    kpis = DashboardKPIs(
        revenue=total_revenue,
        expenses=total_expenses,
        net_profit=net_profit,
        cash_balance=cash_balance,
        ar_total_open=ar_total_open,
        ap_total_open=ap_total_open,
        ar_overdue=ar_overdue,
        ap_overdue=ap_overdue,
        ar_count_open=ar_count_open,
        ap_count_open=ap_count_open,
    )
    
    recent = RecentActivity(
        invoices=invoices_data,
        bills=bills_data,
        bank_transactions=transactions_data,
    )
    
    return DashboardSummaryResponse(
        as_of=as_of,
        company_id=company_id,
        kpis=kpis,
        recent=recent,
    )

