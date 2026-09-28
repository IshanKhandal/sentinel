"""Automated unit tests for CameraRegistryService synchronization and lifecycle."""

from backend.app.models.surveillance import Camera
from backend.app.services.catalogue_client import SentinelCatalogueCamera
from backend.app.services.camera_registry import CameraRegistryService


def test_sync_catalogue_creates_new_cameras(db_session):
    """Verify that catalogue items are ingested into the Camera table with trustworthy statuses."""
    catalogue_items = [
        SentinelCatalogueCamera(
            id="node_001",
            name="Junction SG Highway",
            rtsp="rtsp://host:8554/stream/node_001",
            codec="H.264",
            live=True,
            resolution="1920x1080",
            fps=25.0,
            lat=23.0450,
            lng=72.5200,
        ),
        SentinelCatalogueCamera(
            id="node_002",
            name="Ashram Road Point",
            rtsp="rtsp://host:8554/stream/node_002",
            codec="H.265",
            live=False,
            resolution="3840x2160",
            fps=30.0,
            lat=23.0305,
            lng=72.5714,
        ),
    ]

    result = CameraRegistryService.sync_catalogue(db=db_session, catalogue_cameras=catalogue_items)
    assert result["created"] == 2
    assert result["updated"] == 0
    assert result["marked_unavailable"] == 0

    # Query created cameras
    cams = db_session.query(Camera).all()
    assert len(cams) == 2

    c1 = db_session.query(Camera).filter(Camera.rtsp_url.contains("node_001")).first()
    assert c1 is not None
    assert c1.name == "Junction SG Highway"
    assert c1.resolution == "1920x1080"
    assert c1.fps_target == 25
    # Critical verification of Rule 31 & Section 7:
    # Catalogue reported live=True, but status MUST NOT be 'LIVE' until our app decodes it.
    assert c1.status == "OFFLINE"
    assert c1.stream_type == "LIVE"

    c2 = db_session.query(Camera).filter(Camera.rtsp_url.contains("node_002")).first()
    assert c2 is not None
    assert c2.resolution == "3840x2160"
    assert c2.status == "OFFLINE"


def test_sync_catalogue_updates_existing_camera(db_session):
    """Verify that re-syncing updates existing camera metadata without duplicating."""
    initial_items = [
        SentinelCatalogueCamera(
            id="node_001",
            name="Old Name",
            rtsp="rtsp://host:8554/stream/node_001",
            resolution="1280x720",
            fps=15.0,
            live=True,
        )
    ]
    CameraRegistryService.sync_catalogue(db=db_session, catalogue_cameras=initial_items)
    assert db_session.query(Camera).count() == 1

    updated_items = [
        SentinelCatalogueCamera(
            id="node_001",
            name="New Name",
            rtsp="rtsp://host:8554/stream/node_001",
            resolution="1920x1080",
            fps=25.0,
            live=True,
        )
    ]
    result = CameraRegistryService.sync_catalogue(db=db_session, catalogue_cameras=updated_items)
    assert result["created"] == 0
    assert result["updated"] == 1
    assert db_session.query(Camera).count() == 1

    cam = db_session.query(Camera).first()
    assert cam.resolution == "1920x1080"
    assert cam.fps_target == 25


def test_sync_catalogue_marks_missing_camera_unavailable(db_session):
    """Verify that cameras removed from subsequent catalogue are marked UNAVAILABLE, NOT deleted."""
    initial_items = [
        SentinelCatalogueCamera(id="cam_A", rtsp="rtsp://host:8554/stream/cam_A"),
        SentinelCatalogueCamera(id="cam_B", rtsp="rtsp://host:8554/stream/cam_B"),
    ]
    CameraRegistryService.sync_catalogue(db=db_session, catalogue_cameras=initial_items)
    assert db_session.query(Camera).count() == 2

    # Subsequent sync returns ONLY cam_A (cam_B has disappeared from catalogue)
    next_cycle = [
        SentinelCatalogueCamera(id="cam_A", rtsp="rtsp://host:8554/stream/cam_A")
    ]
    result = CameraRegistryService.sync_catalogue(db=db_session, catalogue_cameras=next_cycle)
    assert result["marked_unavailable"] == 1

    # Both cameras must still exist in DB to protect historical observations
    assert db_session.query(Camera).count() == 2

    cam_b = db_session.query(Camera).filter(Camera.rtsp_url.contains("cam_B")).first()
    assert cam_b.status == "UNAVAILABLE"


def test_camera_health_recording(db_session):
    """Verify that recording camera telemetry stores telemetry and adjusts status."""
    items = [
        SentinelCatalogueCamera(id="cam_health_test", rtsp="rtsp://host:8554/stream/cam_health_test")
    ]
    CameraRegistryService.sync_catalogue(db=db_session, catalogue_cameras=items)
    cam = db_session.query(Camera).first()

    # Record successful health check
    health_ok = CameraRegistryService.record_camera_health(
        db=db_session,
        camera_id=cam.id,
        is_reachable=True,
        latency_ms=22,
        fps_measured=10.0
    )
    assert health_ok.is_reachable is True
    assert health_ok.latency_ms == 22

    # Record unreachable health check
    health_fail = CameraRegistryService.record_camera_health(
        db=db_session,
        camera_id=cam.id,
        is_reachable=False
    )
    assert health_fail.is_reachable is False
    assert cam.status == "OFFLINE"
