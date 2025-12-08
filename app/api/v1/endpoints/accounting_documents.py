"""API endpoints for creating AR/AP records from documents."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.document import Document
from app.services.accounting.document_to_accounting_service import (
    create_ar_invoice_from_document,
    create_ap_bill_from_document,
)
from app.schemas.accounting_ar import ARInvoiceResponse
from app.schemas.accounting_ap import APBillResponse

router = APIRouter()


@router.post("/documents/{document_id}/create-ar-invoice", response_model=ARInvoiceResponse)
def create_ar_invoice_from_document_endpoint(
    document_id: int,
    db: Session = Depends(get_db),
):
    """
    Manually create an AR Invoice from a document.
    
    Args:
        document_id: ID of the document to convert
        db: Database session
    
    Returns:
        Created ARInvoice
    """
    # Verify document exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
    
    try:
        ar_invoice = create_ar_invoice_from_document(db, document_id)
        return ARInvoiceResponse(
            id=ar_invoice.id,
            company_id=ar_invoice.company_id,
            invoice_number=ar_invoice.invoice_number,
            invoice_date=ar_invoice.invoice_date,
            due_date=ar_invoice.due_date,
            status=ar_invoice.status.value,
            currency=ar_invoice.currency,
            total_amount=float(ar_invoice.total_amount),
            balance_amount=float(ar_invoice.balance_amount),
            contact_id=ar_invoice.contact_id,
            journal_entry_id=ar_invoice.journal_entry_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create AR Invoice: {str(e)}")


@router.post("/documents/{document_id}/create-ap-bill", response_model=APBillResponse)
def create_ap_bill_from_document_endpoint(
    document_id: int,
    db: Session = Depends(get_db),
):
    """
    Manually create an AP Bill from a document.
    
    Args:
        document_id: ID of the document to convert
        db: Database session
    
    Returns:
        Created APBill
    """
    # Verify document exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
    
    try:
        ap_bill = create_ap_bill_from_document(db, document_id)
        return APBillResponse(
            id=ap_bill.id,
            company_id=ap_bill.company_id,
            bill_number=ap_bill.bill_number,
            bill_date=ap_bill.bill_date,
            due_date=ap_bill.due_date,
            status=ap_bill.status,
            currency=ap_bill.currency,
            total_amount=float(ap_bill.total_amount),
            balance_amount=float(ap_bill.balance_amount),
            contact_id=ap_bill.contact_id,
            journal_entry_id=ap_bill.journal_entry_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create AP Bill: {str(e)}")

