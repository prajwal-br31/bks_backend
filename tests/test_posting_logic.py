"""Tests for AR/AP posting logic."""

import pytest
from datetime import date
from decimal import Decimal
from uuid import uuid4, UUID

from sqlalchemy.orm import Session

from app.models.accounting import (
    ChartOfAccount,
    JournalEntry,
    JournalLine,
    ARInvoice,
    ARReceipt,
    APBill,
    APPayment,
)
from app.domain.accounting.enums import (
    AccountType,
    InvoiceStatus,
    BillStatus,
    JournalStatus,
    SourceModule,
)
from app.domain.accounting.ar_service import (
    post_invoice,
    post_receipt,
)
from app.domain.accounting.ap_service import (
    post_bill,
    post_payment,
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
    
    db.commit()
    
    return {
        "revenue": revenue,
        "ar": ar_account,
        "cash": cash,
        "expense": expense,
        "ap": ap_account,
    }


def test_post_ar_invoice(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test posting an AR invoice creates journal entry and lines."""
    # Create an invoice
    invoice = ARInvoice(
        id=uuid4(),
        company_id=test_company_id,
        invoice_number="INV-001",
        invoice_date=date(2025, 1, 15),
        due_date=date(2025, 2, 15),
        status=InvoiceStatus.DRAFT,
        currency="USD",
        total_amount=Decimal("10000.00"),
        balance_amount=Decimal("10000.00"),
        contact_id=uuid4(),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    
    # Post the invoice
    journal_entry_id = post_invoice(db, invoice.id)
    
    # Verify journal entry was created
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    assert je is not None
    assert je.company_id == test_company_id
    assert je.date == invoice.invoice_date
    assert je.source_module == SourceModule.AR
    assert je.source_id == invoice.id
    assert je.status == JournalStatus.POSTED
    assert je.posted_at is not None
    
    # Verify journal lines
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    assert len(lines) == 2
    
    # Find AR line (debit)
    ar_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["ar"].id), None)
    assert ar_line is not None
    assert ar_line.debit == Decimal("10000.00")
    assert ar_line.credit == Decimal("0.00")
    
    # Find Revenue line (credit)
    revenue_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["revenue"].id), None)
    assert revenue_line is not None
    assert revenue_line.debit == Decimal("0.00")
    assert revenue_line.credit == Decimal("10000.00")
    
    # Verify invoice was updated
    db.refresh(invoice)
    assert invoice.journal_entry_id == journal_entry_id
    assert invoice.status == InvoiceStatus.SENT


def test_post_ar_receipt(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test posting an AR receipt creates journal entry and updates invoice."""
    # Create an invoice
    invoice = ARInvoice(
        id=uuid4(),
        company_id=test_company_id,
        invoice_number="INV-002",
        invoice_date=date(2025, 1, 15),
        due_date=date(2025, 2, 15),
        status=InvoiceStatus.SENT,
        currency="USD",
        total_amount=Decimal("10000.00"),
        balance_amount=Decimal("10000.00"),
        contact_id=uuid4(),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    
    # Create a receipt linked to the invoice
    receipt = ARReceipt(
        id=uuid4(),
        company_id=test_company_id,
        receipt_number="RCP-001",
        receipt_date=date(2025, 1, 20),
        amount=Decimal("6000.00"),
        payment_method="Check",
        contact_id=invoice.contact_id,
        invoice_id=invoice.id,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    
    # Post the receipt
    journal_entry_id = post_receipt(db, receipt.id)
    
    # Verify journal entry
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    assert je is not None
    assert je.source_module == SourceModule.AR
    assert je.source_id == receipt.id
    
    # Verify journal lines
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    assert len(lines) == 2
    
    # Cash line (debit)
    cash_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["cash"].id), None)
    assert cash_line is not None
    assert cash_line.debit == Decimal("6000.00")
    assert cash_line.credit == Decimal("0.00")
    
    # AR line (credit)
    ar_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["ar"].id), None)
    assert ar_line is not None
    assert ar_line.debit == Decimal("0.00")
    assert ar_line.credit == Decimal("6000.00")
    
    # Verify receipt was updated
    db.refresh(receipt)
    assert receipt.journal_entry_id == journal_entry_id
    
    # Verify invoice balance and status were updated
    db.refresh(invoice)
    assert invoice.balance_amount == Decimal("4000.00")  # 10000 - 6000
    assert invoice.status == InvoiceStatus.PARTIALLY_PAID


def test_post_ap_bill(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test posting an AP bill creates journal entry and lines."""
    # Create a bill
    bill = APBill(
        id=uuid4(),
        company_id=test_company_id,
        bill_number="BILL-001",
        bill_date=date(2025, 1, 10),
        due_date=date(2025, 2, 10),
        status=BillStatus.DRAFT,
        currency="USD",
        total_amount=Decimal("5000.00"),
        balance_amount=Decimal("5000.00"),
        contact_id=uuid4(),
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    
    # Post the bill
    journal_entry_id = post_bill(db, bill.id)
    
    # Verify journal entry
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    assert je is not None
    assert je.company_id == test_company_id
    assert je.date == bill.bill_date
    assert je.source_module == SourceModule.AP
    assert je.source_id == bill.id
    assert je.status == JournalStatus.POSTED
    
    # Verify journal lines
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    assert len(lines) == 2
    
    # Expense line (debit)
    expense_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["expense"].id), None)
    assert expense_line is not None
    assert expense_line.debit == Decimal("5000.00")
    assert expense_line.credit == Decimal("0.00")
    
    # AP line (credit)
    ap_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["ap"].id), None)
    assert ap_line is not None
    assert ap_line.debit == Decimal("0.00")
    assert ap_line.credit == Decimal("5000.00")
    
    # Verify bill was updated
    db.refresh(bill)
    assert bill.journal_entry_id == journal_entry_id
    assert bill.status == BillStatus.APPROVED


def test_post_ap_payment(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test posting an AP payment creates journal entry and updates bill."""
    # Create a bill
    bill = APBill(
        id=uuid4(),
        company_id=test_company_id,
        bill_number="BILL-002",
        bill_date=date(2025, 1, 10),
        due_date=date(2025, 2, 10),
        status=BillStatus.APPROVED,
        currency="USD",
        total_amount=Decimal("5000.00"),
        balance_amount=Decimal("5000.00"),
        contact_id=uuid4(),
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    
    # Create a payment linked to the bill
    payment = APPayment(
        id=uuid4(),
        company_id=test_company_id,
        payment_number="PAY-001",
        payment_date=date(2025, 1, 25),
        amount=Decimal("5000.00"),
        payment_method="Wire Transfer",
        contact_id=bill.contact_id,
        bill_id=bill.id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    # Post the payment
    journal_entry_id = post_payment(db, payment.id)
    
    # Verify journal entry
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    assert je is not None
    assert je.source_module == SourceModule.AP
    assert je.source_id == payment.id
    
    # Verify journal lines
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    assert len(lines) == 2
    
    # AP line (debit)
    ap_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["ap"].id), None)
    assert ap_line is not None
    assert ap_line.debit == Decimal("5000.00")
    assert ap_line.credit == Decimal("0.00")
    
    # Cash line (credit)
    cash_line = next((l for l in lines if l.account_id == sample_chart_of_accounts["cash"].id), None)
    assert cash_line is not None
    assert cash_line.debit == Decimal("0.00")
    assert cash_line.credit == Decimal("5000.00")
    
    # Verify payment was updated
    db.refresh(payment)
    assert payment.journal_entry_id == journal_entry_id
    
    # Verify bill balance and status were updated
    db.refresh(bill)
    assert bill.balance_amount == Decimal("0.00")  # 5000 - 5000
    assert bill.status == BillStatus.PAID


def test_post_invoice_balance_validation(db: Session, test_company_id: UUID, sample_chart_of_accounts):
    """Test that journal entries are balanced (debits = credits)."""
    invoice = ARInvoice(
        id=uuid4(),
        company_id=test_company_id,
        invoice_number="INV-003",
        invoice_date=date(2025, 1, 15),
        status=InvoiceStatus.DRAFT,
        currency="USD",
        total_amount=Decimal("7500.00"),
        balance_amount=Decimal("7500.00"),
        contact_id=uuid4(),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    
    journal_entry_id = post_invoice(db, invoice.id)
    
    # Verify the journal entry is balanced
    je = db.query(JournalEntry).filter(JournalEntry.id == journal_entry_id).first()
    lines = db.query(JournalLine).filter(JournalLine.journal_entry_id == je.id).all()
    
    total_debit = sum(line.debit for line in lines)
    total_credit = sum(line.credit for line in lines)
    
    assert total_debit == total_credit
    assert total_debit == Decimal("7500.00")


