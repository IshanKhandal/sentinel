"""Audit logging and chain-of-custody compliance models."""

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Text, DateTime, ForeignKey,
    Uuid, BigInteger, Integer, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class AuditLog(Base):
    """Immutable, append-only operational audit log."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_user", "user_id", "timestamp"),
        Index("idx_audit_logs_action", "action", "timestamp"),
        Index("idx_audit_logs_time", "timestamp"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    badge_number: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # WATCHLIST_CREATE, ALERT_ACK, SEARCH_PLATE
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ALERT, WATCHLIST, INVESTIGATION
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    payload_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
