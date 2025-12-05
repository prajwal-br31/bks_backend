import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from celery import shared_task
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document import (
    Document,
    DocumentType,
    DocumentStatus,
    DocumentDestination,
    ProcessingStatus,
    Tag,
    AuditLog,
    EmailProcessingJob,
    Notification,
)
from app.services.email import get_email_adapter, is_email_whitelisted, EmailMessage
from app.services.extraction import AttachmentExtractor, ContentExtractor
from app.services.ocr import get_ocr_provider
from app.services.classification import DocumentClassifier
from app.services.storage import S3StorageService
from app.services.security import VirusScanner, FileValidator

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def poll_inbox(self):
    """
    Poll email inbox for new messages.
    
    This is run periodically by Celery Beat.
    """
    settings = get_settings()
    
    try:
        async def _poll():
            adapter = get_email_adapter()
            
            async with adapter:
                emails = await adapter.fetch_unread_emails(
                    limit=20,
                    since=datetime.utcnow() - timedelta(days=7),
                )
                
                logger.info(f"Found {len(emails)} unread emails")
                
                for email in emails:
                    # Check whitelist
                    if not is_email_whitelisted(email.from_address):
                        logger.debug(f"Skipping non-whitelisted email from {email.from_address}")
                        continue
                    
                    # Skip if already processed
                    db = SessionLocal()
                    try:
                        existing = db.query(EmailProcessingJob).filter(
                            EmailProcessingJob.email_message_id == email.message_id
                        ).first()
                        
                        if existing:
                            logger.debug(f"Email already processed: {email.message_id}")
                            continue
                        
                        # Create processing job
                        job = EmailProcessingJob(
                            email_uid=email.uid,
                            email_message_id=email.message_id,
                            email_from=email.from_address,
                            email_to=",".join(email.to_addresses),
                            email_subject=email.subject,
                            email_date=email.date,
                            email_body_preview=email.body_text[:500] if email.body_text else None,
                            status=ProcessingStatus.QUEUED,
                            attachments_count=len(email.attachments),
                        )
                        db.add(job)
                        db.commit()
                        
                        # Queue processing task
                        process_email.delay(job.id)
                        
                        logger.info(f"Queued email for processing: {email.subject}")
                        
                    finally:
                        db.close()
                
                return len(emails)
        
        return run_async(_poll())
        
    except Exception as e:
        logger.error(f"Error polling inbox: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=120)
def process_email(self, job_id: int):
    """
    Process a single email and its attachments.
    
    Args:
        job_id: ID of the EmailProcessingJob record
    """
    db = SessionLocal()
    settings = get_settings()
    
    try:
        # Get job
        job = db.query(EmailProcessingJob).filter(EmailProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Job not found: {job_id}")
            return
        
        # Update status
        job.status = ProcessingStatus.DOWNLOADING
        job.started_at = datetime.utcnow()
        job.celery_task_id = self.request.id
        db.commit()
        
        async def _process():
            # Fetch email
            adapter = get_email_adapter()
            async with adapter:
                email = await adapter.fetch_email_by_uid(job.email_uid)
                if not email:
                    raise Exception(f"Email not found: {job.email_uid}")
                
                # Initialize services
                attachment_extractor = AttachmentExtractor()
                content_extractor = ContentExtractor()
                ocr_provider = get_ocr_provider()
                classifier = DocumentClassifier(settings.classification_confidence_threshold)
                storage = S3StorageService()
                virus_scanner = VirusScanner()
                file_validator = FileValidator()
                
                documents_created = 0
                
                # Process attachments
                for attachment in email.attachments:
                    try:
                        # Extract files (handles ZIP archives)
                        job.status = ProcessingStatus.EXTRACTING
                        db.commit()
                        
                        extraction_result = attachment_extractor.extract(
                            attachment.filename,
                            attachment.content,
                            attachment.content_type,
                        )
                        
                        for extracted_file in extraction_result.files:
                            # Validate file
                            validation = file_validator.validate(
                                extracted_file.content,
                                extracted_file.filename,
                                extracted_file.content_type,
                            )
                            
                            if not validation.is_valid:
                                logger.warning(f"File validation failed: {validation.errors}")
                                continue
                            
                            # Virus scan
                            job.status = ProcessingStatus.SCANNING
                            db.commit()
                            
                            scan_result = await virus_scanner.scan(extracted_file.content)
                            if not scan_result.is_clean:
                                logger.warning(f"Virus detected: {scan_result.virus_name}")
                                # Create audit log
                                audit = AuditLog(
                                    action="virus_detected",
                                    details={
                                        "filename": extracted_file.filename,
                                        "virus": scan_result.virus_name,
                                    },
                                    actor_type="system",
                                    actor_name="virus_scanner",
                                )
                                db.add(audit)
                                db.commit()
                                continue
                            
                            # Extract content
                            content = content_extractor.extract(
                                extracted_file.content,
                                extracted_file.content_type,
                                extracted_file.filename,
                            )
                            
                            # OCR if needed
                            if content.metadata.get("needs_ocr"):
                                if extracted_file.content_type.startswith("image/"):
                                    ocr_result = await ocr_provider.extract_text(
                                        extracted_file.content,
                                        extracted_file.content_type,
                                    )
                                elif extracted_file.content_type == "application/pdf":
                                    ocr_result = await ocr_provider.extract_text_from_pdf(
                                        extracted_file.content
                                    )
                                else:
                                    ocr_result = None
                                
                                if ocr_result and ocr_result.text:
                                    content.text = ocr_result.text
                                    content.confidence = ocr_result.confidence
                            
                            # Classify
                            job.status = ProcessingStatus.CLASSIFYING
                            db.commit()
                            
                            classification = classifier.classify(
                                content.text,
                                source_email=email.from_address,
                            )
                            
                            # Upload to S3
                            job.status = ProcessingStatus.UPLOADING
                            db.commit()
                            
                            await storage.ensure_bucket_exists()
                            stored_file = await storage.upload_file(
                                extracted_file.content,
                                extracted_file.filename,
                                extracted_file.content_type,
                                folder="documents",
                                metadata={
                                    "source_email": email.from_address,
                                    "email_subject": email.subject,
                                    "document_type": classification.document_type.value,
                                },
                            )
                            
                            # Create document record
                            document = Document(
                                source_email=email.from_address,
                                source_email_subject=email.subject,
                                source_email_date=email.date,
                                email_message_id=email.message_id,
                                original_filename=extracted_file.filename,
                                storage_path=stored_file.key,
                                storage_hash=stored_file.content_hash,
                                content_type=extracted_file.content_type,
                                file_size=extracted_file.size,
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
                                ocr_text=content.text[:10000] if content.text else None,
                                status=DocumentStatus.NEEDS_REVIEW if classification.needs_review else DocumentStatus.PROCESSED,
                                processing_status=ProcessingStatus.COMPLETED,
                                is_draft=not settings.auto_post_mode,
                                is_auto_posted=settings.auto_post_mode,
                                requires_review=classification.needs_review,
                                virus_scanned=True,
                                virus_clean=True,
                                processing_job_id=job.id,
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
                            
                            documents_created += 1
                            
                            # Create audit log
                            audit = AuditLog(
                                action="document_created",
                                details={
                                    "filename": extracted_file.filename,
                                    "type": classification.document_type.value,
                                    "destination": classification.destination.value,
                                    "confidence": classification.confidence,
                                },
                                actor_type="celery",
                                actor_id=self.request.id,
                                actor_name="email_processor",
                                document_id=document.id,
                            )
                            db.add(audit)
                            
                            # Create notification
                            create_notification(
                                db,
                                document,
                                classification,
                                email.from_address,
                            )
                            
                    except Exception as e:
                        logger.error(f"Error processing attachment {attachment.filename}: {e}")
                        continue
                
                # Mark email as processed
                await adapter.mark_as_processed(job.email_uid)
                
                return documents_created
        
        documents_created = run_async(_process())
        
        # Update job status
        job.status = ProcessingStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        job.documents_created = documents_created
        db.commit()
        
        logger.info(f"Processed email job {job_id}: created {documents_created} documents")
        return documents_created
        
    except Exception as e:
        logger.error(f"Error processing email job {job_id}: {e}")
        
        # Update job with error
        if job:
            job.status = ProcessingStatus.FAILED
            job.error_message = str(e)
            job.retry_count += 1
            db.commit()
        
        # Retry if not exceeded max
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        raise
        
    finally:
        db.close()


@celery_app.task
def cleanup_old_jobs():
    """Clean up old processing jobs and audit logs."""
    db = SessionLocal()
    
    try:
        # Delete jobs older than 30 days
        cutoff = datetime.utcnow() - timedelta(days=30)
        
        deleted = db.query(EmailProcessingJob).filter(
            EmailProcessingJob.created_at < cutoff,
            EmailProcessingJob.status == ProcessingStatus.COMPLETED,
        ).delete()
        
        db.commit()
        logger.info(f"Cleaned up {deleted} old processing jobs")
        
        return deleted
        
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2)
def reprocess_document(self, document_id: int):
    """
    Reprocess a document (e.g., after manual classification change).
    
    Args:
        document_id: ID of the document to reprocess
    """
    db = SessionLocal()
    
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Document not found: {document_id}")
            return
        
        # Re-classify
        settings = get_settings()
        classifier = DocumentClassifier(settings.classification_confidence_threshold)
        
        if document.ocr_text:
            classification = classifier.classify(
                document.ocr_text,
                source_email=document.source_email,
            )
            
            # Update document
            document.document_type = classification.document_type
            document.destination = classification.destination
            document.confidence_score = classification.confidence
            document.requires_review = classification.needs_review
            document.status = (
                DocumentStatus.NEEDS_REVIEW 
                if classification.needs_review 
                else DocumentStatus.PROCESSED
            )
            
            # Update parsed fields
            document.vendor_name = classification.parsed_fields.vendor_name
            document.invoice_number = classification.parsed_fields.invoice_number
            document.invoice_date = classification.parsed_fields.invoice_date
            document.due_date = classification.parsed_fields.due_date
            document.total_amount = classification.parsed_fields.total_amount
            document.tax_amount = classification.parsed_fields.tax_amount
            
            db.commit()
            
            # Audit log
            audit = AuditLog(
                action="document_reprocessed",
                details={
                    "new_type": classification.document_type.value,
                    "new_destination": classification.destination.value,
                    "confidence": classification.confidence,
                },
                actor_type="celery",
                actor_id=self.request.id,
                actor_name="reprocessor",
                document_id=document.id,
            )
            db.add(audit)
            db.commit()
            
            logger.info(f"Reprocessed document {document_id}")
        
    except Exception as e:
        logger.error(f"Error reprocessing document {document_id}: {e}")
        raise self.retry(exc=e)
        
    finally:
        db.close()


def create_notification(
    db: Session,
    document: Document,
    classification,
    source_email: str,
):
    """Create a notification for a processed document."""
    
    if classification.needs_review:
        title = "Review required — Document needs classification"
        severity = "warning"
        actions = [
            {"action": "view", "label": "View Document"},
            {"action": "mark_invoice", "label": "Mark as Invoice"},
            {"action": "mark_receipt", "label": "Mark as Receipt"},
            {"action": "reject", "label": "Reject"},
        ]
    else:
        doc_type = "Invoice" if document.document_type == DocumentType.INVOICE else "Receipt"
        dest = "AP" if document.destination == DocumentDestination.ACCOUNT_PAYABLE else "AR"
        title = f"Email processed — {doc_type} uploaded to {dest}"
        severity = "success"
        actions = [{"action": "view", "label": "View Document"}]
    
    # Format amount
    amount_str = f"${document.total_amount:,.2f}" if document.total_amount else "N/A"
    
    notification = Notification(
        title=title,
        message=f"From {source_email}: {document.original_filename}",
        notification_type="email",
        severity=severity,
        reference_type="document",
        reference_id=document.id,
        reference_code=document.invoice_number or f"DOC-{document.id}",
        amount=amount_str,
        source=source_email,
        destination=document.destination.value if document.destination else None,
        link=f"/documents/{document.id}",
        actions=actions,
        status="unread",
    )
    
    db.add(notification)
    db.commit()

