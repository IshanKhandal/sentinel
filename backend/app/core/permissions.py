"""Role-Based Access Control (RBAC) permission definitions and seeding.

Protocol Standards:
- docs/security-architecture.md Section 2 (RBAC Matrix)
- docs/database-design.md Domain 1 (roles, permissions, role_permissions)
"""

from typing import Dict, List, Set
from sqlalchemy.orm import Session
from backend.app.models.access import Role, Permission, RolePermission


# ============================================================================
# Canonical Permission Codes
# ============================================================================

PERMISSION_CAMERAS_READ = "cameras:read"
PERMISSION_CAMERAS_WRITE = "cameras:write"
PERMISSION_STREAMS_MANAGE = "streams:manage"
PERMISSION_DETECTIONS_READ = "detections:read"
PERMISSION_WATCHLISTS_READ = "watchlists:read"
PERMISSION_WATCHLISTS_WRITE = "watchlists:write"
PERMISSION_WATCHLISTS_DELETE = "watchlists:delete"
PERMISSION_ALERTS_READ = "alerts:read"
PERMISSION_ALERTS_MANAGE = "alerts:manage"
PERMISSION_INVESTIGATIONS_READ = "investigations:read"
PERMISSION_INVESTIGATIONS_WRITE = "investigations:write"
PERMISSION_EVIDENCE_READ = "evidence:read"
PERMISSION_EVIDENCE_WRITE = "evidence:write"
PERMISSION_EVIDENCE_EXPORT = "evidence:export"
PERMISSION_USERS_MANAGE = "users:manage"
PERMISSION_AUDIT_READ = "audit:read"
PERMISSION_REALTIME_CONNECT = "realtime:connect"

ALL_PERMISSIONS: List[Dict[str, str]] = [
    {"code": PERMISSION_CAMERAS_READ, "description": "View live cameras, topology, and map status"},
    {"code": PERMISSION_CAMERAS_WRITE, "description": "Register and update surveillance camera parameters"},
    {"code": PERMISSION_STREAMS_MANAGE, "description": "Start and stop camera video decoding workers"},
    {"code": PERMISSION_DETECTIONS_READ, "description": "Query historical vehicle and plate detections"},
    {"code": PERMISSION_WATCHLISTS_READ, "description": "Read watchlist configurations and perform plate matches"},
    {"code": PERMISSION_WATCHLISTS_WRITE, "description": "Create watchlists and enroll plate hotlist records"},
    {"code": PERMISSION_WATCHLISTS_DELETE, "description": "Deactivate or delete watchlist entries"},
    {"code": PERMISSION_ALERTS_READ, "description": "View generated real-time surveillance alerts"},
    {"code": PERMISSION_ALERTS_MANAGE, "description": "Acknowledge, dismiss, or resolve security alerts"},
    {"code": PERMISSION_INVESTIGATIONS_READ, "description": "Read investigation case files and timeline graphs"},
    {"code": PERMISSION_INVESTIGATIONS_WRITE, "description": "Create cases, attach events, and update status"},
    {"code": PERMISSION_EVIDENCE_READ, "description": "Inspect registered digital evidence metadata and hashes"},
    {"code": PERMISSION_EVIDENCE_WRITE, "description": "Register digital forensic evidence items"},
    {"code": PERMISSION_EVIDENCE_EXPORT, "description": "Export packaged cryptographic case dossiers"},
    {"code": PERMISSION_USERS_MANAGE, "description": "Provision police operator accounts and clearance levels"},
    {"code": PERMISSION_AUDIT_READ, "description": "Inspect immutable system audit logs"},
    {"code": PERMISSION_REALTIME_CONNECT, "description": "Connect to real-time WebSocket event streams"},
]


# ============================================================================
# Canonical Roles and RBAC Matrix
# ============================================================================

ROLE_SUPER_ADMIN = "SuperAdmin"
ROLE_INVESTIGATOR = "Investigator"
ROLE_OPERATOR = "Operator"
ROLE_AUDITOR = "Auditor"

ROLE_PERMISSIONS_MATRIX: Dict[str, Set[str]] = {
    ROLE_SUPER_ADMIN: {p["code"] for p in ALL_PERMISSIONS},
    ROLE_INVESTIGATOR: {
        PERMISSION_CAMERAS_READ,
        PERMISSION_CAMERAS_WRITE,
        PERMISSION_STREAMS_MANAGE,
        PERMISSION_DETECTIONS_READ,
        PERMISSION_WATCHLISTS_READ,
        PERMISSION_WATCHLISTS_WRITE,
        PERMISSION_WATCHLISTS_DELETE,
        PERMISSION_ALERTS_READ,
        PERMISSION_ALERTS_MANAGE,
        PERMISSION_INVESTIGATIONS_READ,
        PERMISSION_INVESTIGATIONS_WRITE,
        PERMISSION_EVIDENCE_READ,
        PERMISSION_EVIDENCE_WRITE,
        PERMISSION_EVIDENCE_EXPORT,
        PERMISSION_REALTIME_CONNECT,
    },
    ROLE_OPERATOR: {
        PERMISSION_CAMERAS_READ,
        PERMISSION_STREAMS_MANAGE,
        PERMISSION_DETECTIONS_READ,
        PERMISSION_WATCHLISTS_READ,
        PERMISSION_ALERTS_READ,
        PERMISSION_ALERTS_MANAGE,
        PERMISSION_REALTIME_CONNECT,
    },
    ROLE_AUDITOR: {
        PERMISSION_CAMERAS_READ,
        PERMISSION_DETECTIONS_READ,
        PERMISSION_WATCHLISTS_READ,
        PERMISSION_ALERTS_READ,
        PERMISSION_INVESTIGATIONS_READ,
        PERMISSION_EVIDENCE_READ,
        PERMISSION_AUDIT_READ,
        PERMISSION_REALTIME_CONNECT,
    },
}


def seed_roles_and_permissions(db: Session) -> None:
    """Seed or reconcile standard police roles and permissions in the database.
    
    Safe and idempotent: creates missing records without duplicating.
    """
    # 1. Seed Permissions
    existing_perms = {p.code: p for p in db.query(Permission).all()}
    for perm_data in ALL_PERMISSIONS:
        if perm_data["code"] not in existing_perms:
            perm = Permission(code=perm_data["code"], description=perm_data["description"])
            db.add(perm)
            existing_perms[perm_data["code"]] = perm
    db.flush()

    # 2. Seed Roles
    existing_roles = {r.name: r for r in db.query(Role).all()}
    role_descriptions = {
        ROLE_SUPER_ADMIN: "Full administrative authority over users, surveillance, and configuration",
        ROLE_INVESTIGATOR: "Police detective with full investigation, watchlist, and evidence privileges",
        ROLE_OPERATOR: "CCTV control room operator monitoring streams, map, and managing alerts",
        ROLE_AUDITOR: "Oversight officer with read-only access to operations and full audit inspection",
    }
    for role_name, description in role_descriptions.items():
        if role_name not in existing_roles:
            role = Role(name=role_name, description=description)
            db.add(role)
            existing_roles[role_name] = role
    db.flush()

    # 3. Seed Role-Permissions
    existing_rp = {
        (rp.role_id, rp.permission_id) for rp in db.query(RolePermission).all()
    }
    for role_name, perm_codes in ROLE_PERMISSIONS_MATRIX.items():
        role = existing_roles[role_name]
        for code in perm_codes:
            perm = existing_perms[code]
            if (role.id, perm.id) not in existing_rp:
                rp = RolePermission(role_id=role.id, permission_id=perm.id)
                db.add(rp)
                existing_rp.add((role.id, perm.id))
    db.commit()
