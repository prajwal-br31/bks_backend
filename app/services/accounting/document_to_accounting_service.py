"""Service to create AR/AP records from documents."""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentType, DocumentDestination
from app.models.accounting.ar import ARInvoice
from app.models.accounting.ap import APBill
from app.domain.accounting.enums import InvoiceStatus, BillStatus

logger = logging.getLogger(__name__)


def get_default_company_id() -> UUID:
    """
    Get a default company ID for development.
    
    TODO: Replace with actual company resolution logic.
    For now, returns a fixed UUID for testing.
    """
    # This is a placeholder - in production, this should resolve from user context
    return UUID("00000000-0000-0000-0000-000000000001")


def get_default_contact_id(vendor_name: Optional[str] = None) -> UUID:
    """
    Get a default contact ID for development.
    
    TODO: Replace with actual contact resolution logic.
    For now, returns a fixed UUID for testing.
    """
    # This is a placeholder - in production, this should resolve from vendor/customer name
    return UUID("00000000-0000-0000-0000-000000000002")


def create_ar_invoice_from_document(
    db: Session,
    document_id: int,
    company_id: Optional[UUID] = None,
    contact_id: Optional[UUID] = None,
) -> ARInvoice:
    """
    Create an AR Invoice from a classified document.
    
    Args:
        db: Database session
        document_id: ID of the document to convert
        company_id: Optional company ID (uses default if not provided)
        contact_id: Optional contact ID (uses default if not provided)
    
    Returns:
        Created ARInvoice instance
    
    Raises:
        ValueError: If document is not found, already linked, or invalid for AR
    """
    # Load document
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found")
    
    # Check if already linked
    if hasattr(document, 'ar_invoice_id') and document.ar_invoice_id:
        existing_invoice = db.query(ARInvoice).filter(
            ARInvoice.id == document.ar_invoice_id
        ).first()
        if existing_invoice:
            logger.info(f"Document {document_id} already linked to AR Invoice {existing_invoice.id}")
            return existing_invoice
    
    # Validate document type
    if document.document_type not in [DocumentType.INVOICE, DocumentType.RECEIPT]:
        raise ValueError(
            f"Document {document_id} is of type {document.document_type.value}, "
            "expected INVOICE or RECEIPT for AR Invoice creation"
        )
    
    # Check destination
    if document.destination == DocumentDestination.ACCOUNT_PAYABLE:
        logger.warning(
            f"Document {document_id} is marked as ACCOUNT_PAYABLE but creating AR Invoice. "
            "Consider using create_ap_bill_from_document instead."
        )
    
    # Resolve company_id
    if not company_id:
        company_id = get_default_company_id()
    
    # Resolve contact_id
    if not contact_id:
        contact_id = get_default_contact_id(document.vendor_name)
    
    # Extract invoice data
    invoice_number = document.invoice_number or f"DOC-{document.id}"
    invoice_date = document.invoice_date.date() if document.invoice_date else date.today()
    
    # Calculate due date
    if document.due_date:
        due_date = document.due_date.date()
    else:
        # Default to 30 days from invoice date
        from datetime import timedelta
        due_date = invoice_date + timedelta(days=30)
    
    # Extract amounts
    total_amount = Decimal(str(document.total_amount)) if document.total_amount else Decimal("0.00")
    balance_amount = total_amount  # Initially, balance equals total
    currency = document.currency or "USD"
    
    # Create AR Invoice
    ar_invoice = ARInvoice(
        id=uuid4(),
        company_id=company_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        status=InvoiceStatus.DRAFT,
        currency=currency,
        total_amount=total_amount,
        balance_amount=balance_amount,
        contact_id=contact_id,
        journal_entry_id=None,  # Not posted yet
    )
    
    db.add(ar_invoice)
    db.flush()
    
    # Link document to invoice
    document.ar_invoice_id = ar_invoice.id
    db.add(document)
    
    db.commit()
    db.refresh(ar_invoice)
    
    logger.info(
        f"Created AR Invoice {ar_invoice.id} (invoice_number={invoice_number}) "
        f"from document {document_id}"
    )
    
    return ar_invoice


def create_ap_bill_from_document(
    db: Session,
    document_id: int,
    company_id: Optional[UUID] = None,
    contact_id: Optional[UUID] = None,
) -> APBill:
    """
    Create an AP Bill from a classified document.
    
    Args:
        db: Database session
        document_id: ID of the document to convert
        company_id: Optional company ID (uses default if not provided)
        contact_id: Optional contact ID (uses default if not provided)
    
    Returns:
        Created APBill instance
    
    Raises:
        ValueError: If document is not found, already linked, or invalid for AP
    """
    # Load document
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found")
    
    # Check if already linked
    if document.ap_bill_id:
        existing_bill = db.query(APBill).filter(
            APBill.id == document.ap_bill_id
        ).first()
        if existing_bill:
            logger.info(f"Document {document_id} already linked to AP Bill {existing_bill.id}")
            return existing_bill
    
    # Validate document type
    if document.document_type not in [DocumentType.INVOICE, DocumentType.RECEIPT]:
        raise ValueError(
            f"Document {document_id} is of type {document.document_type.value}, "
            "expected INVOICE or RECEIPT for AP Bill creation"
        )
    
    # Check destination
    if document.destination == DocumentDestination.ACCOUNT_RECEIVABLE:
        logger.warning(
            f"Document {document_id} is marked as ACCOUNT_RECEIVABLE but creating AP Bill. "
            "Consider using create_ar_invoice_from_document instead."
        )
    
    # Resolve company_id
    if not company_id:
        company_id = get_default_company_id()
    
    # Resolve contact_id
    if not contact_id:
        contact_id = get_default_contact_id(document.vendor_name)
    
    # Extract bill data
    bill_number = document.invoice_number or f"DOC-{document.id}"
    bill_date = document.invoice_date.date() if document.invoice_date else date.today()
    
    # Calculate due date
    if document.due_date:
        due_date = document.due_date.date()
    else:
        # Default to 30 days from bill date
        from datetime import timedelta
        due_date = bill_date + timedelta(days=30)
    
    # Extract amounts
    total_amount = Decimal(str(document.total_amount)) if document.total_amount else Decimal("0.00")
    balance_amount = total_amount  # Initially, balance equals total
    currency = document.currency or "USD"
    
    # Create AP Bill
    ap_bill = APBill(
        id=uuid4(),
        company_id=company_id,
        bill_number=bill_number,
        bill_date=bill_date,
        due_date=due_date,
        status=BillStatus.DRAFT,
        currency=currency,
        total_amount=total_amount,
        balance_amount=balance_amount,
        contact_id=contact_id,
        journal_entry_id=None,  # Not posted yet
    )
    
    db.add(ap_bill)
    db.flush()
    
    # Link document to bill
    document.ap_bill_id = ap_bill.id
    db.add(document)
    
    db.commit()
    db.refresh(ap_bill)
    
    logger.info(
        f"Created AP Bill {ap_bill.id} (bill_number={bill_number}) "
        f"from document {document_id}"
    )
    
    return ap_bill

