from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "bookkeeping",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.email_tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task routing
    task_routes={
        "app.tasks.email_tasks.*": {"queue": "email_processing"},
    },
    
    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Rate limiting
    task_annotations={
        "app.tasks.email_tasks.process_email": {
            "rate_limit": "10/m",  # Max 10 emails per minute
        },
    },
    
    # Result expiration
    result_expires=3600,  # 1 hour
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
)

# Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "poll-emails-every-30-seconds": {
        "task": "app.tasks.email_tasks.poll_inbox",
        "schedule": 30.0,  # Every 30 seconds
    },
    "cleanup-old-jobs-daily": {
        "task": "app.tasks.email_tasks.cleanup_old_jobs",
        "schedule": 86400.0,  # Daily
    },
}

