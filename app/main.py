from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.v1 import api_router
from app.models import Base
from app.db.session import engine

settings = get_settings()

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.project_name,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    docs_url=f"{settings.api_v1_prefix}/docs",
    redoc_url=f"{settings.api_v1_prefix}/redoc",
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
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "name": settings.project_name,
        "docs": f"{settings.api_v1_prefix}/docs",
    }


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Ensure system tags exist
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
