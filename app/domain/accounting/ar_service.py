"""Accounts Receivable service for invoice and receipt posting."""

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.accounting import (
    ARInvoice,
    ARReceipt,
    ChartOfAccount,
)
from app.domain.accounting.enums import (
    SourceModule,
    InvoiceStatus,
    AccountType,
)
from app.domain.accounting.gl_service import (
    create_journal_entry,
    find_account_by_type_and_name,
)

logger = logging.getLogger(__name__)


def post_invoice(db: Session, invoice_id: UUID) -> UUID:
    """
    Post an AR invoice, creating journal entry.
    
    Posting rules:
    - Debit Accounts Receivable
    - Credit Revenue
    
    Args:
        db: Database session
        invoice_id: ARInvoice UUID
    
    Returns:
        Created journal_entry_id
    
    Raises:
        ValueError: If invoice not found, already posted, or accounts not found
    """
    # Fetch invoice
    invoice = db.query(ARInvoice).filter(ARInvoice.id == invoice_id).first()
    if not invoice:
        raise ValueError(f"Invoice {invoice_id} not found")
    
    # Check if already posted
    if invoice.journal_entry_id:
        logger.warning(f"Invoice {invoice_id} already has journal_entry_id={invoice.journal_entry_id}")
        return invoice.journal_entry_id
    
    # Find AR account (Asset account with AR/Receivable in code or name)
    ar_account = find_account_by_type_and_name(
        db=db,
        company_id=invoice.company_id,
        account_type=AccountType.ASSET.value,
        code_pattern="AR",
        name_pattern="Receivable"
    )
    
    if not ar_account:
        # Try without patterns
        ar_account = find_account_by_type_and_name(
            db=db,
            company_id=invoice.company_id,
            account_type=AccountType.ASSET.value,
        )
    
    if not ar_account:
        raise ValueError(
            f"Could not find Accounts Receivable account for company {invoice.company_id}"
        )
    
    # Find revenue account
    revenue_account = find_account_by_type_and_name(
        db=db,
        company_id=invoice.company_id,
        account_type=AccountType.REVENUE.value,
    )
    
    if not revenue_account:
        raise ValueError(
            f"Could not find Revenue account for company {invoice.company_id}"
        )
    
    # Create journal entry
    description = f"Invoice {invoice.invoice_number} - {invoice.total_amount} {invoice.currency}"
    
    lines_list = [
        {
            "account_id": ar_account.id,
            "debit": float(invoice.total_amount),
            "credit": 0.0,
            "description": f"AR Invoice {invoice.invoice_number}",
        },
        {
            "account_id": revenue_account.id,
            "debit": 0.0,
            "credit": float(invoice.total_amount),
            "description": f"Revenue from Invoice {invoice.invoice_number}",
        },
    ]
    
    journal_entry = create_journal_entry(
        db=db,
        company_id=invoice.company_id,
        entry_date=invoice.invoice_date,
        description=description,
        source_module=SourceModule.AR,
        source_id=invoice.id,
        lines_list=lines_list,
    )
    
    # Update invoice
    invoice.journal_entry_id = journal_entry.id
    
    # Update status: if receipts exist and balance < total, set to PARTIALLY_PAID
    # Otherwise set to SENT
    if invoice.balance_amount < invoice.total_amount and invoice.balance_amount > 0:
        invoice.status = InvoiceStatus.PARTIALLY_PAID
    else:
        invoice.status = InvoiceStatus.SENT
    
    db.commit()
    db.refresh(invoice)
    
    logger.info(f"Posted invoice {invoice_id} as journal entry {journal_entry.id}")
    
    return journal_entry.id


def post_receipt(db: Session, receipt_id: UUID) -> UUID:
    """
    Post an AR receipt, creating journal entry.
    
    Posting rules:
    - Debit Cash
    - Credit Accounts Receivable
    
    If linked to invoice, updates invoice balance and status.
    
    Args:
        db: Database session
        receipt_id: ARReceipt UUID
    
    Returns:
        Created journal_entry_id
    
    Raises:
        ValueError: If receipt not found, already posted, or accounts not found
    """
    # Fetch receipt
    receipt = db.query(ARReceipt).filter(ARReceipt.id == receipt_id).first()
    if not receipt:
        raise ValueError(f"Receipt {receipt_id} not found")
    
    # Check if already posted
    if receipt.journal_entry_id:
        logger.warning(f"Receipt {receipt_id} already has journal_entry_id={receipt.journal_entry_id}")
        return receipt.journal_entry_id
    
    # Find cash account
    cash_account = db.query(ChartOfAccount).filter(
        ChartOfAccount.company_id == receipt.company_id,
        ChartOfAccount.is_cash == True,
        ChartOfAccount.is_active == True
    ).first()
    
    if not cash_account:
        raise ValueError(
            f"Could not find Cash account for company {receipt.company_id}"
        )
    
    # Find AR account
    ar_account = find_account_by_type_and_name(
        db=db,
        company_id=receipt.company_id,
        account_type=AccountType.ASSET.value,
        code_pattern="AR",
        name_pattern="Receivable"
    )
    
    if not ar_account:
        # Try without patterns
        ar_account = find_account_by_type_and_name(
            db=db,
            company_id=receipt.company_id,
            account_type=AccountType.ASSET.value,
        )
    
    if not ar_account:
        raise ValueError(
            f"Could not find Accounts Receivable account for company {receipt.company_id}"
        )
    
    # Create journal entry
    description = f"Receipt {receipt.receipt_number} - {receipt.amount} {receipt.payment_method or ''}"
    
    lines_list = [
        {
            "account_id": cash_account.id,
            "debit": float(receipt.amount),
            "credit": 0.0,
            "description": f"Cash received - Receipt {receipt.receipt_number}",
        },
        {
            "account_id": ar_account.id,
            "debit": 0.0,
            "credit": float(receipt.amount),
            "description": f"AR Receipt {receipt.receipt_number}",
        },
    ]
    
    journal_entry = create_journal_entry(
        db=db,
        company_id=receipt.company_id,
        entry_date=receipt.receipt_date,
        description=description,
        source_module=SourceModule.AR,
        source_id=receipt.id,
        lines_list=lines_list,
    )
    
    # Update receipt
    receipt.journal_entry_id = journal_entry.id
    
    # If linked to invoice, update invoice balance and status
    if receipt.invoice_id:
        invoice = db.query(ARInvoice).filter(ARInvoice.id == receipt.invoice_id).first()
        if invoice:
            invoice.balance_amount -= receipt.amount
            
            if invoice.balance_amount <= 0:
                invoice.status = InvoiceStatus.PAID
            elif invoice.balance_amount < invoice.total_amount:
                invoice.status = InvoiceStatus.PARTIALLY_PAID
            
            db.commit()
            db.refresh(invoice)
            logger.info(
                f"Updated invoice {receipt.invoice_id} balance to {invoice.balance_amount}, "
                f"status={invoice.status.value}"
            )
    
    db.commit()
    db.refresh(receipt)
    
    logger.info(f"Posted receipt {receipt_id} as journal entry {journal_entry.id}")
    
    return journal_entry.id
