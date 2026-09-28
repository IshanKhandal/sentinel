"""GIS REST API endpoints.

Protocol Standards:
- Section 8 & Section 11 of Phase 4 Directive & docs/api-contract.md.
- Outputs WGS 84 GeoJSON FeatureCollections.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.gis import (
    GeoJSONFeatureCollection,
    NearbyCameraItem,
    RoutePreviewRequest,
)
from backend.app.services.gis_service import GISService, CoordinateValidationError
from backend.app.models.surveillance import Camera, Location

router = APIRouter(prefix="/gis", tags=["GIS & Geospatial"])


@router.get("/cameras.geojson", response_model=GeoJSONFeatureCollection)
def get_cameras_geojson(
    status_filter: Optional[str] = Query(None, alias="status"),
    stream_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Export all registered camera markers formatted as standard GeoJSON FeatureCollection.

    Only mapped cameras with valid WGS 84 coordinates are included in features.
    """
    geojson_payload = GISService.get_cameras_geojson(
        db=db,
        status=status_filter,
        stream_type=stream_type
    )
    return geojson_payload


@router.get("/nearby-cameras", response_model=List[NearbyCameraItem])
def find_nearby_cameras(
    latitude: float = Query(..., ge=-90.0, le=90.0, description="Center latitude (-90 to 90)"),
    longitude: float = Query(..., ge=-180.0, le=180.0, description="Center longitude (-180 to 180)"),
    radius_km: float = Query(5.0, gt=0.0, le=50.0, description="Search radius in km (max 50.0)"),
    db: Session = Depends(get_db)
):
    """Find cameras within a radial distance from a given geographic point using Haversine calculation."""
    try:
        results = GISService.find_nearby_cameras(
            db=db,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km
        )
    except (CoordinateValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc)
        ) from exc

    return results


@router.get("/unmapped")
def get_unmapped_cameras(db: Session = Depends(get_db)):
    """Retrieve list of registered surveillance cameras that do not have verified coordinates."""
    cameras = db.query(Camera).outerjoin(Location).all()
    unmapped = []
    for cam in cameras:
        loc = cam.location
        if not loc or loc.latitude is None or loc.longitude is None:
            unmapped.append({
                "camera_id": str(cam.id),
                "camera_name": cam.name,
                "status": cam.status,
                "stream_type": cam.stream_type,
                "reason": "Missing location coordinates"
            })
            continue
        try:
            GISService.validate_coordinates(float(loc.latitude), float(loc.longitude))
        except CoordinateValidationError as exc:
            unmapped.append({
                "camera_id": str(cam.id),
                "camera_name": cam.name,
                "status": cam.status,
                "stream_type": cam.stream_type,
                "reason": f"Invalid coordinates: {exc}"
            })

    return {
        "unmapped_count": len(unmapped),
        "unmapped_cameras": unmapped
    }


@router.post("/route-preview")
def preview_route(
    request: RoutePreviewRequest
):
    """Construct and preview a GeoJSON LineString from an ordered sequence of verified waypoints."""
    waypoints_dict = [wp.model_dump() for wp in request.waypoints]
    try:
        linestring_feature = GISService.build_route_linestring(waypoints_dict)
    except CoordinateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc)
        ) from exc

    return linestring_feature
