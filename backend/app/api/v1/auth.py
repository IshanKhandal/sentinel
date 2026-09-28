"""Authentication REST API endpoints.

Protocol Standards:
- docs/api-contract.md Section 1 (Authentication)
- docs/security-architecture.md Section 1 & 2
- RFC 7807 compliant error responses
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.core.auth import get_current_user
from backend.app.models.access import User
from backend.app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    UserSummary,
    UserProfileResponse,
)
from backend.app.services.auth import (
    AuthService,
    AuthenticationFailedError,
    UserDeactivatedError,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate police personnel",
)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticate officer via badge number or email and issue stateless JWT."""
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    try:
        user, token, expires_in = AuthService.authenticate(
            db=db,
            username=payload.username,
            password=payload.password,
            ip_address=client_ip,
        )
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=UserSummary(
                id=user.id,
                badge_number=user.badge_number,
                full_name=user.full_name,
                role=user.role.name if user.role else "UNKNOWN",
            ),
        )
    except AuthenticationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except UserDeactivatedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke client session and audit log logout",
)
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Terminate session and write operational record to append-only audit trail."""
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    AuthService.logout(db=db, user=current_user, ip_address=client_ip)


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Retrieve current officer profile and permissions",
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserProfileResponse:
    """Retrieve profile and active clearances for the authenticated user."""
    permissions = []
    if current_user.role and current_user.role.permissions:
        permissions = [p.code for p in current_user.role.permissions]

    return UserProfileResponse(
        id=current_user.id,
        badge_number=current_user.badge_number,
        full_name=current_user.full_name,
        email=current_user.email,
        role=current_user.role.name if current_user.role else "UNKNOWN",
        department_id=current_user.department.id if current_user.department else current_user.department_id,
        department_name=current_user.department.name if current_user.department else "General Administration",
        department_code=current_user.department.code if current_user.department else "GEN",
        permissions=permissions,
        is_active=current_user.is_active,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
    )
