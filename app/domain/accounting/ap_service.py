"""Accounts Payable service for bill and payment posting."""

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.accounting import (
    APBill,
    APPayment,
    ChartOfAccount,
)
from app.domain.accounting.enums import (
    SourceModule,
    BillStatus,
    AccountType,
)
from app.domain.accounting.gl_service import (
    create_journal_entry,
    find_account_by_type_and_name,
)

logger = logging.getLogger(__name__)


def post_bill(db: Session, bill_id: UUID) -> UUID:
    """
    Post an AP bill, creating journal entry.
    
    Posting rules:
    - Debit Expense
    - Credit Accounts Payable
    
    Args:
        db: Database session
        bill_id: APBill UUID
    
    Returns:
        Created journal_entry_id
    
    Raises:
        ValueError: If bill not found, already posted, or accounts not found
    """
    # Fetch bill
    bill = db.query(APBill).filter(APBill.id == bill_id).first()
    if not bill:
        raise ValueError(f"Bill {bill_id} not found")
    
    # Check if already posted
    if bill.journal_entry_id:
        logger.warning(f"Bill {bill_id} already has journal_entry_id={bill.journal_entry_id}")
        return bill.journal_entry_id
    
    # Find expense account
    expense_account = find_account_by_type_and_name(
        db=db,
        company_id=bill.company_id,
        account_type=AccountType.EXPENSE.value,
    )
    
    if not expense_account:
        raise ValueError(
            f"Could not find Expense account for company {bill.company_id}"
        )
    
    # Find AP account (Liability account with AP/Payable in code or name)
    ap_account = find_account_by_type_and_name(
        db=db,
        company_id=bill.company_id,
        account_type=AccountType.LIABILITY.value,
        code_pattern="AP",
        name_pattern="Payable"
    )
    
    if not ap_account:
        # Try without patterns
        ap_account = find_account_by_type_and_name(
            db=db,
            company_id=bill.company_id,
            account_type=AccountType.LIABILITY.value,
        )
    
    if not ap_account:
        raise ValueError(
            f"Could not find Accounts Payable account for company {bill.company_id}"
        )
    
    # Create journal entry
    description = f"Bill {bill.bill_number} - {bill.total_amount} {bill.currency}"
    
    lines_list = [
        {
            "account_id": expense_account.id,
            "debit": float(bill.total_amount),
            "credit": 0.0,
            "description": f"Expense from Bill {bill.bill_number}",
        },
        {
            "account_id": ap_account.id,
            "debit": 0.0,
            "credit": float(bill.total_amount),
            "description": f"AP Bill {bill.bill_number}",
        },
    ]
    
    journal_entry = create_journal_entry(
        db=db,
        company_id=bill.company_id,
        entry_date=bill.bill_date,
        description=description,
        source_module=SourceModule.AP,
        source_id=bill.id,
        lines_list=lines_list,
    )
    
    # Update bill
    bill.journal_entry_id = journal_entry.id
    bill.status = BillStatus.APPROVED
    
    db.commit()
    db.refresh(bill)
    
    logger.info(f"Posted bill {bill_id} as journal entry {journal_entry.id}")
    
    return journal_entry.id


def post_payment(db: Session, payment_id: UUID) -> UUID:
    """
    Post an AP payment, creating journal entry.
    
    Posting rules:
    - Debit Accounts Payable
    - Credit Cash
    
    If linked to bill, updates bill balance and status.
    
    Args:
        db: Database session
        payment_id: APPayment UUID
    
    Returns:
        Created journal_entry_id
    
    Raises:
        ValueError: If payment not found, already posted, or accounts not found
    """
    # Fetch payment
    payment = db.query(APPayment).filter(APPayment.id == payment_id).first()
    if not payment:
        raise ValueError(f"Payment {payment_id} not found")
    
    # Check if already posted
    if payment.journal_entry_id:
        logger.warning(f"Payment {payment_id} already has journal_entry_id={payment.journal_entry_id}")
        return payment.journal_entry_id
    
    # Find AP account
    ap_account = find_account_by_type_and_name(
        db=db,
        company_id=payment.company_id,
        account_type=AccountType.LIABILITY.value,
        code_pattern="AP",
        name_pattern="Payable"
    )
    
    if not ap_account:
        # Try without patterns
        ap_account = find_account_by_type_and_name(
            db=db,
            company_id=payment.company_id,
            account_type=AccountType.LIABILITY.value,
        )
    
    if not ap_account:
        raise ValueError(
            f"Could not find Accounts Payable account for company {payment.company_id}"
        )
    
    # Find cash account
    cash_account = db.query(ChartOfAccount).filter(
        ChartOfAccount.company_id == payment.company_id,
        ChartOfAccount.is_cash == True,
        ChartOfAccount.is_active == True
    ).first()
    
    if not cash_account:
        raise ValueError(
            f"Could not find Cash account for company {payment.company_id}"
        )
    
    # Create journal entry
    description = f"Payment {payment.payment_number} - {payment.amount} {payment.payment_method or ''}"
    
    lines_list = [
        {
            "account_id": ap_account.id,
            "debit": float(payment.amount),
            "credit": 0.0,
            "description": f"AP Payment {payment.payment_number}",
        },
        {
            "account_id": cash_account.id,
            "debit": 0.0,
            "credit": float(payment.amount),
            "description": f"Cash paid - Payment {payment.payment_number}",
        },
    ]
    
    journal_entry = create_journal_entry(
        db=db,
        company_id=payment.company_id,
        entry_date=payment.payment_date,
        description=description,
        source_module=SourceModule.AP,
        source_id=payment.id,
        lines_list=lines_list,
    )
    
    # Update payment
    payment.journal_entry_id = journal_entry.id
    
    # If linked to bill, update bill balance and status
    if payment.bill_id:
        bill = db.query(APBill).filter(APBill.id == payment.bill_id).first()
        if bill:
            bill.balance_amount -= payment.amount
            
            if bill.balance_amount <= 0:
                bill.status = BillStatus.PAID
            elif bill.balance_amount < bill.total_amount:
                bill.status = BillStatus.PARTIALLY_PAID
            
            db.commit()
            db.refresh(bill)
            logger.info(
                f"Updated bill {payment.bill_id} balance to {bill.balance_amount}, "
                f"status={bill.status.value}"
            )
    
    db.commit()
    db.refresh(payment)
    
    logger.info(f"Posted payment {payment_id} as journal entry {journal_entry.id}")
    
    return journal_entry.id
