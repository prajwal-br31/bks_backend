"""Notification service for creating and broadcasting notifications."""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
import structlog

from sqlalchemy.orm import Session

from ..models.email_document import (
    Notification, 
    EmailDocument, 
    DocumentType,
    DocumentDestination,
    ProcessingStatus
)
from ..core.config import get_settings

logger = structlog.get_logger()


class NotificationService:
    """Service for managing notifications."""
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
    
    def create_success_notification(
        self,
        document: EmailDocument,
        parsed_fields: dict
    ) -> Notification:
        """Create notification for successful document processing."""
        # Determine type label
        type_labels = {
            DocumentType.INVOICE: "Invoice",
            DocumentType.RECEIPT: "Receipt",
            DocumentType.STATEMENT: "Statement",
            DocumentType.UNKNOWN: "Document",
        }
        type_label = type_labels.get(document.document_type, "Document")
        
        # Determine destination label
        dest_labels = {
            DocumentDestination.ACCOUNT_PAYABLE: "Account Payable",
            DocumentDestination.ACCOUNT_RECEIVABLE: "Account Receivable",
            DocumentDestination.NEEDS_REVIEW: "Review Queue",
        }
        dest_label = dest_labels.get(document.destination, "Unknown")
        
        # Build title and message
        vendor_name = parsed_fields.get('vendor_name', 'Unknown Vendor')
        invoice_num = parsed_fields.get('invoice_number') or parsed_fields.get('receipt_number', '')
        amount = parsed_fields.get('total_amount')
        
        if invoice_num:
            title = f"Email processed — {type_label} #{invoice_num} uploaded"
        else:
            title = f"Email processed — {type_label} uploaded"
        
        message_parts = [f"From: {vendor_name}"]
        if invoice_num:
            message_parts.append(f"Reference: {invoice_num}")
        if amount:
            message_parts.append(f"Amount: ${amount:,.2f}")
        message_parts.append(f"Destination: {dest_label}")
        
        message = " • ".join(message_parts)
        
        # Determine severity based on confidence
        if document.classification_confidence >= 0.9:
            severity = "success"
        elif document.classification_confidence >= 0.75:
            severity = "info"
        else:
            severity = "warning"
        
        # Create notification
        notification = Notification(
            document_id=document.id,
            title=title,
            message=message,
            notification_type="email",
            severity=severity,
            reference_id=invoice_num or f"DOC-{document.id}",
            amount=f"${amount:,.2f}" if amount else None,
            source="Mailbox automation",
            actions=[
                {"label": "View Document", "action": "view", "url": f"/documents/{document.id}"},
            ]
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        logger.info(
            "Success notification created",
            notification_id=notification.id,
            document_id=document.id
        )
        
        return notification
    
    def create_review_notification(
        self,
        document: EmailDocument,
        reason: str
    ) -> Notification:
        """Create notification for documents needing review."""
        title = "Review required — Document needs classification"
        message = f"A document could not be automatically classified. Reason: {reason}"
        
        notification = Notification(
            document_id=document.id,
            title=title,
            message=message,
            notification_type="email",
            severity="warning",
            reference_id=f"DOC-{document.id}",
            source="Mailbox automation",
            actions=[
                {"label": "View Document", "action": "view", "url": f"/documents/{document.id}"},
                {"label": "Mark as Invoice", "action": "classify", "params": {"type": "invoice"}},
                {"label": "Mark as Receipt", "action": "classify", "params": {"type": "receipt"}},
                {"label": "Reject", "action": "reject"},
            ]
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        logger.info(
            "Review notification created",
            notification_id=notification.id,
            document_id=document.id
        )
        
        return notification
    
    def create_error_notification(
        self,
        document: Optional[EmailDocument],
        error_message: str,
        source_email: Optional[str] = None
    ) -> Notification:
        """Create notification for processing errors."""
        title = "Error — Document processing failed"
        
        if source_email:
            message = f"Failed to process document from {source_email}. Error: {error_message}"
        else:
            message = f"Document processing failed. Error: {error_message}"
        
        notification = Notification(
            document_id=document.id if document else None,
            title=title,
            message=message,
            notification_type="email",
            severity="error",
            source="Mailbox automation",
            actions=[
                {"label": "View Details", "action": "view_error"},
            ] + ([{"label": "Retry", "action": "retry"}] if document else [])
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        logger.info(
            "Error notification created",
            notification_id=notification.id,
            error=error_message
        )
        
        return notification
    
    def create_virus_notification(
        self,
        document: EmailDocument,
        virus_name: str
    ) -> Notification:
        """Create notification for virus detection."""
        title = "Security Alert — Virus detected"
        message = f"A virus ({virus_name}) was detected in file '{document.original_filename}'. The file has been quarantined."
        
        notification = Notification(
            document_id=document.id,
            title=title,
            message=message,
            notification_type="email",
            severity="error",
            reference_id=f"DOC-{document.id}",
            source="Security scan",
            actions=[
                {"label": "View Details", "action": "view_security"},
                {"label": "Delete Permanently", "action": "delete"},
            ]
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        logger.warning(
            "Virus notification created",
            notification_id=notification.id,
            document_id=document.id,
            virus=virus_name
        )
        
        return notification
    
    def get_notifications(
        self,
        user_id: Optional[str] = None,
        is_read: Optional[bool] = None,
        limit: int = 50
    ) -> List[Notification]:
        """Get notifications with optional filters."""
        query = self.db.query(Notification)
        
        if user_id:
            query = query.filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None))
            )
        
        if is_read is not None:
            query = query.filter(Notification.is_read == is_read)
        
        query = query.filter(Notification.is_dismissed == False)
        query = query.order_by(Notification.created_at.desc())
        query = query.limit(limit)
        
        return query.all()
    
    def mark_as_read(self, notification_id: int) -> bool:
        """Mark notification as read."""
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            notification.is_read = True
            self.db.commit()
            return True
        return False
    
    def dismiss(self, notification_id: int) -> bool:
        """Dismiss notification."""
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            notification.is_dismissed = True
            notification.is_read = True
            self.db.commit()
            return True
        return False
    
    def to_dict(self, notification: Notification) -> dict:
        """Convert notification to dictionary for API response."""
        return {
            'id': f"n-{notification.id}",
            'title': notification.title,
            'message': notification.message,
            'reference': notification.reference_id or "",
            'amount': notification.amount or "",
            'source': notification.source or "",
            'type': notification.notification_type,
            'status': 'read' if notification.is_read else 'unread',
            'dismissed': notification.is_dismissed,
            'createdAt': notification.created_at.isoformat() + 'Z',
            'actions': notification.actions or [],
            'severity': notification.severity,
        }

