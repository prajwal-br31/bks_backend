"""Tests for bank feed AI classification."""

import pytest
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.bank_feed import (
    BankFile,
    BankTransaction,
    TransactionType,
    ClassificationStatus,
    FileStatus,
)
from app.services.bank_feed.ai_classifier import (
    classify_transaction_rule_based,
    classify_transactions_batch,
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
def sample_bank_file(db: Session):
    """Create a sample bank file for testing."""
    bank_file = BankFile(
        original_filename="test_chase.csv",
        storage_path="test/path",
        file_size=1024,
        content_type="text/csv",
        status=FileStatus.COMPLETED,
        total_rows=5,
        parsed_rows=5,
        bank_name="Chase",
    )
    db.add(bank_file)
    db.commit()
    db.refresh(bank_file)
    return bank_file


def test_classify_bank_fee_transaction(db: Session, sample_bank_file):
    """Test classification of bank fee transaction."""
    txn = BankTransaction(
        bank_file_id=sample_bank_file.id,
        date=datetime(2025, 1, 15),
        description="MONTHLY SERVICE FEE",
        amount=-12.00,
        type=TransactionType.DEBIT,
        status=TransactionStatus.PENDING,
        raw_data={
            "Details": "DEBIT",
            "Type": "FEE_TRANSACTION",
            "Description": "MONTHLY SERVICE FEE",
        },
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    
    result = classify_transaction_rule_based(txn)
    
    assert result["ai_category"] == "BANK_FEE"
    assert result["ai_subcategory"] == "Service Fee"
    assert result["ai_confidence"] == 0.85
    assert result["ai_ledger_hint"] == "OPERATING_EXPENSE"


def test_classify_credit_card_payment(db: Session, sample_bank_file):
    """Test classification of credit card payment."""
    txn = BankTransaction(
        bank_file_id=sample_bank_file.id,
        date=datetime(2025, 1, 15),
        description="CAPITAL ONE PAYMENT",
        amount=-500.00,
        type=TransactionType.DEBIT,
        status=TransactionStatus.PENDING,
        raw_data={
            "Details": "DEBIT",
            "Type": "ACH_DEBIT",
            "Description": "CAPITAL ONE PAYMENT",
        },
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    
    result = classify_transaction_rule_based(txn)
    
    assert result["ai_category"] == "CREDIT_CARD_PAYMENT"
    assert result["ai_subcategory"] == "Credit Card Payment"
    assert result["ai_confidence"] == 0.80


def test_classify_vendor_payment(db: Session, sample_bank_file):
    """Test classification of vendor payment (BacklotCars)."""
    txn = BankTransaction(
        bank_file_id=sample_bank_file.id,
        date=datetime(2025, 1, 15),
        description="BacklotCars Auto Purchase",
        amount=-15000.00,
        type=TransactionType.DEBIT,
        status=TransactionStatus.PENDING,
        raw_data={
            "Details": "DEBIT",
            "Type": "MISC_DEBIT",
            "Description": "BacklotCars Auto Purchase",
        },
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    
    result = classify_transaction_rule_based(txn)
    
    assert result["ai_category"] == "VENDOR_PAYMENT"
    assert result["ai_subcategory"] == "BacklotCars - Auto Purchase"
    assert result["ai_confidence"] == 0.75


def test_classify_transfer_in(db: Session, sample_bank_file):
    """Test classification of transfer in."""
    txn = BankTransaction(
        bank_file_id=sample_bank_file.id,
        date=datetime(2025, 1, 15),
        description="ACCT_XFER",
        amount=1000.00,
        type=TransactionType.CREDIT,
        status=TransactionStatus.PENDING,
        raw_data={
            "Details": "CREDIT",
            "Type": "ACCT_XFER",
            "Description": "ACCT_XFER",
        },
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    
    result = classify_transaction_rule_based(txn)
    
    assert result["ai_category"] == "TRANSFER_IN"
    assert result["ai_ledger_hint"] == "INTERCOMPANY"


def test_classify_transactions_batch(db: Session, sample_bank_file):
    """Test batch classification of transactions."""
    # Create multiple transactions
    transactions = [
        BankTransaction(
            bank_file_id=sample_bank_file.id,
            date=datetime(2025, 1, 15),
            description="MONTHLY SERVICE FEE",
            amount=-12.00,
            type=TransactionType.DEBIT,
            status=TransactionStatus.PENDING,
            raw_data={"Type": "FEE_TRANSACTION"},
        ),
        BankTransaction(
            bank_file_id=sample_bank_file.id,
            date=datetime(2025, 1, 16),
            description="BacklotCars",
            amount=-15000.00,
            type=TransactionType.DEBIT,
            status=TransactionStatus.PENDING,
            raw_data={"Type": "MISC_DEBIT"},
        ),
        BankTransaction(
            bank_file_id=sample_bank_file.id,
            date=datetime(2025, 1, 17),
            description="ACCT_XFER",
            amount=1000.00,
            type=TransactionType.CREDIT,
            status=TransactionStatus.PENDING,
            raw_data={"Details": "CREDIT", "Type": "ACCT_XFER"},
        ),
    ]
    
    for txn in transactions:
        db.add(txn)
    db.commit()
    
    transaction_ids = [txn.id for txn in transactions]
    
    # Classify batch
    classify_transactions_batch(
        db=db,
        transaction_ids=transaction_ids,
        use_ai=False,
        chunk_size=100,
    )
    
    # Verify classifications
    for txn_id in transaction_ids:
        txn = db.query(BankTransaction).filter(BankTransaction.id == txn_id).first()
        assert txn is not None
        assert txn.classification_status == ClassificationStatus.DONE
        assert txn.ai_category is not None
        assert txn.ai_confidence is not None
    
    # Verify specific classifications
    fee_txn = db.query(BankTransaction).filter(
        BankTransaction.description == "MONTHLY SERVICE FEE"
    ).first()
    assert fee_txn.ai_category == "BANK_FEE"
    
    vendor_txn = db.query(BankTransaction).filter(
        BankTransaction.description == "BacklotCars"
    ).first()
    assert vendor_txn.ai_category == "VENDOR_PAYMENT"
    
    transfer_txn = db.query(BankTransaction).filter(
        BankTransaction.description == "ACCT_XFER"
    ).first()
    assert transfer_txn.ai_category == "TRANSFER_IN"



