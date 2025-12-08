# Backend Architecture Summary

## Overview
This document describes the current architecture of the Bash Bookkeeping API backend. All existing routers, modules, and configurations are documented here.

**Last Updated**: 2025-12-07

---

## 1. FastAPI Application Entry Point

**Location**: `app/main.py`

- FastAPI app instance is created here
- Uses `app.core.config.get_settings()` for configuration
- Includes CORS middleware (currently allows all origins - configure for production)
- Registers the main API router from `app.api.v1`
- Root endpoints:
  - `GET /` - Root endpoint with app info
  - `GET /health` - Health check endpoint

**Router Registration**:
```python
from app.api.v1 import api_router
app.include_router(api_router, prefix=settings.api_v1_prefix)
```

---

## 2. API Routers

**Location**: `app/api/v1/__init__.py`

All routers are registered under the `/api/v1` prefix:

| Router | Prefix | Tags | Endpoint File |
|--------|--------|------|---------------|
| Documents | `/api/v1/documents` | `documents` | `endpoints/documents.py` |
| Notifications | `/api/v1/notifications` | `notifications` | `endpoints/notifications.py` |
| Admin | `/api/v1/admin` | `admin` | `endpoints/admin.py` |
| Health | `/api/v1/health` | `health` | `endpoints/health.py` |
| WebSocket | `/api/v1/ws` | `websocket` | `endpoints/websocket.py` |
| Bank Feed | `/api/v1/bank-feed` | `bank-feed` | `endpoints/bank_feed.py` |

**⚠️ DO NOT MODIFY**: These router registrations are critical. Any changes to prefixes or tags will break existing API contracts.

---

## 3. Configuration Management

**Location**: `app/core/config.py`

**Type**: Pydantic Settings (BaseSettings)

**Environment Variables** (from `.env` file):

### Core Settings
- `PROJECT_NAME` (default: "Bash Bookkeeping API")
- `API_V1_PREFIX` (default: "/api/v1")

### Database
- `DATABASE_URL` (default: "postgresql+psycopg2://postgres:postgres@localhost:5432/bash")

### Redis & Celery
- `REDIS_URL` (default: "redis://localhost:6379/0")
- `CELERY_BROKER_URL` (default: "redis://localhost:6379/0")
- `CELERY_RESULT_BACKEND` (default: "redis://localhost:6379/0")

### Email Configuration
- `EMAIL_PROVIDER` ("imap" | "gmail")
- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, etc.
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`

### OCR Configuration
- `OCR_PROVIDER` ("tesseract" | "google_vision" | "aws_textract")
- `GOOGLE_CLOUD_CREDENTIALS_JSON`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`

### Storage (S3-Compatible)
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_NAME`, `S3_REGION`

### Security
- `VIRUS_SCANNER` ("clamav" | "none")
- `CLAMAV_HOST`, `CLAMAV_PORT`

### Other
- `OPENAI_API_KEY` (optional)
- `WEBSOCKET_ENABLED` (default: True)
- `CLASSIFICATION_CONFIDENCE_THRESHOLD` (default: 0.75)
- `AUTO_POST_MODE` (default: False)

**Usage**:
```python
from app.core.config import get_settings
settings = get_settings()
```

The `get_settings()` function uses `@lru_cache` for singleton pattern.

---

## 4. Database Configuration

**Location**: `app/db/session.py`

**SQLAlchemy Setup**:
- **Engine**: Created from `settings.database_url`
  - Pool settings: `pool_pre_ping=True`, `pool_size=10`, `max_overflow=20`
- **SessionLocal**: Session factory bound to engine
  - `autocommit=False`, `autoflush=False`

**Base Model**:
- **Location**: `app/models/base.py`
- **Class**: `Base(DeclarativeBase)` from SQLAlchemy 2.0
- **Mixin**: `TimestampMixin` for `created_at` and `updated_at` columns

**Database Dependency**:
- **Location**: `app/db/dependencies.py`
- Provides `get_db()` dependency for FastAPI route injection

**Current Models** (from `app/models/`):
- `bank_feed.py` - Bank transaction models
- `document.py` - Document models
- `email_document.py` - Email-related models (EmailMessage, EmailDocument, Tag, etc.)

---

## 5. Alembic Migrations

**Status**: ✅ **CONFIGURED**

**Configuration Files**:
- `alembic.ini` - Main Alembic configuration
- `alembic/env.py` - Environment setup

**Key Points**:
- Uses `app.core.config.get_settings()` to get `DATABASE_URL`
- Imports `Base` from `app.models.base`
- Imports all models from `app.models.email_document` (EmailMessage, EmailDocument, Tag, DocumentTag, AuditLog, Notification)
- Target metadata: `Base.metadata`

**Existing Migrations**:
- `alembic/versions/001_initial_email_ingestion.py`

**To Run Migrations**:
```bash
alembic upgrade head
alembic revision --autogenerate -m "description"
```

---

## 6. Celery Configuration

**Status**: ✅ **PRESENT** (with two instances)

### Instance 1: `app/celery_app.py`
- **Name**: "bookkeeping"
- **Includes**: `app.tasks.email_tasks`
- **Queues**: `email_processing`
- **Beat Schedule**:
  - `poll-emails-every-30-seconds` (every 30 seconds)
  - `cleanup-old-jobs-daily` (daily)
- **Task Routing**: Routes email tasks to `email_processing` queue
- **Rate Limiting**: 10 emails per minute for `process_email`

### Instance 2: `app/worker/celery_app.py`
- **Name**: "bookkeeping_worker"
- **Includes**: `app.worker.tasks`
- **Queues**: `emails`, `documents`, `polling`
- **Beat Schedule**:
  - `poll-emails-every-30-seconds` (uses `email_poll_interval_seconds` from settings)
  - `cleanup-old-documents-daily` (2 AM daily)
- **Task Routing**: Routes to different queues based on task type

**⚠️ NOTE**: There are two Celery app instances. This may be intentional for separation of concerns, but should be reviewed for potential consolidation.

**Configuration**:
- Both use `settings.celery_broker_url` and `settings.celery_result_backend`
- Both configured with JSON serialization
- Both use UTC timezone
- Result expiration: 1 hour (instance 1) / 24 hours (instance 2)

**To Run Celery Worker**:
```bash
# For instance 1 (email tasks)
celery -A app.celery_app worker --loglevel=info

# For instance 2 (worker tasks)
celery -A app.worker.celery_app worker --loglevel=info

# For Celery Beat (periodic tasks)
celery -A app.celery_app beat --loglevel=info
```

**Test Task**:
- `ping` task is available for testing Celery connectivity
- Call it with: `from app.celery_app import ping; ping.delay()`

---

## 7. Service Layer Architecture

**Location**: `app/services/`

Services are organized by domain:

- **Email**: `email/` - IMAP, Gmail adapters, factory pattern
- **OCR**: `ocr/` - Tesseract, Google Vision, AWS Textract providers
- **Storage**: `storage/` - S3-compatible storage service
- **Security**: `security/` - File validation, virus scanning
- **Classification**: `classification/` - Document classification
- **Bank Feed**: `bank_feed/` - CSV parsing, bank feed service
- **Notifications**: `notifications/` - Notification service, WebSocket manager
- **Extraction**: `extraction/` - Attachment and content extraction

---

## 8. Task Layer

**Location**: `app/tasks/` and `app/worker/tasks.py`

- `app/tasks/email_tasks.py` - Email processing tasks (used by `app/celery_app.py`)
- `app/worker/tasks.py` - Worker tasks (used by `app/worker/celery_app.py`)

---

## 9. Mock Mode

**Location**: `app/main.py`

The application supports a `MOCK_MODE` environment variable:
- If `MOCK_MODE=true`, database initialization is skipped
- This allows the API to start without a database connection for development/testing

**Current Default**: `MOCK_MODE=true` (from environment or default)

---

## 10. Key Dependencies

**Database**: PostgreSQL (via psycopg2-binary)
**ORM**: SQLAlchemy 2.0.34
**Migrations**: Alembic
**Task Queue**: Celery 5.4.0
**Cache/Queue**: Redis 5.0.1
**API Framework**: FastAPI 0.115.2
**ASGI Server**: Uvicorn 0.30.0

---

## 11. Important Notes

### ⚠️ DO NOT MODIFY:
1. Router prefixes in `app/api/v1/__init__.py`
2. Existing endpoint paths
3. Database models without creating migrations
4. Celery app configurations without understanding the impact

### ✅ Safe to Modify:
1. Environment variables in `.env`
2. Service implementations (as long as interfaces remain)
3. Adding new endpoints to existing routers
4. Adding new models (with migrations)

### 🔍 Areas for Review:
1. **Dual Celery Apps**: Consider consolidating or clearly documenting the separation
2. **CORS Configuration**: Currently allows all origins - should be restricted for production
3. **Model Imports in Alembic**: Only `email_document` models are imported - other models may need to be added

---

## 12. Development Workflow

1. **Start Database**: Ensure PostgreSQL is running
2. **Run Migrations**: `alembic upgrade head`
3. **Start Redis**: Required for Celery
4. **Start API**: `uvicorn app.main:app --reload --port 8000`
5. **Start Celery Worker**: `celery -A app.celery_app worker --loglevel=info`
6. **Start Celery Beat** (optional): `celery -A app.celery_app beat --loglevel=info`

---

## 13. API Documentation

Once the server is running:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/api/v1/openapi.json

---

## Summary

✅ **Config**: Centralized in `app/core/config.py` (Pydantic Settings)
✅ **Database**: Configured in `app/db/session.py` with SQLAlchemy
✅ **Base Model**: Defined in `app/models/base.py`
✅ **Alembic**: Fully configured and wired to models
✅ **Celery**: Present (two instances - may need review)
✅ **Routers**: All required routers exist and are registered

**Status**: Architecture is well-structured and ready for extension. All core pieces are in place.

