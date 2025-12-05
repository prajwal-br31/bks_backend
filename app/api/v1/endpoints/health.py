from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.core.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    clamav: str
    s3: str
    ocr: str


class ServiceStatus(BaseModel):
    name: str
    status: str
    message: str = ""


@router.get("", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """Check health of all services."""
    settings = get_settings()
    
    # Database check
    try:
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    # Redis check
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.ping()
        redis_status = "healthy"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    # ClamAV check
    if settings.virus_scanner == "clamav":
        try:
            from app.services.security import VirusScanner
            scanner = VirusScanner()
            is_healthy = await scanner.health_check()
            clamav_status = "healthy" if is_healthy else "unhealthy"
        except Exception as e:
            clamav_status = f"unhealthy: {str(e)}"
    else:
        clamav_status = "disabled"
    
    # S3 check
    try:
        from app.services.storage import S3StorageService
        storage = S3StorageService()
        is_healthy = await storage.health_check()
        s3_status = "healthy" if is_healthy else "unhealthy"
    except Exception as e:
        s3_status = f"unhealthy: {str(e)}"
    
    # OCR check
    try:
        from app.services.ocr import get_ocr_provider
        ocr = get_ocr_provider()
        is_healthy = await ocr.health_check()
        ocr_status = "healthy" if is_healthy else "unhealthy"
    except Exception as e:
        ocr_status = f"unhealthy: {str(e)}"
    
    # Overall status
    all_healthy = all(
        status == "healthy" or status == "disabled"
        for status in [db_status, redis_status, clamav_status, s3_status, ocr_status]
    )
    
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        database=db_status,
        redis=redis_status,
        clamav=clamav_status,
        s3=s3_status,
        ocr=ocr_status,
    )


@router.get("/ready", response_model=dict)
def readiness_check(db: Session = Depends(get_db)):
    """Kubernetes readiness probe."""
    try:
        db.execute("SELECT 1")
        return {"status": "ready"}
    except Exception:
        return {"status": "not_ready"}


@router.get("/live", response_model=dict)
def liveness_check():
    """Kubernetes liveness probe."""
    return {"status": "alive"}

