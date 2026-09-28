"""Cross-Camera Correlation and Vehicle Journey Reconstruction domain service.

Protocol Standards:
- docs/api-contract.md Section 7 (Vehicles & Journey).
- docs/final-architecture.md FLOW G (Vehicle -> Cross-Camera Journey) & FLOW H (Journey -> GIS).
- docs/gis-architecture.md Section 3.2 (Vehicle Route Rendering & Trajectory Reconstruction).
- Stage 12 Directive Sections 1-28.
- CORE PRINCIPLE: Observation != Route. No road network or path inference hallucination.
- STRICT CHRONOLOGY: Order strictly by observation timestamp (detected_at), with Detection.id tie-breaker.
- STRICT PROVENANCE: Preserves upstream video PTS, raw OCR text, is_demo indicators, and sensor IDs.
- PHYSICAL PLAUSIBILITY: Flags implied speeds > 180 km/h (or simultaneous displacement) as ANOMALY.
- UNKNOWN DATA: Missing location coordinates serialized as None (never 0,0).
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session, joinedload

from backend.app.models.intelligence import Detection
from backend.app.models.surveillance import Camera, Location
from backend.app.schemas.vehicle import (
    VehicleObservationItem,
    VehicleQueryWindow,
)
from backend.app.schemas.correlation import (
    CameraTransition,
    JourneyWaypoint,
    UnmappedWaypoint,
    VehicleJourneyResponse,
)
from backend.app.services.vehicle.service import VehicleService, ensure_utc
from backend.app.services.gis_service import GISService

logger = logging.getLogger("sentinel.correlation.service")

# Default physical plausibility threshold per docs/final-architecture.md line 327
DEFAULT_MAX_SPEED_THRESHOLD_KMH = 180.0


class CorrelationError(Exception):
    """Base exception for cross-camera correlation domain failures."""
    pass


class CorrelationValidationError(CorrelationError):
    """Raised when query parameters fail contract validation."""
    pass


class CorrelationService:
    """Domain service for cross-camera observation correlation, waypoints, and trajectory reconstruction."""

    @classmethod
    def correlate_vehicle_journey(
        cls,
        db: Session,
        plate_number: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        max_speed_threshold_kmh: float = DEFAULT_MAX_SPEED_THRESHOLD_KMH,
        limit: int = 500,
    ) -> VehicleJourneyResponse:
        """Reconstruct cross-camera vehicle observation sequence, camera transitions, and implied velocity.

        Strict Invariants (Stage 12 Directive):
        - Database query only: Evaluates persisted Detection records (never scans live streams).
        - Authoritative timestamp: Detection.detected_at derived strictly from video PTS.
        - Deterministic ordering: detected_at ASC, with Detection.id ASC tie-breaker.
        - Consecutive same-camera observations grouped into JourneyWaypoints.
        - Inter-camera transitions computed only when camera identifier changes.
        - Haversine great-circle distance calculated via existing GISService.
        - Implied transition speed evaluated; values exceeding threshold flagged as ANOMALY.
        - Missing coordinates remain None (never 0,0); unmapped cameras tracked in metadata.
        - Observation != Route: GeoJSON LineString connects camera coordinates only, NOT road paths.

        Returns:
            VehicleJourneyResponse with full correlation, waypoints, transitions, and GeoJSON.
        """
        if not plate_number or not plate_number.strip():
            raise CorrelationValidationError("Plate number must be non-empty.")

        if max_speed_threshold_kmh <= 0:
            raise CorrelationValidationError("max_speed_threshold_kmh must be greater than zero.")

        clean_plate = plate_number.strip().upper()

        # Validate time range
        if start_time and end_time:
            s_utc = ensure_utc(start_time)
            e_utc = ensure_utc(end_time)
            if s_utc > e_utc:
                raise CorrelationValidationError("start_time must be prior to end_time.")

        query_window = VehicleQueryWindow(
            start_time=ensure_utc(start_time),
            end_time=ensure_utc(end_time),
        )

        # 1. Query persisted detections with eager camera + location loading
        query = (
            db.query(Detection)
            .options(
                joinedload(Detection.camera).joinedload(Camera.location)
            )
            .filter(Detection.plate_number == clean_plate)
        )

        if start_time:
            query = query.filter(Detection.detected_at >= ensure_utc(start_time))
        if end_time:
            query = query.filter(Detection.detected_at <= ensure_utc(end_time))

        # Primary ordering: detected_at ASC; Secondary ordering: Detection.id ASC
        query = query.order_by(Detection.detected_at.asc(), Detection.id.asc())

        if limit:
            query = query.limit(min(limit, 1000))

        detections = query.all()

        # 2. Handle empty results truthfully without fabricating records
        if not detections:
            return VehicleJourneyResponse(
                plate_number=clean_plate,
                correlation_status="INSUFFICIENT_DATA",
                query_window=query_window,
                total_observations=0,
                total_waypoints=0,
                total_camera_transitions=0,
                total_distance_km=0.0,
                total_elapsed_seconds=0.0,
                is_demo=False,
                has_speed_anomaly=False,
                max_speed_threshold_kmh=max_speed_threshold_kmh,
                observations=[],
                waypoints=[],
                transitions=[],
                unmapped_waypoints=[],
                geojson_route=None,
            )

        # 3. Convert ORM records to canonical VehicleObservationItem
        observations: List[VehicleObservationItem] = [
            VehicleService.build_observation_item(det) for det in detections
        ]
        is_demo = any(o.is_demo for o in observations)

        # 4. Group consecutive detections at the same camera into JourneyWaypoints (Section 7)
        waypoints: List[JourneyWaypoint] = []
        current_wp: Optional[JourneyWaypoint] = None

        for obs in observations:
            if current_wp is None or current_wp.camera_id != obs.camera_id:
                current_wp = JourneyWaypoint(
                    sequence=len(waypoints) + 1,
                    camera_id=obs.camera_id,
                    camera_name=obs.camera_name,
                    location_id=obs.location_id,
                    location_name=obs.location_name,
                    latitude=obs.latitude,
                    longitude=obs.longitude,
                    city=obs.city,
                    state=obs.state,
                    first_detected_at=obs.detected_at,
                    last_detected_at=obs.detected_at,
                    observation_count=1,
                    detection_ids=[obs.detection_id],
                    is_demo=obs.is_demo,
                )
                waypoints.append(current_wp)
            else:
                current_wp.last_detected_at = obs.detected_at
                current_wp.observation_count += 1
                current_wp.detection_ids.append(obs.detection_id)
                if obs.is_demo:
                    current_wp.is_demo = True

        # 5. Identify unmapped waypoints (missing coordinates in camera registry)
        unmapped_map: Dict[uuid.UUID, UnmappedWaypoint] = {}
        for wp in waypoints:
            if wp.latitude is None or wp.longitude is None:
                if wp.camera_id not in unmapped_map:
                    unmapped_map[wp.camera_id] = UnmappedWaypoint(
                        camera_id=wp.camera_id,
                        camera_name=wp.camera_name,
                        location_id=wp.location_id,
                        location_name=wp.location_name,
                        observations_count=wp.observation_count,
                        reason="Coordinates missing in surveillance camera registry",
                    )
                else:
                    unmapped_map[wp.camera_id].observations_count += wp.observation_count
        unmapped_waypoints = list(unmapped_map.values())

        # 6. Compute inter-camera transitions (Section 7, 8, 9, 10, 11, 12)
        transitions: List[CameraTransition] = []
        for i in range(len(waypoints) - 1):
            wp_from = waypoints[i]
            wp_to = waypoints[i + 1]

            from_dt = ensure_utc(wp_from.last_detected_at)
            to_dt = ensure_utc(wp_to.first_detected_at)
            elapsed_sec = max(0.0, (to_dt - from_dt).total_seconds())

            # Haversine distance if both locations have valid coordinates (Section 8, 9)
            dist_km: Optional[float] = None
            if (
                wp_from.latitude is not None
                and wp_from.longitude is not None
                and wp_to.latitude is not None
                and wp_to.longitude is not None
            ):
                dist_km = round(
                    GISService.haversine_distance_km(
                        wp_from.latitude, wp_from.longitude,
                        wp_to.latitude, wp_to.longitude
                    ),
                    3
                )

            # Transition metrics & physical plausibility (Section 11, 12)
            implied_speed: Optional[float] = None
            plausibility: str = "PLAUSIBILITY_UNKNOWN"
            anomaly_msg: Optional[str] = None

            if dist_km is not None:
                if elapsed_sec > 0:
                    hours = elapsed_sec / 3600.0
                    speed = dist_km / hours
                    implied_speed = round(speed, 2)
                    if implied_speed > max_speed_threshold_kmh:
                        plausibility = "ANOMALY"
                        anomaly_msg = (
                            f"Implied transition speed {implied_speed:.1f} km/h exceeds "
                            f"maximum plausibility threshold ({max_speed_threshold_kmh:.1f} km/h)"
                        )
                    else:
                        plausibility = "PLAUSIBLE"
                else:
                    # elapsed_sec == 0 (simultaneous timestamps)
                    if dist_km > 0.05:  # Over 50m displacement in 0 seconds
                        plausibility = "ANOMALY"
                        anomaly_msg = (
                            f"Simultaneous detection across distinct camera locations "
                            f"(distance: {dist_km:.3f} km, elapsed: 0.0 s)"
                        )
                    else:
                        implied_speed = 0.0
                        plausibility = "PLAUSIBLE"
            else:
                plausibility = "PLAUSIBILITY_UNKNOWN"
                anomaly_msg = "Camera coordinates missing from surveillance camera registry"

            transitions.append(
                CameraTransition(
                    from_camera_id=wp_from.camera_id,
                    from_camera_name=wp_from.camera_name,
                    from_location_name=wp_from.location_name,
                    from_latitude=wp_from.latitude,
                    from_longitude=wp_from.longitude,
                    from_detected_at=wp_from.last_detected_at,
                    from_detection_id=wp_from.detection_ids[-1],
                    to_camera_id=wp_to.camera_id,
                    to_camera_name=wp_to.camera_name,
                    to_location_name=wp_to.location_name,
                    to_latitude=wp_to.latitude,
                    to_longitude=wp_to.longitude,
                    to_detected_at=wp_to.first_detected_at,
                    to_detection_id=wp_to.detection_ids[0],
                    elapsed_seconds=round(elapsed_sec, 2),
                    distance_km=dist_km,
                    implied_speed_kmh=implied_speed,
                    plausibility_status=plausibility,
                    anomaly_reason=anomaly_msg,
                )
            )

        # 7. Summary metrics & correlation classification (Section 14, 15)
        has_speed_anomaly = any(t.plausibility_status == "ANOMALY" for t in transitions)
        known_dists = [t.distance_km for t in transitions if t.distance_km is not None]
        total_dist = round(sum(known_dists), 3) if known_dists else 0.0

        first_time = ensure_utc(observations[0].detected_at)
        last_time = ensure_utc(observations[-1].detected_at)
        total_elapsed = round(max(0.0, (last_time - first_time).total_seconds()), 2)

        if len(transitions) == 0:
            correlation_status = "NO_TRANSITION"
        elif has_speed_anomaly or len(unmapped_waypoints) > 0:
            correlation_status = "PARTIALLY_CORRELATED"
        else:
            correlation_status = "CORRELATED"

        # 8. Generate GeoJSON Feature with LineString connecting mapped camera points (FLOW H)
        mapped_wps = [wp for wp in waypoints if wp.latitude is not None and wp.longitude is not None]
        geojson_route: Optional[Dict[str, Any]] = None

        if mapped_wps:
            wp_dicts = [
                {
                    "latitude": wp.latitude,
                    "longitude": wp.longitude,
                    "sequence": wp.sequence,
                    "timestamp": wp.first_detected_at.isoformat()
                }
                for wp in mapped_wps
            ]
            raw_feat = GISService.build_route_linestring(wp_dicts)
            geojson_route = {
                "type": "Feature",
                "geometry": raw_feat.get("geometry"),
                "properties": {
                    "plate_number": clean_plate,
                    "start_time": first_time.isoformat() if first_time else None,
                    "end_time": last_time.isoformat() if last_time else None,
                    "total_distance_km": total_dist,
                    "waypoints_count": len(waypoints),
                    "mapped_waypoints_count": len(mapped_wps),
                    "unmapped_waypoints_count": len(unmapped_waypoints),
                    "is_demo": is_demo,
                    "observation_type": "INTER_CAMERA_SEQUENCE",
                    "route_inference": "NONE_CAMERA_POINTS_ONLY",
                    "status": "VALID" if len(mapped_wps) >= 2 else "SINGLE_POINT",
                }
            }

        return VehicleJourneyResponse(
            plate_number=clean_plate,
            correlation_status=correlation_status,
            query_window=query_window,
            total_observations=len(observations),
            total_waypoints=len(waypoints),
            total_camera_transitions=len(transitions),
            total_distance_km=total_dist,
            total_elapsed_seconds=total_elapsed,
            is_demo=is_demo,
            has_speed_anomaly=has_speed_anomaly,
            max_speed_threshold_kmh=max_speed_threshold_kmh,
            observations=observations,
            waypoints=waypoints,
            transitions=transitions,
            unmapped_waypoints=unmapped_waypoints,
            geojson_route=geojson_route,
        )
