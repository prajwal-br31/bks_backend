import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.document import Notification, Document, DocumentType, DocumentDestination
from .websocket_manager import websocket_manager

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for managing notifications.
    
    Handles:
    - Creating notifications
    - Querying notifications
    - Updating notification status
    - Pushing real-time updates via WebSocket
    """

    def __init__(self, db: Session):
        self.db = db

    async def create(
        self,
        title: str,
        message: str,
        notification_type: str = "email",
        severity: str = "info",
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        reference_code: Optional[str] = None,
        amount: Optional[str] = None,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        link: Optional[str] = None,
        actions: Optional[list] = None,
        user_id: Optional[str] = None,
        push_realtime: bool = True,
    ) -> Notification:
        """
        Create a new notification.
        
        Args:
            title: Notification title
            message: Notification message
            notification_type: Type (email, excel, teller, manual)
            severity: Severity level (success, warning, error, info)
            reference_type: Type of referenced entity
            reference_id: ID of referenced entity
            reference_code: Display code for reference
            amount: Amount to display
            source: Source of the notification
            destination: Destination (AP, AR)
            link: Link to view details
            actions: Available actions
            user_id: Target user (null for all)
            push_realtime: Whether to push via WebSocket
        
        Returns:
            Created Notification
        """
        notification = Notification(
            title=title,
            message=message,
            notification_type=notification_type,
            severity=severity,
            reference_type=reference_type,
            reference_id=reference_id,
            reference_code=reference_code,
            amount=amount,
            source=source,
            destination=destination,
            link=link,
            actions=actions,
            user_id=user_id,
            status="unread",
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        # Push via WebSocket
        if push_realtime:
            await self._push_notification(notification, user_id)
        
        return notification

    async def create_for_document(
        self,
        document: Document,
        needs_review: bool = False,
        push_realtime: bool = True,
    ) -> Notification:
        """
        Create a notification for a processed document.
        
        Args:
            document: The processed document
            needs_review: Whether manual review is required
            push_realtime: Whether to push via WebSocket
        
        Returns:
            Created Notification
        """
        if needs_review:
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
        
        amount_str = f"${document.total_amount:,.2f}" if document.total_amount else None
        
        return await self.create(
            title=title,
            message=f"From {document.source_email}: {document.original_filename}",
            notification_type="email",
            severity=severity,
            reference_type="document",
            reference_id=document.id,
            reference_code=document.invoice_number or f"DOC-{document.id}",
            amount=amount_str,
            source=document.source_email,
            destination=document.destination.value if document.destination else None,
            link=f"/documents/{document.id}",
            actions=actions,
            push_realtime=push_realtime,
        )

    def get_notifications(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        notification_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Notification]:
        """
        Get notifications with filters.
        
        Args:
            user_id: Filter by user
            status: Filter by status (unread, read, dismissed)
            notification_type: Filter by type
            limit: Maximum results
            offset: Offset for pagination
        
        Returns:
            List of notifications
        """
        query = self.db.query(Notification)
        
        # Filter by user or show global (user_id is null)
        if user_id:
            query = query.filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None))
            )
        
        if status:
            if status == "dismissed":
                query = query.filter(Notification.dismissed == True)
            else:
                query = query.filter(
                    Notification.status == status,
                    Notification.dismissed == False,
                )
        else:
            query = query.filter(Notification.dismissed == False)
        
        if notification_type:
            query = query.filter(Notification.notification_type == notification_type)
        
        return query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()

    def get_unread_count(self, user_id: Optional[str] = None) -> int:
        """Get count of unread notifications."""
        query = self.db.query(Notification).filter(
            Notification.status == "unread",
            Notification.dismissed == False,
        )
        
        if user_id:
            query = query.filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None))
            )
        
        return query.count()

    def mark_as_read(self, notification_id: int) -> Optional[Notification]:
        """Mark a notification as read."""
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            notification.status = "read"
            self.db.commit()
        
        return notification

    def mark_all_as_read(self, user_id: Optional[str] = None) -> int:
        """Mark all notifications as read."""
        query = self.db.query(Notification).filter(
            Notification.status == "unread"
        )
        
        if user_id:
            query = query.filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None))
            )
        
        count = query.update({"status": "read"})
        self.db.commit()
        return count

    def dismiss(self, notification_id: int) -> Optional[Notification]:
        """Dismiss a notification."""
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            notification.dismissed = True
            notification.status = "read"
            self.db.commit()
        
        return notification

    def delete(self, notification_id: int) -> bool:
        """Delete a notification."""
        result = self.db.query(Notification).filter(
            Notification.id == notification_id
        ).delete()
        self.db.commit()
        return result > 0

    async def _push_notification(self, notification: Notification, user_id: Optional[str]):
        """Push notification via WebSocket."""
        data = {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "notification_type": notification.notification_type,
            "severity": notification.severity,
            "reference_code": notification.reference_code,
            "amount": notification.amount,
            "source": notification.source,
            "link": notification.link,
            "actions": notification.actions,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        }
        
        await websocket_manager.send_notification(
            notification_type=notification.notification_type,
            title=notification.title,
            message=notification.message,
            data=data,
            user_id=user_id,
        )

