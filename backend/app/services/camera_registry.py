"""Camera Registry domain service managing camera synchronization and lifecycle.

Protocol Standard: Sections 5, 6, 7 of Phase 3 Directive.
- Preserves historical records on catalogue camera disappearance (marks UNAVAILABLE, never deletes).
- Maintains strict distinction between CATALOGUE LIVE vs APPLICATION CONNECTION VERIFIED.
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.app.models.access import Department
from backend.app.models.surveillance import Location, Camera, CameraHealth
from backend.app.services.catalogue_client import SentinelCatalogueCamera


class CameraRegistryService:
    """Service managing camera persistence, queries, and catalogue synchronization."""

    @staticmethod
    def get_or_create_default_department(db: Session) -> Department:
        """Ensure a default surveillance department exists for discovered cameras."""
        dept = db.query(Department).filter_by(code="GJ-POLICE-HQ").first()
        if not dept:
            dept = Department(
                name="Gujarat Police Surveillance Command",
                code="GJ-POLICE-HQ"
            )
            db.add(dept)
            db.commit()
            db.refresh(dept)
        return dept

    @staticmethod
    def get_or_create_location_for_catalogue_camera(
        db: Session,
        cam_meta: SentinelCatalogueCamera
    ) -> Location:
        """Find or create a location entity matching catalogue geographic data."""
        # Use coordinates if available, otherwise fallback to unmapped landmark
        lat = cam_meta.latitude if cam_meta.latitude is not None else 23.0225
        lon = cam_meta.longitude if cam_meta.longitude is not None else 72.5714
        loc_name = cam_meta.name or f"Camera Site {cam_meta.id}"

        # Match existing location by coordinates or name
        loc = db.query(Location).filter(
            Location.latitude == lat,
            Location.longitude == lon
        ).first()

        if not loc:
            loc = Location(
                name=loc_name,
                latitude=lat,
                longitude=lon,
                city="Gujarat Surveillance Zone",
                state="Gujarat"
            )
            db.add(loc)
            db.commit()
            db.refresh(loc)
        return loc

    @classmethod
    def sync_catalogue(
        cls,
        db: Session,
        catalogue_cameras: List[SentinelCatalogueCamera],
        department_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Synchronize external Sentinel catalogue records with local database registry."""
        if not department_id:
            default_dept = cls.get_or_create_default_department(db)
            department_id = default_dept.id

        created_count = 0
        updated_count = 0
        now = datetime.now(timezone.utc)

        # Track which cameras are present in current sync cycle
        catalogue_ids_present = set()

        for cat_cam in catalogue_cameras:
            catalogue_ids_present.add(cat_cam.id)

            # Standardized internal camera name incorporating authoritative Sentinel ID
            camera_name = cat_cam.name or f"Sentinel-Cam-{cat_cam.id}"
            rtsp_url = cat_cam.rtsp_url or f"rtsp://unconfigured/stream/{cat_cam.id}"

            # Query existing camera by name or rtsp_url
            camera = db.query(Camera).filter(
                (Camera.name == camera_name) | (Camera.rtsp_url == rtsp_url)
            ).first()

            # Resolution & FPS parsing
            resolution = cat_cam.resolution or "1920x1080"
            fps = int(cat_cam.fps) if cat_cam.fps and cat_cam.fps > 0 else 10

            if camera:
                # Update existing camera
                camera.rtsp_url = rtsp_url
                camera.resolution = resolution
                camera.fps_target = fps
                camera.last_heartbeat_at = now

                # Section 7: Catalogue Live vs Application Connection Verified
                # If catalogue explicitly reports camera is NOT live:
                if cat_cam.live is False:
                    camera.status = "OFFLINE"
                # If catalogue reports live=True, do NOT blindly display LIVE until our app decodes it.
                elif camera.status not in ("LIVE", "DEMO"):
                    camera.status = "OFFLINE"

                updated_count += 1
            else:
                # Create newly discovered camera
                location = cls.get_or_create_location_for_catalogue_camera(db, cat_cam)
                camera = Camera(
                    department_id=department_id,
                    location_id=location.id,
                    name=camera_name,
                    rtsp_url=rtsp_url,
                    stream_type="LIVE",
                    status="OFFLINE",  # Pending actual stream connection verification
                    resolution=resolution,
                    fps_target=fps,
                    last_heartbeat_at=now
                )
                db.add(camera)
                created_count += 1

        # Section 6: Mark cameras missing from latest catalogue as UNAVAILABLE (never delete!)
        marked_unavailable = 0
        all_live_cameras = db.query(Camera).filter(Camera.stream_type == "LIVE").all()
        for cam in all_live_cameras:
            # Check if camera was derived from catalogue
            if cam.name.startswith("Sentinel-Cam-"):
                cam_cat_id = cam.name.replace("Sentinel-Cam-", "")
                if cam_cat_id not in catalogue_ids_present and cam.status != "UNAVAILABLE":
                    cam.status = "UNAVAILABLE"
                    marked_unavailable += 1

        db.commit()

        return {
            "total_catalogue": len(catalogue_cameras),
            "created": created_count,
            "updated": updated_count,
            "marked_unavailable": marked_unavailable,
            "timestamp": now.isoformat()
        }

    @staticmethod
    def list_cameras(
        db: Session,
        status: Optional[str] = None,
        stream_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[Camera]:
        """Query cameras with optional status and stream_type filters."""
        query = db.query(Camera)
        if status:
            query = query.filter(Camera.status == status)
        if stream_type:
            query = query.filter(Camera.stream_type == stream_type)
        return query.offset(skip).limit(limit).all()

    @staticmethod
    def get_camera(db: Session, camera_id: uuid.UUID) -> Optional[Camera]:
        """Fetch camera by unique UUID."""
        return db.query(Camera).filter(Camera.id == camera_id).first()

    @staticmethod
    def record_camera_health(
        db: Session,
        camera_id: uuid.UUID,
        is_reachable: bool,
        latency_ms: Optional[int] = None,
        fps_measured: Optional[float] = None,
        dropped_frames: int = 0
    ) -> CameraHealth:
        """Record health check telemetry for a surveillance camera."""
        health = CameraHealth(
            camera_id=camera_id,
            is_reachable=is_reachable,
            latency_ms=latency_ms,
            fps_measured=fps_measured,
            dropped_frames_count=dropped_frames
        )
        db.add(health)
        
        # Update camera status based on health
        cam = db.query(Camera).filter(Camera.id == camera_id).first()
        if cam:
            cam.last_heartbeat_at = datetime.now(timezone.utc)
            if not is_reachable and cam.status == "LIVE":
                cam.status = "OFFLINE"
        
        db.commit()
        db.refresh(health)
        return health
