"""Bank Feed API endpoints."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.bank_feed import (
    BankFile,
    BankTransaction,
    TransactionStatus,
    TransactionType,
    FileStatus,
)
from app.services.bank_feed import BankFeedService
from app.services.notifications import NotificationService

router = APIRouter()


# Pydantic models
class TransactionResponse(BaseModel):
    id: int
    date: str
    description: str
    amount: float
    type: str
    balance: Optional[float]
    status: str
    category: Optional[str]
    check_number: Optional[str]
    bank_file_id: int
    matched_entity: Optional[dict]

    class Config:
        from_attributes = True


class TransactionListResponse(BaseModel):
    items: List[TransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class UploadResponse(BaseModel):
    file_id: int
    filename: str
    status: str
    total_rows: int
    parsed_rows: int
    skipped_rows: int
    transaction_ids: List[int]
    bank_name: Optional[str]
    statement_start: Optional[str]
    statement_end: Optional[str]
    errors: List[str]
    warnings: List[str]


class MatchRequest(BaseModel):
    bank_transaction_id: int
    matched_type: str  # "ar", "ap", "expense"
    matched_id: int
    matched_by: Optional[str] = None
    matched_name: Optional[str] = None
    matched_reference: Optional[str] = None
    notes: Optional[str] = None


class MatchResponse(BaseModel):
    match_id: int
    bank_transaction_id: int
    matched_type: str
    matched_id: int
    matched_name: Optional[str]
    status: str


class SummaryResponse(BaseModel):
    imported_this_period: int
    unmatched_count: int
    matched_count: int
    reviewed_count: int
    cleared_count: int
    last_import: Optional[str]
    last_import_filename: Optional[str]


class ReprocessResponse(BaseModel):
    file_id: int
    status: str
    total_rows: int
    parsed_rows: int
    transaction_ids: List[int]


class BulkActionRequest(BaseModel):
    action: str  # "reviewed", "cleared", "excluded"
    transaction_ids: List[int]


# Endpoints

@router.post("/upload", response_model=UploadResponse)
async def upload_bank_file(
    file: UploadFile = File(...),
    uploaded_by: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload a bank statement file (CSV, XLSX, or ZIP).
    
    - Validates file type and size
    - Parses using appropriate parser
    - Stores original file in S3
    - Creates BankFile and BankTransaction records
    """
    # Validate file type
    allowed_types = [
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    ]
    
    # Also check by extension
    filename = file.filename or "upload.csv"
    ext = filename.lower().split(".")[-1]
    allowed_extensions = ["csv", "xlsx", "xls", "zip"]
    
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed_types and ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: CSV, XLSX, ZIP. Got: {content_type}"
        )
    
    # Read content
    content = await file.read()
    
    # Validate size (max 50MB)
    max_size = 50 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: 50MB. Got: {len(content)} bytes"
        )
    
    # Process
    service = BankFeedService(db)
    
    try:
        result = await service.process_upload(
            content=content,
            filename=filename,
            content_type=content_type,
            uploaded_by=uploaded_by,
        )
        
        # Send notification
        notification_service = NotificationService(db)
        await notification_service.create(
            title="Bank statement uploaded",
            message=f"File '{filename}' processed: {result['parsed_rows']} transactions imported",
            notification_type="excel",
            severity="success" if not result["errors"] else "warning",
            reference_type="bank_file",
            reference_id=result["file_id"],
            source="Bank Feed Upload",
            push_realtime=True,
        )
        
        return UploadResponse(**result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transactions", response_model=TransactionListResponse)
def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    search: Optional[str] = None,
    file_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Get paginated list of bank transactions with filters.
    """
    service = BankFeedService(db)
    
    # Parse filters
    status_enum = TransactionStatus(status) if status else None
    type_enum = TransactionType(type) if type else None
    
    date_from_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
        except ValueError:
            pass
    
    date_to_dt = None
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        except ValueError:
            pass
    
    result = service.get_transactions(
        page=page,
        page_size=page_size,
        status=status_enum,
        transaction_type=type_enum,
        date_from=date_from_dt,
        date_to=date_to_dt,
        amount_min=amount_min,
        amount_max=amount_max,
        search=search,
        file_id=file_id,
    )
    
    return TransactionListResponse(**result)


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Get a single transaction by ID."""
    txn = db.query(BankTransaction).filter(BankTransaction.id == transaction_id).first()
    
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    result = {
        "id": txn.id,
        "date": txn.date.isoformat() if txn.date else None,
        "description": txn.description,
        "amount": txn.amount,
        "type": txn.type.value,
        "balance": txn.balance,
        "status": txn.status.value,
        "category": txn.category,
        "check_number": txn.check_number,
        "memo": txn.memo,
        "bank_file_id": txn.bank_file_id,
        "raw_data": txn.raw_data,
        "matched_entity": None,
    }
    
    if txn.match:
        result["matched_entity"] = {
            "type": txn.match.matched_type.value,
            "id": txn.match.matched_id,
            "name": txn.match.matched_name,
            "reference": txn.match.matched_reference,
            "matched_at": txn.match.matched_at.isoformat() if txn.match.matched_at else None,
            "matched_by": txn.match.matched_by,
        }
    
    return result


@router.post("/match", response_model=MatchResponse)
def create_match(request: MatchRequest, db: Session = Depends(get_db)):
    """
    Match a bank transaction to an AP/AR/Expense entity.
    
    Creates a BankMatch record and updates transaction status to MATCHED.
    """
    service = BankFeedService(db)
    
    try:
        result = service.create_match(
            bank_transaction_id=request.bank_transaction_id,
            matched_type=request.matched_type,
            matched_id=request.matched_id,
            matched_by=request.matched_by,
            matched_name=request.matched_name,
            matched_reference=request.matched_reference,
            notes=request.notes,
        )
        return MatchResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reprocess/{file_id}", response_model=ReprocessResponse)
async def reprocess_file(file_id: int, db: Session = Depends(get_db)):
    """
    Re-parse a previously uploaded file.
    
    - Downloads from S3
    - Re-parses with current parser
    - Re-runs matching suggestions
    """
    service = BankFeedService(db)
    
    try:
        result = await service.reprocess_file(file_id)
        return ReprocessResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(get_db)):
    """Get summary statistics for the bank feed dashboard."""
    service = BankFeedService(db)
    return SummaryResponse(**service.get_summary())


@router.post("/bulk-action")
def bulk_action(request: BulkActionRequest, db: Session = Depends(get_db)):
    """
    Perform bulk action on multiple transactions.
    
    Supported actions: reviewed, cleared, excluded
    """
    valid_actions = ["reviewed", "cleared", "excluded"]
    
    if request.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Allowed: {valid_actions}"
        )
    
    # Map action to status
    status_map = {
        "reviewed": TransactionStatus.REVIEWED,
        "cleared": TransactionStatus.CLEARED,
        "excluded": TransactionStatus.EXCLUDED,
    }
    
    new_status = status_map[request.action]
    
    # Update transactions
    updated = db.query(BankTransaction).filter(
        BankTransaction.id.in_(request.transaction_ids)
    ).update({"status": new_status}, synchronize_session=False)
    
    db.commit()
    
    return {
        "action": request.action,
        "updated_count": updated,
        "transaction_ids": request.transaction_ids,
    }


@router.get("/files")
def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List uploaded bank files."""
    query = db.query(BankFile)
    
    if status:
        query = query.filter(BankFile.status == FileStatus(status))
    
    total = query.count()
    files = (
        query
        .order_by(BankFile.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    items = []
    for f in files:
        items.append({
            "id": f.id,
            "filename": f.original_filename,
            "status": f.status.value,
            "total_rows": f.total_rows,
            "parsed_rows": f.parsed_rows,
            "bank_name": f.bank_name,
            "statement_start": f.statement_start_date.isoformat() if f.statement_start_date else None,
            "statement_end": f.statement_end_date.isoformat() if f.statement_end_date else None,
            "uploaded_by": f.uploaded_by,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "error_message": f.error_message,
        })
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.delete("/files/{file_id}")
def delete_file(file_id: int, db: Session = Depends(get_db)):
    """Delete a bank file and its transactions."""
    bank_file = db.query(BankFile).filter(BankFile.id == file_id).first()
    
    if not bank_file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Check if any transactions are matched
    matched_count = db.query(BankTransaction).filter(
        BankTransaction.bank_file_id == file_id,
        BankTransaction.status == TransactionStatus.MATCHED,
    ).count()
    
    if matched_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: {matched_count} transactions are matched"
        )
    
    # Delete (cascade will remove transactions)
    db.delete(bank_file)
    db.commit()
    
    return {"status": "deleted", "file_id": file_id}
