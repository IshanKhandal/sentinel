"""FastAPI authentication and authorization dependencies.

Protocol Standards:
- docs/security-architecture.md Sections 1 & 2 (JWT & RBAC)
- docs/engineering-rules.md Rule 23, 24, 25 (Defense-in-depth, least privilege)
"""

import uuid
from typing import Callable, List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload

from backend.app.db.session import get_db
from backend.app.models.access import User, Role
from backend.app.core.security import (
    decode_access_token,
    TokenExpiredError,
    TokenInvalidError,
)
from backend.app.core.permissions import ROLE_SUPER_ADMIN

# Bearer security scheme with auto_error=False to allow clean custom 401 handling
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate Bearer token and retrieve active authenticated police user."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except TokenInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject identity.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject identifier format.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = (
        db.query(User)
        .options(
            joinedload(User.role).joinedload(Role.permissions),
            joinedload(User.department),
        )
        .filter(User.id == user_uuid)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency verifying that the authenticated user is currently active."""
    return current_user


def require_role(allowed_roles: List[str]) -> Callable[[User], User]:
    """Dependency factory checking that the current user has one of the allowed roles."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if not current_user.role or current_user.role.name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required role: {', '.join(allowed_roles)}",
            )
        return current_user
    return role_checker


def require_permission(permission_code: str) -> Callable[[User], User]:
    """Dependency factory checking that the current user possesses a specific fine-grained permission."""
    def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        # SuperAdmin has universal clearance
        if current_user.role and current_user.role.name == ROLE_SUPER_ADMIN:
            return current_user

        user_permissions = set()
        if current_user.role and current_user.role.permissions:
            user_permissions = {p.code for p in current_user.role.permissions}

        if permission_code not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Missing permission: '{permission_code}'.",
            )
        return current_user
    return permission_checker
