"""Main FastAPI application entry point for Sentinel."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from backend.app.core.config import settings
from backend.app.api.v1.cameras import router as cameras_router
from backend.app.api.v1.gis import router as gis_router
from backend.app.api.v1.streams import router as streams_router
from backend.app.api.v1.detection import router as detection_router
from backend.app.api.v1.anpr import router as anpr_router
from backend.app.api.v1.detections import router as detections_router
from backend.app.api.v1.watchlists import router as watchlists_router
from backend.app.services.streaming.manager import stream_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager ensuring clean background worker teardown."""
    yield
    stream_manager.shutdown_all()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Sentinel Surveillance & Automated Video Analytics Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Mount API v1 Routers
app.include_router(cameras_router, prefix="/api/v1")
app.include_router(gis_router, prefix="/api/v1")
app.include_router(streams_router, prefix="/api/v1")
app.include_router(detection_router, prefix="/api/v1")
app.include_router(anpr_router, prefix="/api/v1")
app.include_router(detections_router, prefix="/api/v1")
app.include_router(watchlists_router, prefix="/api/v1")




@app.get("/health", tags=["System Health"])
def health_check():
    """System health check endpoint."""
    return {
        "status": "HEALTHY",
        "app_version": settings.VERSION,
        "operation_mode": settings.SENTINEL_OPERATION_MODE,
        "stream_host_configured": bool(settings.SENTINEL_STREAM_HOST),
    }


@app.get("/gis-preview", response_class=HTMLResponse, tags=["GIS & Geospatial"])
def gis_preview():
    """Serve minimal Leaflet GIS presentation component for topology verification."""
    html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "gis_preview.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>GIS preview file not found.</h1>", status_code=404)
