"""Vehicle intelligence, detections, and continuous track models."""

import uuid
from datetime import datetime
from typing import Optional, List, Any
from sqlalchemy import (
    String, Boolean, Integer, Float, DateTime, ForeignKey,
    Uuid, JSON, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Vehicle(Base):
    """Canonical profile for recognized vehicle registration numbers."""

    __tablename__ = "vehicles"
    __table_args__ = (
        Index("idx_vehicles_plate", "plate_number"),
        Index("idx_vehicles_last_seen", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    vehicle_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # CAR, TRUCK, BUS, MOTORCYCLE
    color: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_detections_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    detections: Mapped[List["Detection"]] = relationship("Detection", back_populates="vehicle")


class Detection(Base):
    """Transactional record of a single frame vehicle and plate detection."""

    __tablename__ = "detections"
    __table_args__ = (
        Index("idx_detections_plate_time", "plate_number", "detected_at"),
        Index("idx_detections_cam_time", "camera_id", "detected_at"),
        Index("idx_detections_detected_at", "detected_at"),
        Index("idx_detections_vehicle_id", "vehicle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False
    )
    vehicle_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="SET NULL"),
        nullable=True
    )
    plate_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    vehicle_type: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_vehicle: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_plate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_vehicle: Mapped[Any] = mapped_column(JSON, nullable=False)  # [x1, y1, x2, y2]
    bbox_plate: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # [x1, y1, x2, y2]
    snapshot_path: Mapped[str] = mapped_column(String(500), nullable=False)
    plate_crop_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="detections")
    vehicle: Mapped[Optional["Vehicle"]] = relationship("Vehicle", back_populates="detections")
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="detection")


class Track(Base):
    """Intra-camera continuous tracklet connecting sequential frames."""

    __tablename__ = "tracks"
    __table_args__ = (
        Index("idx_tracks_camera", "camera_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False
    )
    detection_id_start: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("detections.id", ondelete="CASCADE"),
        nullable=False
    )
    detection_id_end: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("detections.id", ondelete="CASCADE"),
        nullable=False
    )
    track_tracker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
