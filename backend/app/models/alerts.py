"""Threat detection and incident alert models."""

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Text, DateTime, ForeignKey,
    Uuid, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Alert(Base):
    """Incident alert raised upon real-time watchlist match."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_status_created", "status", "created_at"),
        Index("idx_alerts_plate", "plate_number"),
        Index("idx_alerts_camera", "camera_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    detection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("detections.id", ondelete="RESTRICT"),
        nullable=False
    )
    watchlist_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("watchlist_entries.id", ondelete="RESTRICT"),
        nullable=False
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cameras.id", ondelete="RESTRICT"),
        nullable=False
    )
    plate_number: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    status: Mapped[str] = mapped_column(String(30), default="NEW", nullable=False)  # NEW, ACKNOWLEDGED, RESOLVED, DISMISSED
    acknowledged_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    detection: Mapped["Detection"] = relationship("Detection", back_populates="alerts")
    watchlist_entry: Mapped["WatchlistEntry"] = relationship("WatchlistEntry", back_populates="alerts")
