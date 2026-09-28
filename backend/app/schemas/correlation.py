"""Pydantic schemas for Cross-Camera Correlation and Vehicle Journey Reconstruction.

Protocol Standards:
- docs/api-contract.md Section 7 (Vehicles & Journey).
- docs/final-architecture.md FLOW G (Vehicle -> Cross-Camera Journey) & FLOW H (Journey -> GIS).
- docs/gis-architecture.md Section 3.2 (Vehicle Route Rendering & Trajectory Reconstruction).
- Stage 12 Directive: Deterministic chronological correlation of persisted observations.
- CORE PRINCIPLE: Observation != Route. No road network or path inference hallucination.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.vehicle import VehicleObservationItem, VehicleQueryWindow


class CameraTransition(BaseModel):
    """Correlated transition between consecutive camera locations."""
    model_config = ConfigDict(from_attributes=True)

    from_camera_id: uuid.UUID = Field(..., description="Originating camera UUID")
    from_camera_name: Optional[str] = Field(default=None, description="Originating camera designation")
    from_location_name: Optional[str] = Field(default=None, description="Originating junction/location name")
    from_latitude: Optional[float] = Field(default=None, description="Originating latitude coordinate (None if unmapped)")
    from_longitude: Optional[float] = Field(default=None, description="Originating longitude coordinate (None if unmapped)")
    from_detected_at: datetime = Field(..., description="Timestamp of last observation at originating camera")
    from_detection_id: uuid.UUID = Field(..., description="Detection observation UUID at departure")

    to_camera_id: uuid.UUID = Field(..., description="Destination camera UUID")
    to_camera_name: Optional[str] = Field(default=None, description="Destination camera designation")
    to_location_name: Optional[str] = Field(default=None, description="Destination junction/location name")
    to_latitude: Optional[float] = Field(default=None, description="Destination latitude coordinate (None if unmapped)")
    to_longitude: Optional[float] = Field(default=None, description="Destination longitude coordinate (None if unmapped)")
    to_detected_at: datetime = Field(..., description="Timestamp of first observation at destination camera")
    to_detection_id: uuid.UUID = Field(..., description="Detection observation UUID at arrival")

    elapsed_seconds: float = Field(..., ge=0.0, description="Elapsed duration between observations in seconds")
    distance_km: Optional[float] = Field(default=None, description="Haversine great-circle distance in kilometers (None if unmapped)")
    implied_speed_kmh: Optional[float] = Field(default=None, description="Calculated distance / time metric in km/h (None if distance/time unavailable)")
    plausibility_status: str = Field(
        ...,
        description="Transition plausibility: 'PLAUSIBLE', 'ANOMALY' (>180 km/h or simultaneous displacement), or 'PLAUSIBILITY_UNKNOWN'"
    )
    anomaly_reason: Optional[str] = Field(default=None, description="Explanatory text if transition is flagged as ANOMALY")


class JourneyWaypoint(BaseModel):
    """Aggregated camera site stay representing one or more consecutive detections."""
    model_config = ConfigDict(from_attributes=True)

    sequence: int = Field(..., ge=1, description="1-based chronological stop sequence index")
    camera_id: uuid.UUID = Field(..., description="Surveillance camera UUID")
    camera_name: Optional[str] = Field(default=None, description="Camera designation")
    location_id: Optional[uuid.UUID] = Field(default=None, description="Associated location identifier")
    location_name: Optional[str] = Field(default=None, description="Location/Junction name")
    latitude: Optional[float] = Field(default=None, description="Latitude coordinate (None if unmapped)")
    longitude: Optional[float] = Field(default=None, description="Longitude coordinate (None if unmapped)")
    city: Optional[str] = Field(default=None, description="City municipality")
    state: Optional[str] = Field(default=None, description="State jurisdiction")
    first_detected_at: datetime = Field(..., description="First arrival observation timestamp at this camera")
    last_detected_at: datetime = Field(..., description="Last departure observation timestamp at this camera")
    observation_count: int = Field(default=1, ge=1, description="Total consecutive detections at this camera stop")
    detection_ids: List[uuid.UUID] = Field(default_factory=list, description="IDs of observations at this stop")
    is_demo: bool = Field(default=False, description="True if any observation at this camera stop was synthetic/demo")


class UnmappedWaypoint(BaseModel):
    """Metadata record for a camera waypoint lacking geographic coordinates in the registry."""
    model_config = ConfigDict(from_attributes=True)

    camera_id: uuid.UUID = Field(..., description="Surveillance camera UUID")
    camera_name: Optional[str] = Field(default=None, description="Camera designation")
    location_id: Optional[uuid.UUID] = Field(default=None, description="Associated location UUID if exists")
    location_name: Optional[str] = Field(default=None, description="Location/Junction name")
    observations_count: int = Field(default=1, ge=1, description="Count of observations recorded at this unmapped camera")
    reason: str = Field(default="Coordinates missing in surveillance camera registry", description="Exclusion explanation")


class VehicleJourneyResponse(BaseModel):
    """Full cross-camera correlation and journey trajectory response."""
    model_config = ConfigDict(from_attributes=True)

    plate_number: str = Field(..., description="Normalized vehicle registration plate searched")
    correlation_status: str = Field(
        ...,
        description="Correlation classification: 'CORRELATED', 'PARTIALLY_CORRELATED', 'NO_TRANSITION', or 'INSUFFICIENT_DATA'"
    )
    query_window: VehicleQueryWindow = Field(default_factory=VehicleQueryWindow, description="Applied query temporal window")
    total_observations: int = Field(default=0, ge=0, description="Total individual detection events correlated")
    total_waypoints: int = Field(default=0, ge=0, description="Total distinct camera stop sites")
    total_camera_transitions: int = Field(default=0, ge=0, description="Total inter-camera transitions evaluated")
    total_distance_km: Optional[float] = Field(default=None, description="Sum of verified great-circle transition distances in km")
    total_elapsed_seconds: Optional[float] = Field(default=None, description="Duration from first observation to latest observation in seconds")
    is_demo: bool = Field(default=False, description="True if any observation in journey originated from DEMO fixture")
    has_speed_anomaly: bool = Field(default=False, description="True if any transition implied speed exceeded plausibility threshold")
    max_speed_threshold_kmh: float = Field(default=180.0, description="Configured physical plausibility speed threshold in km/h")

    observations: List[VehicleObservationItem] = Field(default_factory=list, description="Chronological sequence of individual observations")
    waypoints: List[JourneyWaypoint] = Field(default_factory=list, description="Chronological sequence of camera stops")
    transitions: List[CameraTransition] = Field(default_factory=list, description="Inter-camera transitions between consecutive sites")
    unmapped_waypoints: List[UnmappedWaypoint] = Field(default_factory=list, description="Cameras excluded from polyline due to missing coordinates")
    geojson_route: Optional[Dict[str, Any]] = Field(default=None, description="GeoJSON Feature with LineString connecting mapped camera coordinates")
