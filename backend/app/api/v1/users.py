"""Police personnel and user account management REST API endpoints.

Protocol Standards:
- docs/api-contract.md Section 2 (Users & Personnel)
- docs/security-architecture.md Section 2 (RBAC: SuperAdmin role required)
- Password hashes are strictly excluded from API responses
"""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.core.auth import get_current_user, require_role, require_permission
from backend.app.core.permissions import ROLE_SUPER_ADMIN, PERMISSION_USERS_MANAGE
from backend.app.models.access import User
from backend.app.schemas.auth import (
    UserCreate,
    UserUpdate,
    UserRead,
    UserListResponse,
)
from backend.app.services.auth import (
    UserService,
    UserNotFoundError,
    UserConflictError,
    UserValidationError,
)

router = APIRouter(prefix="/users", tags=["Users & Personnel"])


def _serialize_user(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        badge_number=user.badge_number,
        full_name=user.full_name,
        email=user.email,
        is_active=user.is_active,
        role_id=user.role.id if user.role else user.role_id,
        role_name=user.role.name if user.role else "UNKNOWN",
        department_id=user.department.id if user.department else user.department_id,
        department_name=user.department.name if user.department else "General Administration",
        department_code=user.department.code if user.department else "GEN",
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get("", response_model=UserListResponse, summary="List registered police operators")
def list_users(
    skip: int = Query(0, ge=0, description="Offset pagination"),
    limit: int = Query(20, ge=1, le=100, description="Page limit (max 100)"),
    role: Optional[str] = Query(None, description="Optional role filter"),
    current_user: User = Depends(require_permission(PERMISSION_USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> UserListResponse:
    """List registered users and clearance levels (SuperAdmin clearance required)."""
    items, total = UserService.list_users(db=db, skip=skip, limit=limit, role_name=role)
    return UserListResponse(
        total=total,
        items=[_serialize_user(u) for u in items],
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Provision new user")
def create_user(
    payload: UserCreate,
    request: Request,
    current_user: User = Depends(require_role([ROLE_SUPER_ADMIN])),
    db: Session = Depends(get_db),
) -> UserRead:
    """Provision a new police operator or investigator account (SuperAdmin only)."""
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    try:
        new_user = UserService.create_user(
            db=db,
            data=payload,
            current_user=current_user,
            ip_address=client_ip,
        )
        return _serialize_user(new_user)
    except UserConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except UserValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{user_id}", response_model=UserRead, summary="Get user details by ID")
def get_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRead:
    """Retrieve specific user profile. Requires SuperAdmin role or accessing own profile."""
    is_self = current_user.id == user_id
    is_admin = current_user.role and current_user.role.name == ROLE_SUPER_ADMIN
    if not (is_self or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted: can only access own profile or require SuperAdmin clearance.",
        )

    user = UserService.get_user_by_id(db=db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID '{user_id}' not found.",
        )
    return _serialize_user(user)


@router.patch("/{user_id}", response_model=UserRead, summary="Update user profile")
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
    current_user: User = Depends(require_role([ROLE_SUPER_ADMIN])),
    db: Session = Depends(get_db),
) -> UserRead:
    """Modify user credentials, clearance role, or active status (SuperAdmin only)."""
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    try:
        updated = UserService.update_user(
            db=db,
            user_id=user_id,
            data=payload,
            current_user=current_user,
            ip_address=client_ip,
        )
        return _serialize_user(updated)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except UserConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except UserValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
