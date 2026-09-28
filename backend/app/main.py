"""Main FastAPI application entry point for Sentinel."""

from fastapi import FastAPI
from backend.app.core.config import settings
from backend.app.api.v1.cameras import router as cameras_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Sentinel Surveillance & Automated Video Analytics Platform",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Mount API v1 Routers
app.include_router(cameras_router, prefix="/api/v1")


@app.get("/health", tags=["System Health"])
def health_check():
    """System health check endpoint."""
    return {
        "status": "HEALTHY",
        "app_version": settings.VERSION,
        "operation_mode": settings.SENTINEL_OPERATION_MODE,
        "stream_host_configured": bool(settings.SENTINEL_STREAM_HOST),
    }
