"""Accounts Payable API endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.accounting import APBill, APPayment
from app.domain.accounting.ap_service import post_bill, post_payment
from app.schemas.accounting_ap import (
    APBillCreate,
    APBillResponse,
    APPaymentCreate,
    APPaymentResponse,
    PostBillResponse,
    PostPaymentResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/bills", response_model=APBillResponse, status_code=status.HTTP_201_CREATED)
def create_bill(
    bill_data: APBillCreate,
    db: Session = Depends(get_db),
) -> APBillResponse:
    """
    Create a new AP bill.
    
    Returns the created bill with DRAFT status.
    """
    try:
        bill = APBill(
            company_id=bill_data.company_id,
            bill_number=bill_data.bill_number,
            bill_date=bill_data.bill_date,
            due_date=bill_data.due_date,
            currency=bill_data.currency,
            total_amount=bill_data.total_amount,
            balance_amount=bill_data.total_amount,  # Initially balance equals total
            contact_id=bill_data.contact_id,
        )
        db.add(bill)
        db.commit()
        db.refresh(bill)
        
        logger.info(f"Created bill {bill.id} with number {bill.bill_number}")
        return APBillResponse.model_validate(bill)
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating bill: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create bill: {str(e)}"
        )


@router.post("/bills/{bill_id}/post", response_model=PostBillResponse)
def post_bill_endpoint(
    bill_id: UUID,
    db: Session = Depends(get_db),
) -> PostBillResponse:
    """
    Post an AP bill, creating journal entry.
    
    This triggers the posting logic which:
    - Creates a journal entry with Expense (debit) and AP (credit)
    - Updates bill status to APPROVED
    - Stores journal_entry_id in the bill
    """
    try:
        # Verify bill exists
        bill = db.query(APBill).filter(APBill.id == bill_id).first()
        if not bill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bill {bill_id} not found"
            )
        
        # Post the bill using service
        journal_entry_id = post_bill(db, bill_id)
        
        # Refresh bill to get updated status and journal_entry_id
        db.refresh(bill)
        
        logger.info(f"Posted bill {bill_id} as journal entry {journal_entry_id}")
        
        return PostBillResponse(
            bill=APBillResponse.model_validate(bill),
            journal_entry_id=journal_entry_id
        )
    
    except ValueError as e:
        logger.error(f"Validation error posting bill {bill_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error posting bill {bill_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post bill: {str(e)}"
        )


@router.post("/payments", response_model=APPaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payment_data: APPaymentCreate,
    db: Session = Depends(get_db),
) -> APPaymentResponse:
    """
    Create a new AP payment.
    
    If bill_id is provided, the payment will be linked to that bill.
    """
    try:
        payment = APPayment(
            company_id=payment_data.company_id,
            payment_number=payment_data.payment_number,
            payment_date=payment_data.payment_date,
            amount=payment_data.amount,
            payment_method=payment_data.payment_method,
            contact_id=payment_data.contact_id,
            bill_id=payment_data.bill_id,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        
        logger.info(f"Created payment {payment.id} with number {payment.payment_number}")
        return APPaymentResponse.model_validate(payment)
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating payment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create payment: {str(e)}"
        )


@router.post("/payments/{payment_id}/post", response_model=PostPaymentResponse)
def post_payment_endpoint(
    payment_id: UUID,
    db: Session = Depends(get_db),
) -> PostPaymentResponse:
    """
    Post an AP payment, creating journal entry.
    
    This triggers the posting logic which:
    - Creates a journal entry with AP (debit) and Cash (credit)
    - If linked to bill, updates bill balance and status
    - Stores journal_entry_id in the payment
    """
    try:
        # Verify payment exists
        payment = db.query(APPayment).filter(APPayment.id == payment_id).first()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found"
            )
        
        # Post the payment using service
        journal_entry_id = post_payment(db, payment_id)
        
        # Refresh payment to get updated journal_entry_id
        db.refresh(payment)
        
        # Get bill info if linked
        bill_balance = None
        bill_status = None
        if payment.bill_id:
            bill = db.query(APBill).filter(APBill.id == payment.bill_id).first()
            if bill:
                bill_balance = bill.balance_amount
                bill_status = bill.status
        
        logger.info(f"Posted payment {payment_id} as journal entry {journal_entry_id}")
        
        return PostPaymentResponse(
            payment=APPaymentResponse.model_validate(payment),
            journal_entry_id=journal_entry_id,
            bill_balance=bill_balance,
            bill_status=bill_status
        )
    
    except ValueError as e:
        logger.error(f"Validation error posting payment {payment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error posting payment {payment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post payment: {str(e)}"
        )



