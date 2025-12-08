from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.document import (
    Document,
    DocumentType,
    DocumentStatus,
    DocumentDestination,
    Tag,
    AuditLog,
    ProcessingStatus,
)
from app.tasks.email_tasks import reprocess_document
from app.services.storage import get_storage_service
from app.services.extraction import AttachmentExtractor, ContentExtractor
from app.services.ocr import get_ocr_provider
from app.services.classification import DocumentClassifier
from app.services.security import VirusScanner, FileValidator
from app.core.config import get_settings
from app.services.accounting.document_to_accounting_service import (
    create_ar_invoice_from_document,
    create_ap_bill_from_document,
)

router = APIRouter()


# Pydantic models for API
class TagResponse(BaseModel):
    id: int
    name: str
    color: str

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: int
    original_filename: str
    source_email: Optional[str]
    source_email_subject: Optional[str]
    document_type: DocumentType
    destination: DocumentDestination
    status: DocumentStatus
    confidence_score: float
    vendor_name: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[datetime]
    due_date: Optional[datetime]
    total_amount: Optional[float]
    tax_amount: Optional[float]
    currency: str
    file_size: Optional[int]
    content_type: Optional[str]
    requires_review: bool
    is_draft: bool
    tags: List[TagResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    items: List[DocumentResponse]
    total: int
    page: int
    page_size: int


class DocumentUpdateRequest(BaseModel):
    document_type: Optional[DocumentType] = None
    destination: Optional[DocumentDestination] = None
    status: Optional[DocumentStatus] = None
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    total_amount: Optional[float] = None
    is_draft: Optional[bool] = None


class TagAssignRequest(BaseModel):
    tag_names: List[str]


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    ar_invoice_id: Optional[str] = None
    ap_bill_id: Optional[str] = None
    message: str


@router.get("", response_model=DocumentListResponse)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[DocumentStatus] = None,
    document_type: Optional[DocumentType] = None,
    destination: Optional[DocumentDestination] = None,
    requires_review: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List documents with filters and pagination."""
    query = db.query(Document)

    if status:
        query = query.filter(Document.status == status)
    if document_type:
        query = query.filter(Document.document_type == document_type)
    if destination:
        query = query.filter(Document.destination == destination)
    if requires_review is not None:
        query = query.filter(Document.requires_review == requires_review)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Document.original_filename.ilike(search_term))
            | (Document.vendor_name.ilike(search_term))
            | (Document.invoice_number.ilike(search_term))
        )

    total = query.count()
    items = query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(doc) for doc in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Get a single document by ID."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(document)


@router.post("/upload-invoice", response_model=DocumentUploadResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    auto_create_ar: bool = Form(False),
    db: Session = Depends(get_db),
):
    """
    Upload an invoice document.
    
    Args:
        file: The invoice file (PDF, image, etc.)
        auto_create_ar: If True, automatically create AR Invoice after classification
        db: Database session
    
    Returns:
        Created document and optionally AR Invoice
    """
    return await _upload_document(
        file=file,
        document_type=DocumentType.INVOICE,
        destination=DocumentDestination.ACCOUNT_RECEIVABLE,
        auto_create_ar=auto_create_ar,
        auto_create_ap=False,
        db=db,
    )


@router.post("/upload-receipt", response_model=DocumentUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    auto_create_ar: bool = Form(False),
    db: Session = Depends(get_db),
):
    """
    Upload a receipt document.
    
    Args:
        file: The receipt file (PDF, image, etc.)
        auto_create_ar: If True, automatically create AR Receipt after classification
        db: Database session
    
    Returns:
        Created document
    """
    return await _upload_document(
        file=file,
        document_type=DocumentType.RECEIPT,
        destination=DocumentDestination.ACCOUNT_RECEIVABLE,
        auto_create_ar=auto_create_ar,
        auto_create_ap=False,
        db=db,
    )


@router.post("/upload-bill", response_model=DocumentUploadResponse)
async def upload_bill(
    file: UploadFile = File(...),
    auto_create_ap: bool = Form(False),
    db: Session = Depends(get_db),
):
    """
    Upload a bill/vendor invoice document.
    
    Args:
        file: The bill file (PDF, image, etc.)
        auto_create_ap: If True, automatically create AP Bill after classification
        db: Database session
    
    Returns:
        Created document and optionally AP Bill
    """
    return await _upload_document(
        file=file,
        document_type=DocumentType.INVOICE,
        destination=DocumentDestination.ACCOUNT_PAYABLE,
        auto_create_ar=False,
        auto_create_ap=auto_create_ap,
        db=db,
    )


async def _upload_document(
    file: UploadFile,
    document_type: DocumentType,
    destination: DocumentDestination,
    auto_create_ar: bool,
    auto_create_ap: bool,
    db: Session,
) -> DocumentUploadResponse:
    """Internal helper to upload and process a document."""
    import logging
    import hashlib
    from datetime import datetime
    
    logger = logging.getLogger(__name__)
    settings = get_settings()
    
    # Read file content
    content = await file.read()
    filename = file.filename or "upload.pdf"
    content_type = file.content_type or "application/pdf"
    
    # Validate file
    file_validator = FileValidator()
    if not file_validator.is_allowed_file(filename, content_type):
        raise HTTPException(status_code=400, detail=f"File type not allowed: {content_type}")
    
    # Virus scan
    virus_scanner = VirusScanner()
    is_clean = await virus_scanner.scan_file(content, filename)
    if not is_clean:
        raise HTTPException(status_code=400, detail="File failed virus scan")
    
    # Extract content
    content_extractor = ContentExtractor()
    extracted_content = content_extractor.extract(content, content_type, filename)
    
    # OCR if needed
    ocr_provider = get_ocr_provider()
    if extracted_content.metadata.get("needs_ocr"):
        if content_type.startswith("image/"):
            ocr_result = await ocr_provider.extract_text(content, content_type)
        elif content_type == "application/pdf":
            ocr_result = await ocr_provider.extract_text_from_pdf(content)
        else:
            ocr_result = None
        
        if ocr_result and ocr_result.text:
            extracted_content.text = ocr_result.text
            extracted_content.confidence = ocr_result.confidence
    
    # Classify
    classifier = DocumentClassifier(settings.classification_confidence_threshold)
    classification = classifier.classify(
        extracted_content.text or "",
        source_email=None,
    )
    
    # Override with provided type/destination if classification is uncertain
    if classification.confidence < 0.7:
        classification.document_type = document_type
        classification.destination = destination
    
    # Upload to storage
    storage = None
    try:
        storage = get_storage_service()
    except Exception as e:
        logger.warning(f"Storage service not available: {e}")
    
    if storage:
        try:
            await storage.ensure_bucket_exists()
            stored_file = await storage.upload_file(
                content,
                filename,
                content_type,
                folder="documents",
                metadata={
                    "upload_type": "manual",
                    "document_type": classification.document_type.value,
                },
            )
            stored_file_key = stored_file.key
            stored_file_hash = stored_file.content_hash
        except Exception as e:
            logger.warning(f"Storage upload failed, using local path: {e}")
            content_hash = hashlib.sha256(content).hexdigest()
            stored_file_key = f"local://documents/{content_hash[:16]}_{filename}"
            stored_file_hash = content_hash
    else:
        content_hash = hashlib.sha256(content).hexdigest()
        stored_file_key = f"local://documents/{content_hash[:16]}_{filename}"
        stored_file_hash = content_hash
    
    # Create document record
    document = Document(
        source_email=None,
        source_email_subject=None,
        source_email_date=None,
        email_message_id=None,
        original_filename=filename,
        storage_path=stored_file_key,
        storage_hash=stored_file_hash,
        content_type=content_type,
        file_size=len(content),
        document_type=classification.document_type,
        destination=classification.destination,
        confidence_score=classification.confidence,
        vendor_name=classification.parsed_fields.vendor_name,
        invoice_number=classification.parsed_fields.invoice_number,
        invoice_date=classification.parsed_fields.invoice_date,
        due_date=classification.parsed_fields.due_date,
        total_amount=classification.parsed_fields.total_amount,
        tax_amount=classification.parsed_fields.tax_amount,
        currency=classification.parsed_fields.currency,
        parsed_fields=classification.parsed_fields.confidence_scores,
        ocr_text=extracted_content.text[:10000] if extracted_content.text else None,
        status=DocumentStatus.NEEDS_REVIEW if classification.needs_review else DocumentStatus.PROCESSED,
        processing_status=ProcessingStatus.COMPLETED,
        is_draft=not settings.auto_post_mode,
        is_auto_posted=settings.auto_post_mode,
        requires_review=classification.needs_review,
        virus_scanned=True,
        virus_clean=True,
    )
    
    # Add tags
    for tag_name in classification.tags:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name, is_system=True)
            db.add(tag)
            db.flush()
        document.tags.append(tag)
    
    db.add(document)
    db.commit()
    db.refresh(document)
    
    # Create audit log
    audit = AuditLog(
        action="document_uploaded",
        details={
            "filename": filename,
            "type": classification.document_type.value,
            "destination": classification.destination.value,
            "confidence": classification.confidence,
        },
        actor_type="api",
        actor_id="user",
        actor_name="manual_upload",
        document_id=document.id,
    )
    db.add(audit)
    
    # Optionally create AR/AP records
    ar_invoice_id = None
    ap_bill_id = None
    message = "Document uploaded successfully"
    
    try:
        if auto_create_ar and document.document_type == DocumentType.INVOICE and document.destination == DocumentDestination.ACCOUNT_RECEIVABLE:
            ar_invoice = create_ar_invoice_from_document(db, document.id)
            ar_invoice_id = str(ar_invoice.id)
            message = f"Document uploaded and AR Invoice {ar_invoice.invoice_number} created"
            
            # Create notification
            try:
                from app.models.document import Notification
                notification = Notification(
                    title="AR Invoice Created",
                    message=f"AR Invoice {ar_invoice.invoice_number} created from uploaded document {filename}",
                    notification_type="accounting",
                    severity="success",
                    reference_type="ar_invoice",
                    reference_id=None,
                    reference_code=str(ar_invoice.id),
                    amount=str(ar_invoice.total_amount),
                    document_id=document.id,
                )
                db.add(notification)
                db.commit()
            except Exception as notif_error:
                logger.warning(f"Failed to create notification: {notif_error}")
        
        elif auto_create_ap and document.document_type == DocumentType.INVOICE and document.destination == DocumentDestination.ACCOUNT_PAYABLE:
            ap_bill = create_ap_bill_from_document(db, document.id)
            ap_bill_id = str(ap_bill.id)
            message = f"Document uploaded and AP Bill {ap_bill.bill_number} created"
            
            # Create notification
            try:
                from app.models.document import Notification
                notification = Notification(
                    title="AP Bill Created",
                    message=f"AP Bill {ap_bill.bill_number} created from uploaded document {filename}",
                    notification_type="accounting",
                    severity="success",
                    reference_type="ap_bill",
                    reference_id=None,
                    reference_code=str(ap_bill.id),
                    amount=str(ap_bill.total_amount),
                    document_id=document.id,
                )
                db.add(notification)
                db.commit()
            except Exception as notif_error:
                logger.warning(f"Failed to create notification: {notif_error}")
    except Exception as accounting_error:
        logger.error(f"Failed to create AR/AP record: {accounting_error}", exc_info=True)
        message = f"Document uploaded but AR/AP creation failed: {str(accounting_error)}"
    
    return DocumentUploadResponse(
        document=DocumentResponse.from_orm(document),
        ar_invoice_id=ar_invoice_id,
        ap_bill_id=ap_bill_id,
        message=message,
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: int,
    update: DocumentUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update a document's metadata."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if update.document_type is not None:
        document.document_type = update.document_type
    if update.destination is not None:
        document.destination = update.destination
    if update.status is not None:
        document.status = update.status
    if update.vendor_name is not None:
        document.vendor_name = update.vendor_name
    if update.invoice_number is not None:
        document.invoice_number = update.invoice_number
    if update.invoice_date is not None:
        document.invoice_date = update.invoice_date
    if update.due_date is not None:
        document.due_date = update.due_date
    if update.total_amount is not None:
        document.total_amount = update.total_amount
    if update.is_draft is not None:
        document.is_draft = update.is_draft

    db.commit()
    db.refresh(document)
    return DocumentResponse.model_validate(document)


@router.post("/{document_id}/tags", response_model=DocumentResponse)
def assign_tags(
    document_id: int,
    request: TagAssignRequest,
    db: Session = Depends(get_db),
):
    """Assign tags to a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    document.tags.clear()
    for tag_name in request.tag_names:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name, is_system=False)
            db.add(tag)
            db.flush()
        document.tags.append(tag)

    db.commit()
    db.refresh(document)
    return DocumentResponse.model_validate(document)


@router.post("/{document_id}/reprocess")
def trigger_reprocess(document_id: int, db: Session = Depends(get_db)):
    """Trigger reprocessing of a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    reprocess_document.delay(document_id)
    return {"message": "Reprocessing started", "document_id": document_id}


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    """Delete a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(document)
    db.commit()
    return {"message": "Document deleted", "document_id": document_id}


@router.get("/{document_id}/download")
async def download_document(document_id: int, db: Session = Depends(get_db)):
    """Download a document file."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    from app.services.storage import get_storage_service
    from fastapi.responses import StreamingResponse
    import io
    
    storage = get_storage_service()
    if not storage:
        raise HTTPException(status_code=500, detail="Storage service not configured")
    
    if document.storage_path.startswith("local://"):
        raise HTTPException(status_code=404, detail="File stored locally, cannot download")
    
    try:
        content = await storage.download_file(document.storage_path)
        return StreamingResponse(
            io.BytesIO(content),
            media_type=document.content_type or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{document.original_filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download file: {str(e)}")
