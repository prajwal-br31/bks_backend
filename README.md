# Bash Bookkeeping API

A FastAPI-powered backend for the Bash Bookkeeping application featuring email ingestion, document processing, bank feed management, and real-time notifications.

## Features

- 🔐 **Email Auto-Ingestion** - IMAP/Gmail API integration for automatic document import
- 📄 **Document Processing** - OCR, PDF parsing, Excel/CSV handling
- 🏦 **Bank Feed** - CSV/Excel upload, transaction matching, reconciliation
- 🔔 **Real-time Notifications** - WebSocket-based notification system
- 🦠 **Security** - ClamAV virus scanning, file validation
- ⚡ **Background Tasks** - Celery + Redis for async processing

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL + SQLAlchemy (Azure PostgreSQL / Azure SQL)
- **Task Queue**: Celery + Redis (Azure Cache for Redis)
- **Storage**: Azure Blob Storage (or S3-compatible)
- **OCR**: Tesseract / Google Vision / Azure AI Document Intelligence

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Docker (optional)

### 1. Clone & Setup

```bash
git clone https://github.com/YOUR_USERNAME/bookkeeping-api.git
cd bookkeeping-api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp env.example .env
# Edit .env with your configuration
```

**Minimum required variables:**
```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/bash
REDIS_URL=redis://localhost:6379/0

# Azure Blob Storage
STORAGE_PROVIDER=azure_blob
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER_NAME=bookkeeping-documents
```

### 3. Start Infrastructure

```bash
# Using Docker
docker-compose up -d postgres redis

# Or use your existing PostgreSQL and Redis instances
```

### 4. Run the API

```bash
# Development
uvicorn app.main:app --reload --port 8000

# Production
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### 5. Start Celery Worker (for background tasks)

```bash
# Development
celery -A app.celery_app worker --loglevel=info --pool=solo

# Production
celery -A app.celery_app worker --loglevel=info --concurrency=4
```

## API Documentation

Once running, access the interactive API docs:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### Bank Feed

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/bank-feed/upload` | Upload CSV/Excel bank statement |
| GET | `/api/v1/bank-feed/transactions` | List transactions with filters |
| POST | `/api/v1/bank-feed/match` | Match transaction to AP/AR/Expense |
| GET | `/api/v1/bank-feed/summary` | Dashboard summary statistics |
| POST | `/api/v1/bank-feed/bulk-action` | Bulk update transactions |

### Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/documents` | List all documents |
| GET | `/api/v1/documents/{id}` | Get document details |
| PUT | `/api/v1/documents/{id}/classify` | Update classification |

### Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/notifications` | List notifications |
| PUT | `/api/v1/notifications/{id}/read` | Mark as read |
| WS | `/api/v1/ws/{client_id}` | WebSocket connection |

## Docker Deployment

```dockerfile
# Build
docker build -t bookkeeping-api .

# Run
docker run -p 8000:8000 --env-file .env bookkeeping-api
```

## Environment Variables

See `env.example` for all available configuration options.

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=app --cov-report=html
```

## License

MIT
