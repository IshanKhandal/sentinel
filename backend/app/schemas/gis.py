"""Pydantic schemas for GIS endpoints and geospatial payloads."""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

from backend.app.schemas.camera import CameraResponse


class NearbyCameraItem(BaseModel):
    """Camera entity returned from a radial spatial query with distance."""

    camera: CameraResponse
    distance_km: float = Field(..., description="Great-circle distance in kilometers")
    distance_meters: float = Field(..., description="Great-circle distance in meters")


class GeoJSONFeatureCollection(BaseModel):
    """Standard RFC 7946 GeoJSON FeatureCollection container."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[Dict[str, Any]]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WaypointInput(BaseModel):
    """Geographic point waypoint for route construction."""

    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS 84 Latitude")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS 84 Longitude")
    sequence: Optional[int] = Field(default=None, description="Deterministic sequence ordering")
    timestamp: Optional[str] = Field(default=None, description="Observation timestamp")
    label: Optional[str] = Field(default=None, description="Optional waypoint landmark label")


class RoutePreviewRequest(BaseModel):
    """Request payload for route line preview."""

    waypoints: List[WaypointInput]
