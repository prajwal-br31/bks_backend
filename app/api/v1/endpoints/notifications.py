from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.document import Notification
from app.services.notifications import NotificationService

router = APIRouter()


class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    notification_type: str
    severity: str
    reference_type: Optional[str]
    reference_id: Optional[int]
    reference_code: Optional[str]
    amount: Optional[str]
    source: Optional[str]
    destination: Optional[str]
    link: Optional[str]
    actions: Optional[list]
    status: str
    dismissed: bool
    created_at: str

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    unread_count: int


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    status: Optional[str] = None,
    notification_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List notifications with filters."""
    service = NotificationService(db)
    
    notifications = service.get_notifications(
        status=status,
        notification_type=notification_type,
        limit=limit,
        offset=offset,
    )
    
    unread_count = service.get_unread_count()
    
    # Convert to response format
    items = []
    for n in notifications:
        items.append(NotificationResponse(
            id=n.id,
            title=n.title,
            message=n.message,
            notification_type=n.notification_type,
            severity=n.severity,
            reference_type=n.reference_type,
            reference_id=n.reference_id,
            reference_code=n.reference_code,
            amount=n.amount,
            source=n.source,
            destination=n.destination,
            link=n.link,
            actions=n.actions,
            status=n.status,
            dismissed=n.dismissed,
            created_at=n.created_at.isoformat() if n.created_at else "",
        ))
    
    return NotificationListResponse(items=items, unread_count=unread_count)


@router.get("/count", response_model=dict)
def get_unread_count(db: Session = Depends(get_db)):
    """Get count of unread notifications."""
    service = NotificationService(db)
    return {"unread_count": service.get_unread_count()}


@router.post("/{notification_id}/read", response_model=dict)
def mark_as_read(notification_id: int, db: Session = Depends(get_db)):
    """Mark a notification as read."""
    service = NotificationService(db)
    notification = service.mark_as_read(notification_id)
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"status": "read"}


@router.post("/read-all", response_model=dict)
def mark_all_as_read(db: Session = Depends(get_db)):
    """Mark all notifications as read."""
    service = NotificationService(db)
    count = service.mark_all_as_read()
    return {"marked_read": count}


@router.post("/{notification_id}/dismiss", response_model=dict)
def dismiss_notification(notification_id: int, db: Session = Depends(get_db)):
    """Dismiss a notification."""
    service = NotificationService(db)
    notification = service.dismiss(notification_id)
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"status": "dismissed"}


@router.delete("/{notification_id}", response_model=dict)
def delete_notification(notification_id: int, db: Session = Depends(get_db)):
    """Delete a notification."""
    service = NotificationService(db)
    deleted = service.delete(notification_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"status": "deleted"}
