from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.dependencies import get_db
from app.models.document import (
    Document,
    DocumentStatus,
    EmailProcessingJob,
    ProcessingStatus,
    AuditLog,
)
from app.tasks.email_tasks import poll_inbox, process_email

router = APIRouter()


class EmailJobResponse(BaseModel):
    id: int
    email_uid: str
    email_from: str
    email_subject: Optional[str]
    email_date: Optional[datetime]
    status: ProcessingStatus
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    retry_count: int
    attachments_count: int
    documents_created: int
    created_at: datetime

    class Config:
        from_attributes = True


class EmailJobListResponse(BaseModel):
    items: List[EmailJobResponse]
    total: int


class MetricsResponse(BaseModel):
    processed_count: int
    failed_count: int
    pending_count: int
    avg_processing_time_seconds: float
    documents_created_today: int
    documents_needs_review: int
    queue_depth: int


class AuditLogResponse(BaseModel):
    id: int
    action: str
    details: Optional[dict]
    actor_type: str
    actor_name: Optional[str]
    document_id: Optional[int]
    timestamp: datetime

    class Config:
        from_attributes = True


@router.get("/email-jobs", response_model=EmailJobListResponse)
def list_email_jobs(
    status: Optional[ProcessingStatus] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List email processing jobs."""
    query = db.query(EmailProcessingJob)
    
    if status:
        query = query.filter(EmailProcessingJob.status == status)
    
    total = query.count()
    items = query.order_by(EmailProcessingJob.created_at.desc()).offset(offset).limit(limit).all()
    
    return EmailJobListResponse(items=items, total=total)


@router.get("/email-jobs/{job_id}", response_model=EmailJobResponse)
def get_email_job(job_id: int, db: Session = Depends(get_db)):
    """Get a specific email processing job."""
    job = db.query(EmailProcessingJob).filter(EmailProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/email-jobs/{job_id}/retry", response_model=dict)
def retry_email_job(job_id: int, db: Session = Depends(get_db)):
    """Retry a failed email processing job."""
    job = db.query(EmailProcessingJob).filter(EmailProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != ProcessingStatus.FAILED:
        raise HTTPException(status_code=400, detail="Can only retry failed jobs")
    
    # Reset job status
    job.status = ProcessingStatus.QUEUED
    job.error_message = None
    db.commit()
    
    # Queue task
    task = process_email.delay(job_id)
    
    return {"status": "queued", "task_id": task.id}


@router.post("/trigger-poll", response_model=dict)
def trigger_poll():
    """Manually trigger email inbox poll."""
    task = poll_inbox.delay()
    return {"status": "triggered", "task_id": task.id}


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db)):
    """Get processing metrics."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Job counts
    processed_count = db.query(EmailProcessingJob).filter(
        EmailProcessingJob.status == ProcessingStatus.COMPLETED
    ).count()
    
    failed_count = db.query(EmailProcessingJob).filter(
        EmailProcessingJob.status == ProcessingStatus.FAILED
    ).count()
    
    pending_count = db.query(EmailProcessingJob).filter(
        EmailProcessingJob.status.in_([ProcessingStatus.QUEUED, ProcessingStatus.DOWNLOADING])
    ).count()
    
    # Average processing time
    completed_jobs = db.query(EmailProcessingJob).filter(
        EmailProcessingJob.status == ProcessingStatus.COMPLETED,
        EmailProcessingJob.started_at.isnot(None),
        EmailProcessingJob.completed_at.isnot(None),
    ).all()
    
    if completed_jobs:
        total_time = sum(
            (job.completed_at - job.started_at).total_seconds()
            for job in completed_jobs
        )
        avg_time = total_time / len(completed_jobs)
    else:
        avg_time = 0.0
    
    # Documents
    documents_created_today = db.query(Document).filter(
        Document.created_at >= today
    ).count()
    
    documents_needs_review = db.query(Document).filter(
        Document.requires_review == True
    ).count()
    
    # Queue depth (pending jobs)
    queue_depth = pending_count
    
    return MetricsResponse(
        processed_count=processed_count,
        failed_count=failed_count,
        pending_count=pending_count,
        avg_processing_time_seconds=round(avg_time, 2),
        documents_created_today=documents_created_today,
        documents_needs_review=documents_needs_review,
        queue_depth=queue_depth,
    )


@router.get("/audit-logs", response_model=List[AuditLogResponse])
def list_audit_logs(
    document_id: Optional[int] = None,
    action: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List audit logs."""
    query = db.query(AuditLog)
    
    if document_id:
        query = query.filter(AuditLog.document_id == document_id)
    if action:
        query = query.filter(AuditLog.action == action)
    
    return query.order_by(AuditLog.timestamp.desc()).limit(limit).all()


@router.get("/stats/by-type", response_model=dict)
def get_stats_by_type(db: Session = Depends(get_db)):
    """Get document counts by type."""
    results = db.query(
        Document.document_type,
        func.count(Document.id).label("count")
    ).group_by(Document.document_type).all()
    
    return {r.document_type.value: r.count for r in results}


@router.get("/stats/by-destination", response_model=dict)
def get_stats_by_destination(db: Session = Depends(get_db)):
    """Get document counts by destination."""
    results = db.query(
        Document.destination,
        func.count(Document.id).label("count")
    ).group_by(Document.destination).all()
    
    return {r.destination.value: r.count for r in results}


@router.get("/stats/by-status", response_model=dict)
def get_stats_by_status(db: Session = Depends(get_db)):
    """Get document counts by status."""
    results = db.query(
        Document.status,
        func.count(Document.id).label("count")
    ).group_by(Document.status).all()
    
    return {r.status.value: r.count for r in results}
