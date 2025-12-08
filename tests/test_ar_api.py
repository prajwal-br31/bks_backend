"""Tests for AR API endpoints."""

import pytest
from datetime import date
from decimal import Decimal
from uuid import uuid4, UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.accounting import (
    ChartOfAccount,
    ARInvoice,
    JournalEntry,
    JournalLine,
)
from app.domain.accounting.enums import (
    AccountType,
    InvoiceStatus,
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
    # Revenue account
    revenue = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="4000",
        name="Sales Revenue",
        account_type=AccountType.REVENUE,
        is_active=True,
    )
    db.add(revenue)
    
    # Accounts Receivable
    ar_account = ChartOfAccount(
        id=uuid4(),
        company_id=test_company_id,
        code="1200",
        name="Accounts Receivable",
        account_type=AccountType.ASSET,
        is_active=True,
    )
    db.add(ar_account)
    
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
        "revenue": revenue,
        "ar": ar_account,
        "cash": cash,
    }


def test_create_and_post_invoice(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test creating an invoice and posting it creates journal entry."""
    # Create invoice via API
    invoice_data = {
        "company_id": str(test_company_id),
        "invoice_number": "INV-API-001",
        "invoice_date": "2025-01-15",
        "due_date": "2025-02-15",
        "currency": "USD",
        "total_amount": "10000.00",
        "contact_id": str(uuid4()),
    }
    
    response = client.post("/api/v1/ar/invoices", json=invoice_data)
    assert response.status_code == 201
    
    invoice_response = response.json()
    invoice_id = invoice_response["id"]
    
    # Verify invoice was created
    assert invoice_response["invoice_number"] == "INV-API-001"
    assert invoice_response["status"] == "draft"
    assert invoice_response["total_amount"] == "10000.00"
    assert invoice_response["balance_amount"] == "10000.00"
    assert invoice_response["journal_entry_id"] is None
    
    # Post the invoice
    post_response = client.post(f"/api/v1/ar/invoices/{invoice_id}/post")
    assert post_response.status_code == 200
    
    post_data = post_response.json()
    assert post_data["journal_entry_id"] is not None
    assert post_data["invoice"]["status"] in ["sent", "partially_paid"]
    assert post_data["invoice"]["journal_entry_id"] == post_data["journal_entry_id"]
    
    # Verify journal entry was created in database
    journal_entry_id = UUID(post_data["journal_entry_id"])
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    assert je is not None
    assert je.company_id == test_company_id
    assert je.source_module == SourceModule.AR
    assert je.status == JournalStatus.POSTED
    
    # Verify journal lines
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    assert len(lines) == 2
    
    # Check that debits equal credits
    total_debit = sum(line.debit for line in lines)
    total_credit = sum(line.credit for line in lines)
    assert total_debit == total_credit
    assert total_debit == Decimal("10000.00")



