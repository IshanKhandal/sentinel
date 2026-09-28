"""Central model registry exporting all database entities."""

from backend.app.db.base import Base

from backend.app.models.access import (
    Department,
    Role,
    Permission,
    RolePermission,
    User,
)
from backend.app.models.surveillance import (
    Location,
    Camera,
    CameraHealth,
    SystemEvent,
)
from backend.app.models.intelligence import (
    Vehicle,
    Detection,
    Track,
)
from backend.app.models.watchlists import (
    Watchlist,
    WatchlistEntry,
)
from backend.app.models.alerts import (
    Alert,
)
from backend.app.models.investigation import (
    Investigation,
    InvestigationEvent,
    Evidence,
)
from backend.app.models.audit import (
    AuditLog,
)

__all__ = [
    "Base",
    # Access
    "Department",
    "Role",
    "Permission",
    "RolePermission",
    "User",
    # Surveillance
    "Location",
    "Camera",
    "CameraHealth",
    "SystemEvent",
    # Intelligence
    "Vehicle",
    "Detection",
    "Track",
    # Watchlists
    "Watchlist",
    "WatchlistEntry",
    # Alerts
    "Alert",
    # Investigation
    "Investigation",
    "InvestigationEvent",
    "Evidence",
    # Audit
    "AuditLog",
]
