"""Accounts Receivable API endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.accounting import ARInvoice, ARReceipt
from app.domain.accounting.ar_service import post_invoice, post_receipt
from app.schemas.accounting_ar import (
    ARInvoiceCreate,
    ARInvoiceResponse,
    ARReceiptCreate,
    ARReceiptResponse,
    PostInvoiceResponse,
    PostReceiptResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/invoices", response_model=ARInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_invoice(
    invoice_data: ARInvoiceCreate,
    db: Session = Depends(get_db),
) -> ARInvoiceResponse:
    """
    Create a new AR invoice.
    
    Returns the created invoice with DRAFT status.
    """
    try:
        invoice = ARInvoice(
            company_id=invoice_data.company_id,
            invoice_number=invoice_data.invoice_number,
            invoice_date=invoice_data.invoice_date,
            due_date=invoice_data.due_date,
            currency=invoice_data.currency,
            total_amount=invoice_data.total_amount,
            balance_amount=invoice_data.total_amount,  # Initially balance equals total
            contact_id=invoice_data.contact_id,
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        
        logger.info(f"Created invoice {invoice.id} with number {invoice.invoice_number}")
        return ARInvoiceResponse.model_validate(invoice)
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating invoice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create invoice: {str(e)}"
        )


@router.post("/invoices/{invoice_id}/post", response_model=PostInvoiceResponse)
def post_invoice_endpoint(
    invoice_id: UUID,
    db: Session = Depends(get_db),
) -> PostInvoiceResponse:
    """
    Post an AR invoice, creating journal entry.
    
    This triggers the posting logic which:
    - Creates a journal entry with AR (debit) and Revenue (credit)
    - Updates invoice status to SENT or PARTIALLY_PAID
    - Stores journal_entry_id in the invoice
    """
    try:
        # Verify invoice exists
        invoice = db.query(ARInvoice).filter(ARInvoice.id == invoice_id).first()
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Invoice {invoice_id} not found"
            )
        
        # Post the invoice using service
        journal_entry_id = post_invoice(db, invoice_id)
        
        # Refresh invoice to get updated status and journal_entry_id
        db.refresh(invoice)
        
        logger.info(f"Posted invoice {invoice_id} as journal entry {journal_entry_id}")
        
        return PostInvoiceResponse(
            invoice=ARInvoiceResponse.model_validate(invoice),
            journal_entry_id=journal_entry_id
        )
    
    except ValueError as e:
        logger.error(f"Validation error posting invoice {invoice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error posting invoice {invoice_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post invoice: {str(e)}"
        )


@router.post("/receipts", response_model=ARReceiptResponse, status_code=status.HTTP_201_CREATED)
def create_receipt(
    receipt_data: ARReceiptCreate,
    db: Session = Depends(get_db),
) -> ARReceiptResponse:
    """
    Create a new AR receipt.
    
    If invoice_id is provided, the receipt will be linked to that invoice.
    """
    try:
        receipt = ARReceipt(
            company_id=receipt_data.company_id,
            receipt_number=receipt_data.receipt_number,
            receipt_date=receipt_data.receipt_date,
            amount=receipt_data.amount,
            payment_method=receipt_data.payment_method,
            contact_id=receipt_data.contact_id,
            invoice_id=receipt_data.invoice_id,
        )
        db.add(receipt)
        db.commit()
        db.refresh(receipt)
        
        logger.info(f"Created receipt {receipt.id} with number {receipt.receipt_number}")
        return ARReceiptResponse.model_validate(receipt)
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating receipt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create receipt: {str(e)}"
        )


@router.post("/receipts/{receipt_id}/post", response_model=PostReceiptResponse)
def post_receipt_endpoint(
    receipt_id: UUID,
    db: Session = Depends(get_db),
) -> PostReceiptResponse:
    """
    Post an AR receipt, creating journal entry.
    
    This triggers the posting logic which:
    - Creates a journal entry with Cash (debit) and AR (credit)
    - If linked to invoice, updates invoice balance and status
    - Stores journal_entry_id in the receipt
    """
    try:
        # Verify receipt exists
        receipt = db.query(ARReceipt).filter(ARReceipt.id == receipt_id).first()
        if not receipt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Receipt {receipt_id} not found"
            )
        
        # Post the receipt using service
        journal_entry_id = post_receipt(db, receipt_id)
        
        # Refresh receipt to get updated journal_entry_id
        db.refresh(receipt)
        
        # Get invoice info if linked
        invoice_balance = None
        invoice_status = None
        if receipt.invoice_id:
            invoice = db.query(ARInvoice).filter(ARInvoice.id == receipt.invoice_id).first()
            if invoice:
                invoice_balance = invoice.balance_amount
                invoice_status = invoice.status
        
        logger.info(f"Posted receipt {receipt_id} as journal entry {journal_entry_id}")
        
        return PostReceiptResponse(
            receipt=ARReceiptResponse.model_validate(receipt),
            journal_entry_id=journal_entry_id,
            invoice_balance=invoice_balance,
            invoice_status=invoice_status
        )
    
    except ValueError as e:
        logger.error(f"Validation error posting receipt {receipt_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error posting receipt {receipt_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post receipt: {str(e)}"
        )

