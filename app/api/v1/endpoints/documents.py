from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
)
from app.tasks.email_tasks import reprocess_document

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
            (Document.original_filename.ilike(search_term)) |
            (Document.vendor_name.ilike(search_term)) |
            (Document.invoice_number.ilike(search_term)) |
            (Document.source_email.ilike(search_term))
        )

    total = query.count()
    items = query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return DocumentListResponse(
        items=items,
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
    return document


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: int,
    update: DocumentUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update document fields."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(document, field, value)

    # If type or destination changed, may need to update review status
    if "document_type" in update_data or "destination" in update_data:
        if update_data.get("document_type") != DocumentType.UNKNOWN:
            document.requires_review = False
            document.status = DocumentStatus.PROCESSED

    # Create audit log
    audit = AuditLog(
        action="document_updated",
        details=update_data,
        actor_type="user",
        actor_name="api",
        document_id=document.id,
    )
    db.add(audit)
    db.commit()
    db.refresh(document)

    return document


@router.post("/{document_id}/reprocess", response_model=dict)
def trigger_reprocess(document_id: int, db: Session = Depends(get_db)):
    """Trigger reprocessing of a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Queue reprocessing task
    task = reprocess_document.delay(document_id)

    return {"status": "queued", "task_id": task.id}


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

    for tag_name in request.tag_names:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            db.flush()
        if tag not in document.tags:
            document.tags.append(tag)

    db.commit()
    db.refresh(document)
    return document


@router.delete("/{document_id}/tags/{tag_name}", response_model=DocumentResponse)
def remove_tag(
    document_id: int,
    tag_name: str,
    db: Session = Depends(get_db),
):
    """Remove a tag from a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    tag = db.query(Tag).filter(Tag.name == tag_name).first()
    if tag and tag in document.tags:
        document.tags.remove(tag)
        db.commit()
        db.refresh(document)

    return document


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    """Delete a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from S3 (would need to implement)
    # storage = S3StorageService()
    # await storage.delete_file(document.storage_path)

    db.delete(document)
    db.commit()

    return {"status": "deleted"}


@router.get("/{document_id}/download-url", response_model=dict)
async def get_download_url(document_id: int, db: Session = Depends(get_db)):
    """Get a presigned download URL for the document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    from app.services.storage import S3StorageService
    storage = S3StorageService()
    url = await storage.get_presigned_url(document.storage_path)

    return {"url": url, "expires_in": 3600}
