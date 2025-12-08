"""Tests for AP API endpoints."""

import pytest
from datetime import date
from decimal import Decimal
from uuid import uuid4, UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.accounting import (
    ChartOfAccount,
    APBill,
    JournalEntry,
    JournalLine,
)
from app.domain.accounting.enums import (
    AccountType,
    BillStatus,
    JournalStatus,
    SourceModule,
)
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


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
def sample_chart_of_accounts(db: Session, test_company_id: UUID):
    """Create sample chart of accounts for testing."""
    # Expense account
    expense = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="5000",
        name="Operating Expenses",
        account_type=AccountType.EXPENSE,
        is_active=True,
    )
    db.add(expense)
    
    # Accounts Payable
    ap_account = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="2000",
        name="Accounts Payable",
        account_type=AccountType.LIABILITY,
        is_active=True,
    )
    db.add(ap_account)
    
    # Cash account
    cash = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="1000",
        name="Cash",
        account_type=AccountType.ASSET,
        is_cash=True,
        is_active=True,
    )
    db.add(cash)
    
    db.commit()
    
    return {
        "expense": expense,
        "ap": ap_account,
        "cash": cash,
    }


def test_create_and_post_bill(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test creating a bill and posting it creates journal entry."""
    # Create bill via API
    bill_data = {
        "company_id": str(test_company_id),
        "bill_number": "BILL-API-001",
        "bill_date": "2025-01-10",
        "due_date": "2025-02-10",
        "currency": "USD",
        "total_amount": "5000.00",
        "contact_id": str(uuid4()),
    }
    
    response = client.post("/api/v1/ap/bills", json=bill_data)
    assert response.status_code == 201
    
    bill_response = response.json()
    bill_id = bill_response["id"]
    
    # Verify bill was created
    assert bill_response["bill_number"] == "BILL-API-001"
    assert bill_response["status"] == "draft"
    assert bill_response["total_amount"] == "5000.00"
    assert bill_response["balance_amount"] == "5000.00"
    assert bill_response["journal_entry_id"] is None
    
    # Post the bill
    post_response = client.post(f"/api/v1/ap/bills/{bill_id}/post")
    assert post_response.status_code == 200
    
    post_data = post_response.json()
    assert post_data["journal_entry_id"] is not None
    assert post_data["bill"]["status"] == "approved"
    assert post_data["bill"]["journal_entry_id"] == post_data["journal_entry_id"]
    
    # Verify journal entry was created in database
    journal_entry_id = UUID(post_data["journal_entry_id"])
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    assert je is not None
    assert je.company_id == test_company_id
    assert je.source_module == SourceModule.AP
    assert je.status == JournalStatus.POSTED
    
    # Verify journal lines
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    assert len(lines) == 2
    
    # Check that debits equal credits
    total_debit = sum(line.debit for line in lines)
    total_credit = sum(line.credit for line in lines)
    assert total_debit == total_credit
    assert total_debit == Decimal("5000.00")



