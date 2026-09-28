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
from backend.app.api.v1.alerts import router as alerts_router
from backend.app.api.v1.vehicles import router as vehicles_router
from backend.app.api.v1.investigations import router as investigations_router
from backend.app.api.v1.ws import router as ws_router
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.users import router as users_router
from backend.app.api.v1.audit import router as audit_router
from backend.app.api.v1.system import router as system_router
from backend.app.services.streaming.manager import stream_manager
from backend.app.services.realtime.manager import websocket_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager ensuring clean background worker teardown."""
    websocket_manager.start_reaper()
    yield
    await websocket_manager.shutdown_all()
    stream_manager.shutdown_all()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Sentinel Surveillance & Automated Video Analytics Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Attach defensive security headers to all HTTP responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Mount API v1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(cameras_router, prefix="/api/v1")
app.include_router(gis_router, prefix="/api/v1")
app.include_router(streams_router, prefix="/api/v1")
app.include_router(detection_router, prefix="/api/v1")
app.include_router(anpr_router, prefix="/api/v1")
app.include_router(detections_router, prefix="/api/v1")
app.include_router(watchlists_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(vehicles_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1")
app.include_router(ws_router, prefix="/api/v1")
app.include_router(system_router, prefix="/api/v1")




from fastapi.staticfiles import StaticFiles

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/health", tags=["System Health"])
def health_check():
    """System health check endpoint."""
    return {
        "status": "HEALTHY",
        "app_version": settings.VERSION,
        "operation_mode": settings.SENTINEL_OPERATION_MODE,
        "stream_host_configured": bool(settings.SENTINEL_STREAM_HOST),
    }


@app.get("/", response_class=HTMLResponse, tags=["Tactical UI"])
def serve_ui():
    """Serve the Sentinel Gujarat Tactical Command Center Single Page Application."""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Sentinel UI not found.</h1>", status_code=404)


@app.get("/gis-preview", response_class=HTMLResponse, tags=["GIS & Geospatial"])
def gis_preview():
    """Serve minimal Leaflet GIS presentation component for topology verification."""
    html_path = os.path.join(frontend_dir, "gis_preview.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>GIS preview file not found.</h1>", status_code=404)
