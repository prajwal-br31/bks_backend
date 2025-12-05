"""Celery tasks for email processing."""

import json
from datetime import datetime, timedelta
from typing import Optional
import structlog

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.session import SessionLocal
from ..models.email_document import (
    EmailMessage,
    EmailDocument,
    Tag,
    DocumentTag,
    AuditLog,
    ProcessingStatus,
    DocumentType,
    DocumentDestination,
)
from ..services.email_adapter import get_email_adapter, ParsedEmail
from ..services.attachment_extractor import AttachmentExtractor
from ..services.ocr_service import get_ocr_service
from ..services.storage_service import StorageService
from ..services.virus_scanner import get_virus_scanner
from ..services.classification_service import ClassificationService
from ..services.notification_service import NotificationService

logger = structlog.get_logger()
settings = get_settings()


def get_db() -> Session:
    """Get database session."""
    return SessionLocal()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def poll_emails_task(self):
    """Poll for new emails and queue them for processing."""
    logger.info("Starting email polling task")
    
    try:
        adapter = get_email_adapter()
        adapter.connect()
        
        # Get emails from last 24 hours to catch any missed
        since = datetime.utcnow() - timedelta(hours=24)
        
        processed_count = 0
        for email in adapter.fetch_new_emails(since=since):
            # Queue each email for processing
            process_email_task.delay(email_data=serialize_email(email))
            processed_count += 1
        
        adapter.disconnect()
        
        logger.info(f"Queued {processed_count} emails for processing")
        return {"queued": processed_count}
        
    except Exception as e:
        logger.error("Email polling failed", error=str(e))
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def process_email_task(self, email_data: dict):
    """Process a single email and its attachments."""
    db = get_db()
    email_message = None
    
    try:
        # Deserialize email
        email = deserialize_email(email_data)
        
        logger.info(
            "Processing email",
            message_id=email.message_id,
            from_address=email.from_address,
            subject=email.subject
        )
        
        # Check if already processed
        existing = db.query(EmailMessage).filter(
            EmailMessage.message_id == email.message_id
        ).first()
        
        if existing:
            logger.info("Email already processed", message_id=email.message_id)
            return {"status": "skipped", "reason": "already_processed"}
        
        # Create email record
        email_message = EmailMessage(
            message_id=email.message_id,
            thread_id=email.thread_id,
            from_address=email.from_address,
            to_addresses=json.dumps(email.to_addresses),
            cc_addresses=json.dumps(email.cc_addresses),
            subject=email.subject,
            received_date=email.received_date,
            body_text=email.body_text,
            body_html=email.body_html,
            source_provider=settings.email_provider,
            source_folder=settings.imap_folder if settings.email_provider == "imap" else settings.gmail_label,
            processing_status=ProcessingStatus.PROCESSING,
        )
        
        db.add(email_message)
        db.commit()
        db.refresh(email_message)
        
        # Log audit
        create_audit_log(
            db,
            None,
            "email_received",
            {"message_id": email.message_id, "from": email.from_address},
            "system"
        )
        
        # Extract attachments
        extractor = AttachmentExtractor()
        extracted_files = extractor.extract_all(email.attachments)
        
        if not extracted_files:
            logger.info("No processable attachments", message_id=email.message_id)
            email_message.processing_status = ProcessingStatus.COMPLETED
            email_message.processed_at = datetime.utcnow()
            db.commit()
            return {"status": "completed", "documents": 0}
        
        # Queue each document for processing
        document_ids = []
        for file in extracted_files:
            # Create document record
            doc = EmailDocument(
                email_id=email_message.id,
                original_filename=file.filename,
                content_type=file.content_type,
                file_size=file.size,
                file_hash=file.file_hash,
                storage_path="",  # Will be set during processing
                storage_bucket=settings.s3_bucket_name,
                processing_status=ProcessingStatus.PENDING,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            
            document_ids.append(doc.id)
            
            # Queue document processing
            process_document_task.delay(
                document_id=doc.id,
                file_content=file.content.hex(),  # Convert bytes to hex for JSON
                filename=file.filename,
                content_type=file.content_type
            )
        
        logger.info(
            "Queued documents for processing",
            message_id=email.message_id,
            document_count=len(document_ids)
        )
        
        return {"status": "queued", "documents": document_ids}
        
    except Exception as e:
        logger.error("Email processing failed", error=str(e))
        
        if email_message:
            email_message.processing_status = ProcessingStatus.FAILED
            email_message.error_message = str(e)
            db.commit()
        
        raise self.retry(exc=e)
    finally:
        db.close()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_document_task(
    self,
    document_id: int,
    file_content: str,
    filename: str,
    content_type: str
):
    """Process a single document: scan, OCR, classify, store."""
    db = get_db()
    
    try:
        # Get document record
        document = db.query(EmailDocument).filter(
            EmailDocument.id == document_id
        ).first()
        
        if not document:
            logger.error("Document not found", document_id=document_id)
            return {"status": "error", "reason": "not_found"}
        
        document.processing_status = ProcessingStatus.PROCESSING
        db.commit()
        
        # Convert hex back to bytes
        content = bytes.fromhex(file_content)
        
        logger.info(
            "Processing document",
            document_id=document_id,
            filename=filename
        )
        
        # Step 1: Virus scan
        scanner = get_virus_scanner()
        scan_result = scanner.scan(content, filename)
        
        document.virus_scanned = True
        document.virus_scan_result = scan_result.virus_name if not scan_result.is_clean else "clean"
        document.virus_scanned_at = datetime.utcnow()
        
        create_audit_log(
            db, document_id, "virus_scanned",
            {"result": "clean" if scan_result.is_clean else scan_result.virus_name},
            "system"
        )
        
        if not scan_result.is_clean:
            document.processing_status = ProcessingStatus.VIRUS_DETECTED
            document.error_message = f"Virus detected: {scan_result.virus_name}"
            db.commit()
            
            # Create notification
            notification_service = NotificationService(db)
            notification_service.create_virus_notification(document, scan_result.virus_name)
            
            logger.warning(
                "Virus detected",
                document_id=document_id,
                virus=scan_result.virus_name
            )
            return {"status": "virus_detected", "virus": scan_result.virus_name}
        
        # Step 2: Store file
        storage = StorageService()
        storage.ensure_bucket_exists()
        
        storage_result = storage.upload_file(
            content=content,
            filename=filename,
            content_type=content_type,
            file_hash=document.file_hash,
            metadata={"document_id": str(document_id)}
        )
        
        if not storage_result.success:
            raise Exception(f"Storage upload failed: {storage_result.error}")
        
        document.storage_path = storage_result.key
        document.storage_bucket = storage_result.bucket
        
        create_audit_log(
            db, document_id, "uploaded_to_storage",
            {"bucket": storage_result.bucket, "key": storage_result.key},
            "system"
        )
        
        # Step 3: OCR
        ocr_service = get_ocr_service()
        ocr_result = ocr_service.extract_text(content, content_type, filename)
        
        document.ocr_text = ocr_result.text
        document.ocr_provider = ocr_result.provider
        document.ocr_confidence = ocr_result.confidence
        
        create_audit_log(
            db, document_id, "ocr_processed",
            {"provider": ocr_result.provider, "confidence": ocr_result.confidence},
            "system"
        )
        
        # Step 4: Classification
        classifier = ClassificationService(settings.classification_confidence_threshold)
        classification = classifier.classify(ocr_result.text, filename)
        
        document.document_type = classification.document_type
        document.destination = classification.destination
        document.classification_confidence = classification.confidence
        document.parsed_fields = classifier.to_dict(classification.parsed_fields)
        
        create_audit_log(
            db, document_id, "classified",
            {
                "type": classification.document_type.value,
                "destination": classification.destination.value,
                "confidence": classification.confidence,
                "reasons": classification.classification_reasons
            },
            "system"
        )
        
        # Step 5: Add tags
        ensure_system_tags(db)
        
        if classification.document_type == DocumentType.INVOICE:
            add_tag_to_document(db, document_id, "invoice")
        elif classification.document_type == DocumentType.RECEIPT:
            add_tag_to_document(db, document_id, "receipt")
        
        if classification.destination == DocumentDestination.NEEDS_REVIEW:
            add_tag_to_document(db, document_id, "needs_review")
        
        # Step 6: Set draft mode
        document.is_draft = not settings.auto_post_mode
        
        # Step 7: Mark as completed
        document.processing_status = ProcessingStatus.COMPLETED
        document.processed_at = datetime.utcnow()
        db.commit()
        
        # Step 8: Create notification
        notification_service = NotificationService(db)
        
        if classification.destination == DocumentDestination.NEEDS_REVIEW:
            notification_service.create_review_notification(
                document,
                f"Low confidence ({classification.confidence:.0%})"
            )
        else:
            notification_service.create_success_notification(
                document,
                document.parsed_fields
            )
        
        # Update parent email status
        update_email_status(db, document.email_id)
        
        logger.info(
            "Document processing completed",
            document_id=document_id,
            type=classification.document_type.value,
            confidence=classification.confidence
        )
        
        return {
            "status": "completed",
            "document_type": classification.document_type.value,
            "destination": classification.destination.value,
            "confidence": classification.confidence
        }
        
    except Exception as e:
        logger.error("Document processing failed", document_id=document_id, error=str(e))
        
        if document:
            document.processing_status = ProcessingStatus.FAILED
            document.error_message = str(e)
            db.commit()
            
            # Create error notification
            notification_service = NotificationService(db)
            notification_service.create_error_notification(document, str(e))
        
        raise self.retry(exc=e)
    finally:
        db.close()


@shared_task
def cleanup_old_documents_task():
    """Clean up old processed documents (audit retention)."""
    db = get_db()
    
    try:
        # Keep documents for 90 days
        cutoff = datetime.utcnow() - timedelta(days=90)
        
        # Find old dismissed notifications
        deleted_notifications = db.query(Notification).filter(
            Notification.is_dismissed == True,
            Notification.created_at < cutoff
        ).delete()
        
        db.commit()
        
        logger.info(f"Cleaned up {deleted_notifications} old notifications")
        return {"deleted_notifications": deleted_notifications}
        
    except Exception as e:
        logger.error("Cleanup task failed", error=str(e))
        raise
    finally:
        db.close()


# Helper functions

def serialize_email(email: ParsedEmail) -> dict:
    """Serialize email for task queue."""
    return {
        "message_id": email.message_id,
        "thread_id": email.thread_id,
        "from_address": email.from_address,
        "to_addresses": email.to_addresses,
        "cc_addresses": email.cc_addresses,
        "subject": email.subject,
        "received_date": email.received_date.isoformat(),
        "body_text": email.body_text,
        "body_html": email.body_html,
        "attachments": [
            {
                "filename": a.filename,
                "content_type": a.content_type,
                "content": a.content.hex(),
                "size": a.size,
                "content_id": a.content_id,
            }
            for a in email.attachments
        ]
    }


def deserialize_email(data: dict) -> ParsedEmail:
    """Deserialize email from task queue."""
    from ..services.email_adapter import EmailAttachment
    
    return ParsedEmail(
        message_id=data["message_id"],
        thread_id=data.get("thread_id"),
        from_address=data["from_address"],
        to_addresses=data["to_addresses"],
        cc_addresses=data["cc_addresses"],
        subject=data["subject"],
        received_date=datetime.fromisoformat(data["received_date"]),
        body_text=data.get("body_text"),
        body_html=data.get("body_html"),
        attachments=[
            EmailAttachment(
                filename=a["filename"],
                content_type=a["content_type"],
                content=bytes.fromhex(a["content"]),
                size=a["size"],
                content_id=a.get("content_id"),
            )
            for a in data.get("attachments", [])
        ]
    )


def create_audit_log(
    db: Session,
    document_id: Optional[int],
    event_type: str,
    event_data: dict,
    actor: str
):
    """Create an audit log entry."""
    log = AuditLog(
        document_id=document_id,
        event_type=event_type,
        event_data=event_data,
        actor=actor,
    )
    db.add(log)
    db.commit()


def ensure_system_tags(db: Session):
    """Ensure system tags exist."""
    system_tags = [
        ("invoice", "#10b981", "Automatically tagged as invoice"),
        ("receipt", "#3b82f6", "Automatically tagged as receipt"),
        ("needs_review", "#f59e0b", "Requires manual review"),
    ]
    
    for name, color, description in system_tags:
        existing = db.query(Tag).filter(Tag.name == name).first()
        if not existing:
            tag = Tag(
                name=name,
                color=color,
                description=description,
                is_system=True
            )
            db.add(tag)
    
    db.commit()


def add_tag_to_document(db: Session, document_id: int, tag_name: str):
    """Add a tag to a document."""
    tag = db.query(Tag).filter(Tag.name == tag_name).first()
    if tag:
        doc_tag = DocumentTag(
            document_id=document_id,
            tag_id=tag.id,
            added_by="system"
        )
        db.add(doc_tag)
        db.commit()


def update_email_status(db: Session, email_id: int):
    """Update parent email status based on documents."""
    email = db.query(EmailMessage).filter(EmailMessage.id == email_id).first()
    if not email:
        return
    
    documents = db.query(EmailDocument).filter(
        EmailDocument.email_id == email_id
    ).all()
    
    if not documents:
        email.processing_status = ProcessingStatus.COMPLETED
    elif all(d.processing_status == ProcessingStatus.COMPLETED for d in documents):
        email.processing_status = ProcessingStatus.COMPLETED
    elif any(d.processing_status == ProcessingStatus.FAILED for d in documents):
        email.processing_status = ProcessingStatus.FAILED
    elif any(d.processing_status == ProcessingStatus.NEEDS_REVIEW for d in documents):
        email.processing_status = ProcessingStatus.NEEDS_REVIEW
    
    email.processed_at = datetime.utcnow()
    db.commit()


# Import Notification model at module level to avoid circular imports
from ..models.email_document import Notification

