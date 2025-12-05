"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab

from ..core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "bookkeeping_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
    
    # Result settings
    result_expires=86400,  # 24 hours
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    
    # Task routing
    task_routes={
        "app.worker.tasks.process_email_task": {"queue": "emails"},
        "app.worker.tasks.process_document_task": {"queue": "documents"},
        "app.worker.tasks.poll_emails_task": {"queue": "polling"},
    },
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        "poll-emails-every-30-seconds": {
            "task": "app.worker.tasks.poll_emails_task",
            "schedule": settings.email_poll_interval_seconds,
        },
        "cleanup-old-documents-daily": {
            "task": "app.worker.tasks.cleanup_old_documents_task",
            "schedule": crontab(hour=2, minute=0),  # 2 AM daily
        },
    },
)

# Optional: Configure for specific queues
celery_app.conf.task_queues = {
    "emails": {
        "exchange": "emails",
        "routing_key": "emails",
    },
    "documents": {
        "exchange": "documents", 
        "routing_key": "documents",
    },
    "polling": {
        "exchange": "polling",
        "routing_key": "polling",
    },
}

