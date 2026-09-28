"""Surveillance topology, camera registry, and health telemetry models."""

import uuid
from datetime import datetime
from typing import Optional, List, Any
from sqlalchemy import (
    String, Text, Boolean, Integer, Float, Numeric, DateTime, ForeignKey,
    Uuid, BigInteger, JSON, CheckConstraint, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Location(Base):
    """Geographic landmarks, junctions, and camera installation sites."""

    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint("latitude >= -90.0 AND latitude <= 90.0", name="chk_location_latitude"),
        CheckConstraint("longitude >= -180.0 AND longitude <= 180.0", name="chk_location_longitude"),
        Index("idx_locations_lat_lon", "latitude", "longitude"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), default="Gujarat", nullable=False)

    cameras: Mapped[List["Camera"]] = relationship("Camera", back_populates="location")


class Camera(Base):
    """Surveillance camera device and stream ingestion configuration."""

    __tablename__ = "cameras"
    __table_args__ = (
        Index("idx_cameras_status", "status"),
        Index("idx_cameras_location", "location_id"),
        Index("idx_cameras_stream_type", "stream_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String(500), nullable=False)
    stream_type: Mapped[str] = mapped_column(String(20), nullable=False)  # LIVE or DEMO
    direction_heading: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-360 degrees
    fps_target: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    resolution: Mapped[str] = mapped_column(String(20), default="1920x1080", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OFFLINE", nullable=False)  # LIVE, DEMO, OFFLINE, UNAVAILABLE
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    location: Mapped["Location"] = relationship("Location", back_populates="cameras")
    department: Mapped["Department"] = relationship("Department", back_populates="cameras")
    health_records: Mapped[List["CameraHealth"]] = relationship("CameraHealth", back_populates="camera", cascade="all, delete-orphan")
    detections: Mapped[List["Detection"]] = relationship("Detection", back_populates="camera")


class CameraHealth(Base):
    """Historical telemetry for stream uptime and frame drops."""

    __tablename__ = "camera_health"
    __table_args__ = (
        Index("idx_camera_health_cam_time", "camera_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps_measured: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dropped_frames_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="health_records")


class SystemEvent(Base):
    """System-level operational and failure events."""

    __tablename__ = "system_events"
    __table_args__ = (
        Index("idx_system_events_created", "created_at"),
        Index("idx_system_events_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True
    )
    subsystem: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., INGESTION, INFERENCE, DATABASE
    severity: Mapped[str] = mapped_column(String(20), nullable=False)   # INFO, WARNING, ERROR, CRITICAL
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
