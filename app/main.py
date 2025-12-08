import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

# Check if running in mock mode (no database required)
MOCK_MODE = False

settings = get_settings()

# Only initialize database if not in mock mode
if not MOCK_MODE:
    from app.models import Base
    from app.db.session import engine
    Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.project_name,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url="/docs",  # Simpler docs URL
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
from app.api.v1 import api_router
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "name": settings.project_name,
        "docs": "/docs",
        "mock_mode": MOCK_MODE,
    }


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "mock_mode": MOCK_MODE}


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    import logging
    logging.basicConfig(level=logging.INFO)
    logging.info(f"Starting in {'MOCK' if MOCK_MODE else 'PRODUCTION'} mode")
    
    if not MOCK_MODE:
        # Ensure system tags exist (only when database is available)
        from app.db.session import SessionLocal
        from app.models import Tag
        
        db = SessionLocal()
        try:
            system_tags = ["invoice", "receipt", "needs_review", "high_value", "urgent"]
            for tag_name in system_tags:
                existing = db.query(Tag).filter(Tag.name == tag_name).first()
                if not existing:
                    tag = Tag(name=tag_name, is_system=True)
                    db.add(tag)
            db.commit()
        finally:
            db.close()


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    pass
