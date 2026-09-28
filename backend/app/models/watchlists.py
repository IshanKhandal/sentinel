"""Watchlists and target hotlist entry models."""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Text, Boolean, DateTime, ForeignKey,
    Uuid, UniqueConstraint, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Watchlist(Base):
    """Categorized police hotlists (e.g., Stolen Vehicles, Suspects)."""

    __tablename__ = "watchlists"
    __table_args__ = (
        Index("idx_watchlists_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # STOLEN, WANTED, SUSPECT, EXPIRED
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    entries: Mapped[List["WatchlistEntry"]] = relationship("WatchlistEntry", back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistEntry(Base):
    """Individual vehicle registration enrolled onto a watchlist."""

    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "plate_number", name="uq_watchlist_entry_plate"),
        Index("idx_watchlist_entries_plate_active", "plate_number", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False
    )
    plate_number: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_make_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fir_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Police FIR reference
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    watchlist: Mapped["Watchlist"] = relationship("Watchlist", back_populates="entries")
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="watchlist_entry")
