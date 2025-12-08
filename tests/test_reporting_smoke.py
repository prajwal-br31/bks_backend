"""Smoke tests for reporting service.

Note: These tests require a database connection and will create test data.
Run with: pytest tests/test_reporting_smoke.py
"""

import pytest
from datetime import date
from decimal import Decimal
from uuid import uuid4, UUID

from sqlalchemy.orm import Session

from app.models.accounting import (
    ChartOfAccount,
    JournalEntry,
    JournalLine,
)
from app.domain.accounting.enums import (
    AccountType,
    JournalStatus,
    SourceModule,
)
from app.services.reporting_service import (
    get_profit_and_loss,
    get_balance_sheet,
    get_cash_flow,
)
from app.db.session import SessionLocal


@pytest.fixture
def db() -> Session:
    """Provide database session for tests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_company_id() -> UUID:
    """Generate a test company ID."""
    return uuid4()


@pytest.fixture
def sample_accounts(db: Session, test_company_id: UUID):
    """Create sample chart of accounts."""
    # Revenue account
    revenue_account = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="4000",
        name="Sales Revenue",
        account_type=AccountType.REVENUE,
        is_active=True,
    )
    db.add(revenue_account)
    
    # Expense account
    expense_account = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="5000",
        name="Operating Expenses",
        account_type=AccountType.EXPENSE,
        is_active=True,
    )
    db.add(expense_account)
    
    # Asset account (cash)
    cash_account = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="1000",
        name="Cash",
        account_type=AccountType.ASSET,
        is_cash=True,
        is_active=True,
    )
    db.add(cash_account)
    
    # Asset account (non-cash)
    asset_account = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="1100",
        name="Accounts Receivable",
        account_type=AccountType.ASSET,
        is_cash=False,
        is_active=True,
    )
    db.add(asset_account)
    
    db.commit()
    db.refresh(revenue_account)
    db.refresh(expense_account)
    db.refresh(cash_account)
    db.refresh(asset_account)
    
    return {
        "revenue": revenue_account,
        "expense": expense_account,
        "cash": cash_account,
        "asset": asset_account,
    }


@pytest.fixture
def sample_journal_entries(db: Session, test_company_id: UUID, sample_accounts):
    """Create sample journal entries."""
    # Create a posted journal entry for revenue
    entry1 = JournalEntry(
        id=uuid4(),
        company_id=test_company_id,
        date=date(2025, 1, 15),
        description="Sales transaction",
        source_module=SourceModule.MANUAL,
        status=JournalStatus.POSTED,
    )
    db.add(entry1)
    db.flush()
    
    # Revenue line (credit)
    line1 = JournalLine(
        id=uuid4(),
        journal_entry_id=entry1.id,
        account_id=sample_accounts["revenue"].id,
        description="Sales",
        debit=Decimal("0.00"),
        credit=Decimal("10000.00"),
    )
    db.add(line1)
    
    # Cash line (debit)
    line2 = JournalLine(
        id=uuid4(),
        journal_entry_id=entry1.id,
        account_id=sample_accounts["cash"].id,
        description="Cash received",
        debit=Decimal("10000.00"),
        credit=Decimal("0.00"),
    )
    db.add(line2)
    
    # Create a posted journal entry for expense
    entry2 = JournalEntry(
        id=uuid4(),
        company_id=test_company_id,
        date=date(2025, 1, 20),
        description="Operating expense",
        source_module=SourceModule.MANUAL,
        status=JournalStatus.POSTED,
    )
    db.add(entry2)
    db.flush()
    
    # Expense line (debit)
    line3 = JournalLine(
        id=uuid4(),
        journal_entry_id=entry2.id,
        account_id=sample_accounts["expense"].id,
        description="Operating expense",
        debit=Decimal("3000.00"),
        credit=Decimal("0.00"),
    )
    db.add(line3)
    
    # Cash line (credit)
    line4 = JournalLine(
        id=uuid4(),
        journal_entry_id=entry2.id,
        account_id=sample_accounts["cash"].id,
        description="Cash paid",
        debit=Decimal("0.00"),
        credit=Decimal("3000.00"),
    )
    db.add(line4)
    
    db.commit()
    
    return {
        "revenue_entry": entry1,
        "expense_entry": entry2,
    }


def test_profit_and_loss_smoke(db: Session, test_company_id: UUID, sample_accounts, sample_journal_entries):
    """Smoke test for P&L report."""
    result = get_profit_and_loss(
        db=db,
        company_id=test_company_id,
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
        granularity="monthly",
    )
    
    assert "periods" in result
    assert "accounts" in result
    assert "totals" in result
    
    # Check that we have revenue and expense accounts
    account_types = [acc["type"] for acc in result["accounts"]]
    assert "REVENUE" in account_types or "EXPENSE" in account_types
    
    # Check totals structure
    assert "revenue" in result["totals"]
    assert "expenses" in result["totals"]
    assert "net_profit" in result["totals"]
    
    # Net profit should equal revenue - expenses
    calculated_net = result["totals"]["revenue"] - result["totals"]["expenses"]
    assert abs(result["totals"]["net_profit"] - calculated_net) < 0.01


def test_balance_sheet_smoke(db: Session, test_company_id: UUID, sample_accounts, sample_journal_entries):
    """Smoke test for Balance Sheet report."""
    result = get_balance_sheet(
        db=db,
        company_id=test_company_id,
        as_of=date(2025, 1, 31),
    )
    
    assert "as_of" in result
    assert "sections" in result
    assert "check" in result
    
    # Check that we have sections
    assert len(result["sections"]) > 0
    
    # Check balance equation: Assets = Liabilities + Equity
    assets = result["check"]["assets"]
    liabilities_plus_equity = result["check"]["liabilities_plus_equity"]
    # Allow small floating point differences
    assert abs(assets - liabilities_plus_equity) < 0.01


def test_cash_flow_smoke(db: Session, test_company_id: UUID, sample_accounts, sample_journal_entries):
    """Smoke test for Cash Flow report."""
    result = get_cash_flow(
        db=db,
        company_id=test_company_id,
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
    )
    
    assert "period" in result
    assert "opening_cash" in result
    assert "closing_cash" in result
    assert "categories" in result
    assert "net_change_in_cash" in result
    
    # Check categories structure
    assert "OPERATING" in result["categories"]
    assert "INVESTING" in result["categories"]
    assert "FINANCING" in result["categories"]
    
    # Check that closing = opening + net_change
    calculated_closing = result["opening_cash"] + result["net_change_in_cash"]
    assert abs(result["closing_cash"] - calculated_closing) < 0.01

