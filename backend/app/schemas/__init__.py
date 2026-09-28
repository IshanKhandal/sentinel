"""Pydantic API request and response validation schemas."""

from backend.app.schemas.watchlist import (
    WatchlistCategory,
    WatchlistSeverity,
    WatchlistMatchMethod,
    WatchlistCreate,
    WatchlistRead,
    WatchlistUpdate,
    WatchlistEntryCreate,
    WatchlistEntryRead,
    WatchlistEntryUpdate,
    WatchlistMatchResult,
    WatchlistMatchResponse,
    PlateMatchRequest,
)

from backend.app.schemas.alert import (
    AlertStatus,
    AlertSeverity,
    AlertRead,
    AlertListResponse,
    AlertAcknowledgeRequest,
    AlertStatusUpdateRequest,
    AlertEngineResult,
)

from backend.app.schemas.vehicle import (
    VehicleProfileRead,
    VehicleObservationItem,
    VehicleHistoryResponse,
    VehicleQueryWindow,
)

from backend.app.schemas.investigation import (
    InvestigationCreate,
    InvestigationUpdate,
    InvestigationRead,
    InvestigationListResponse,
    InvestigationEventCreate,
    InvestigationEventRead,
    EvidenceCreate,
    EvidenceRead,
    AttachVehicleHistoryRequest,
    AttachAlertRequest,
)

__all__ = [
    "WatchlistCategory",
    "WatchlistSeverity",
    "WatchlistMatchMethod",
    "WatchlistCreate",
    "WatchlistRead",
    "WatchlistUpdate",
    "WatchlistEntryCreate",
    "WatchlistEntryRead",
    "WatchlistEntryUpdate",
    "WatchlistMatchResult",
    "WatchlistMatchResponse",
    "PlateMatchRequest",
    "AlertStatus",
    "AlertSeverity",
    "AlertRead",
    "AlertListResponse",
    "AlertAcknowledgeRequest",
    "AlertStatusUpdateRequest",
    "AlertEngineResult",
    "VehicleProfileRead",
    "VehicleObservationItem",
    "VehicleHistoryResponse",
    "VehicleQueryWindow",
    "InvestigationCreate",
    "InvestigationUpdate",
    "InvestigationRead",
    "InvestigationListResponse",
    "InvestigationEventCreate",
    "InvestigationEventRead",
    "EvidenceCreate",
    "EvidenceRead",
    "AttachVehicleHistoryRequest",
    "AttachAlertRequest",
]
