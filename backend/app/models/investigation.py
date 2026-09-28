"""Investigation case files, attached events, and forensic evidence models."""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Text, Integer, BigInteger, DateTime, ForeignKey,
    Uuid, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Investigation(Base):
    """Police case file tracking suspect vehicles or incident timelines."""

    __tablename__ = "investigations"
    __table_args__ = (
        Index("idx_investigations_case", "case_number"),
        Index("idx_investigations_plate", "target_plate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_plate: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False)  # OPEN, IN_PROGRESS, CLOSED, ARCHIVED
    lead_detective_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    events: Mapped[List["InvestigationEvent"]] = relationship(
        "InvestigationEvent",
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="InvestigationEvent.sequence_order"
    )
    evidence_items: Mapped[List["Evidence"]] = relationship(
        "Evidence",
        back_populates="investigation",
        cascade="all, delete-orphan"
    )


class InvestigationEvent(Base):
    """Specific detections or alerts tagged and attached to an investigation case."""

    __tablename__ = "investigation_events"
    __table_args__ = (
        Index("idx_inv_events_timeline", "investigation_id", "sequence_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False
    )
    detection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("detections.id", ondelete="SET NULL"),
        nullable=True
    )
    alert_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("alerts.id", ondelete="SET NULL"),
        nullable=True
    )
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    investigation: Mapped["Investigation"] = relationship("Investigation", back_populates="events")


class Evidence(Base):
    """Digital evidence dossiers and exported archives with cryptographic verification."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("idx_evidence_inv", "investigation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)  # PDF_DOSSIER, CROP_ARCHIVE, EXPORT_JSON
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # Proof of integrity
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    investigation: Mapped["Investigation"] = relationship("Investigation", back_populates="evidence_items")
