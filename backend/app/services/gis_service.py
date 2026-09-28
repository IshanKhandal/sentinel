"""Geospatial Information System (GIS) service for Sentinel.

Protocol Standards:
- WGS 84 / EPSG:4326 standard coordinates.
- GeoJSON coordinate ordering: [longitude, latitude] (RFC 7946).
- Strict non-hallucination: Never invent coordinates (Rule 37 / Rule 38).
- Haversine great-circle distance calculation.
"""

import math
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session

from backend.app.models.surveillance import Location, Camera


class CoordinateValidationError(ValueError):
    """Raised when coordinates violate WGS 84 boundary rules or are malformed."""
    pass


class GISService:
    """Core geospatial operations, coordinate validation, and GeoJSON generation."""

    EARTH_RADIUS_KM: float = 6371.0088

    @classmethod
    def validate_coordinates(cls, latitude: float, longitude: float) -> Tuple[float, float]:
        """Validate WGS 84 coordinates strictly.

        Enforces:
        - -90.0 <= latitude <= 90.0
        - -180.0 <= longitude <= 180.0
        - Rejects NaN, Infinity, and malformed numeric values.
        """
        if latitude is None or longitude is None:
            raise CoordinateValidationError("Latitude and longitude must not be null.")

        try:
            lat = float(latitude)
            lon = float(longitude)
        except (ValueError, TypeError) as exc:
            raise CoordinateValidationError(f"Coordinates must be valid floating point numbers: {exc}") from exc

        if math.isnan(lat) or math.isinf(lat):
            raise CoordinateValidationError(f"Latitude cannot be NaN or Infinite: {lat}")
        if math.isnan(lon) or math.isinf(lon):
            raise CoordinateValidationError(f"Longitude cannot be NaN or Infinite: {lon}")

        if not (-90.0 <= lat <= 90.0):
            raise CoordinateValidationError(f"Latitude out of bounds [-90, 90]: {lat}")
        if not (-180.0 <= lon <= 180.0):
            raise CoordinateValidationError(f"Longitude out of bounds [-180, 180]: {lon}")

        return lat, lon

    @classmethod
    def haversine_distance_km(cls, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points on the WGS 84 sphere in kilometers.

        Uses the numerically stable Haversine formula.
        """
        cls.validate_coordinates(lat1, lon1)
        cls.validate_coordinates(lat2, lon2)

        # Convert decimal degrees to radians
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        # Numerical guard against precision errors exceeding 1.0
        c = 2.0 * math.atan2(math.sqrt(min(1.0, a)), math.sqrt(max(0.0, 1.0 - a)))

        return cls.EARTH_RADIUS_KM * c

    @classmethod
    def get_cameras_geojson(
        cls,
        db: Session,
        status: Optional[str] = None,
        stream_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate GeoJSON FeatureCollection of mapped cameras.

        Strict Invariants:
        - Coordinates ordered as [longitude, latitude] per RFC 7946.
        - Only cameras with verified, valid coordinates are included in features.
        - Unmapped cameras are NOT placed at (0, 0) or center of Gujarat.
        - Sensitive credentials (e.g. RTSP passwords) are stripped from properties.
        """
        query = db.query(Camera).join(Location)
        if status:
            query = query.filter(Camera.status == status)
        if stream_type:
            query = query.filter(Camera.stream_type == stream_type)

        cameras = query.all()

        features: List[Dict[str, Any]] = []
        unmapped_camera_ids: List[str] = []

        for cam in cameras:
            loc = cam.location
            if not loc or loc.latitude is None or loc.longitude is None:
                unmapped_camera_ids.append(str(cam.id))
                continue

            try:
                lat, lon = cls.validate_coordinates(float(loc.latitude), float(loc.longitude))
            except CoordinateValidationError:
                unmapped_camera_ids.append(str(cam.id))
                continue

            # Sanitized properties (no secrets)
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    # GeoJSON standard: [longitude, latitude]
                    "coordinates": [lon, lat]
                },
                "properties": {
                    "camera_id": str(cam.id),
                    "camera_name": cam.name,
                    "status": cam.status,
                    "stream_type": cam.stream_type,
                    "direction_heading": cam.direction_heading,
                    "resolution": cam.resolution,
                    "fps_target": cam.fps_target,
                    "location_id": str(loc.id),
                    "location_name": loc.name,
                    "city": loc.city,
                    "state": loc.state,
                    "mapped_status": "MAPPED"
                }
            }
            features.append(feature)

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "total_mapped": len(features),
                "total_unmapped": len(unmapped_camera_ids),
                "unmapped_camera_ids": unmapped_camera_ids,
                "crs": "urn:ogc:def:crs:OGC:1.3:CRS84"
            }
        }

    @classmethod
    def find_nearby_cameras(
        cls,
        db: Session,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0
    ) -> List[Dict[str, Any]]:
        """Find cameras within a radial distance from a given WGS 84 point.

        Unmapped cameras are excluded from spatial distance queries.
        """
        lat, lon = cls.validate_coordinates(latitude, longitude)
        if radius_km <= 0:
            raise ValueError(f"Radius must be strictly greater than 0: {radius_km}")
        if radius_km > 50.0:
            raise ValueError(f"Radius exceeds maximum allowed limit of 50.0 km: {radius_km}")

        # Fetch cameras with locations
        cameras = db.query(Camera).join(Location).all()

        nearby_results: List[Dict[str, Any]] = []

        for cam in cameras:
            loc = cam.location
            if not loc or loc.latitude is None or loc.longitude is None:
                continue

            try:
                c_lat, c_lon = cls.validate_coordinates(float(loc.latitude), float(loc.longitude))
            except CoordinateValidationError:
                continue

            distance_km = cls.haversine_distance_km(lat, lon, c_lat, c_lon)
            if distance_km <= radius_km:
                nearby_results.append({
                    "camera": cam,
                    "distance_km": round(distance_km, 3),
                    "distance_meters": round(distance_km * 1000.0, 1)
                })

        # Sort ascending by distance
        nearby_results.sort(key=lambda item: item["distance_km"])
        return nearby_results

    @classmethod
    def build_route_linestring(
        cls,
        waypoints: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Construct a GeoJSON LineString from an ordered sequence of verified geographic waypoints.

        Input: List of dicts containing:
        - 'latitude': float
        - 'longitude': float
        - 'sequence': Optional[int]
        - 'timestamp': Optional[datetime / ISO str]
        - 'label': Optional[str]
        """
        if not waypoints:
            return {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": []
                },
                "properties": {
                    "points_count": 0,
                    "total_distance_km": 0.0,
                    "status": "EMPTY"
                }
            }

        # Deterministic sorting if sequence or timestamp is provided
        def sort_key(wp: Dict[str, Any]):
            seq = wp.get("sequence")
            ts = wp.get("timestamp")
            if seq is not None:
                return (0, seq)
            if ts is not None:
                return (1, str(ts))
            return (2, 0)

        sorted_wps = sorted(waypoints, key=sort_key)

        coordinates: List[List[float]] = []
        total_distance = 0.0
        prev_pt: Optional[Tuple[float, float]] = None

        for wp in sorted_wps:
            lat = wp.get("latitude")
            lon = wp.get("longitude")
            if lat is None or lon is None:
                continue

            v_lat, v_lon = cls.validate_coordinates(float(lat), float(lon))
            coordinates.append([v_lon, v_lat])  # GeoJSON: [lon, lat]

            if prev_pt is not None:
                total_distance += cls.haversine_distance_km(prev_pt[0], prev_pt[1], v_lat, v_lon)
            prev_pt = (v_lat, v_lon)

        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates
            },
            "properties": {
                "points_count": len(coordinates),
                "total_distance_km": round(total_distance, 3),
                "status": "VALID" if len(coordinates) >= 2 else "INSUFFICIENT_POINTS"
            }
        }
