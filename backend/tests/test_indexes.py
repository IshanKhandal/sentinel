"""Automated tests verifying critical performance indexes exist in the schema."""

from sqlalchemy import inspect
from backend.app.models import Base


def test_critical_indexes_in_metadata():
    """Verify that all critical indexes required by the architecture exist in SQLAlchemy models."""
    tables = Base.metadata.tables
    all_indexes = {}
    for table_name, table in tables.items():
        for idx in table.indexes:
            all_indexes[idx.name] = [col.name for col in idx.columns]

    # Required critical indexes from frozen architecture
    required_indexes = {
        "idx_detections_plate_time": ["plate_number", "detected_at"],
        "idx_detections_cam_time": ["camera_id", "detected_at"],
        "idx_watchlist_entries_plate_active": ["plate_number", "is_active"],
        "idx_locations_lat_lon": ["latitude", "longitude"],
        "idx_detections_detected_at": ["detected_at"],
        "idx_audit_logs_time": ["timestamp"],
    }

    for index_name, expected_columns in required_indexes.items():
        assert index_name in all_indexes, f"Critical index {index_name} is missing from Base.metadata"
        actual_columns = all_indexes[index_name]
        assert actual_columns == expected_columns, (
            f"Index {index_name} columns mismatch: expected {expected_columns}, got {actual_columns}"
        )


def test_indexes_in_sqlite_engine(test_engine):
    """Verify that SQLite engine physically created the required indexes."""
    inspector = inspect(test_engine)
    
    # Check detections table indexes
    detection_indexes = {idx["name"] for idx in inspector.get_indexes("detections")}
    assert "idx_detections_plate_time" in detection_indexes
    assert "idx_detections_cam_time" in detection_indexes
    assert "idx_detections_detected_at" in detection_indexes

    # Check watchlist_entries table indexes
    wl_indexes = {idx["name"] for idx in inspector.get_indexes("watchlist_entries")}
    assert "idx_watchlist_entries_plate_active" in wl_indexes

    # Check locations table indexes
    loc_indexes = {idx["name"] for idx in inspector.get_indexes("locations")}
    assert "idx_locations_lat_lon" in loc_indexes

    # Check audit_logs table indexes
    audit_indexes = {idx["name"] for idx in inspector.get_indexes("audit_logs")}
    assert "idx_audit_logs_time" in audit_indexes
