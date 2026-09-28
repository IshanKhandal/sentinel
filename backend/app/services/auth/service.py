"""Authentication and User management services.

Protocol Standards:
- docs/security-architecture.md Sections 1 & 2 (JWT, RBAC, Bcrypt cost 12)
- docs/api-contract.md Sections 1 & 2
- Append-only audit logging on security operations
- Never store plaintext passwords or log credentials
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.app.core.config import settings
from backend.app.core.security import hash_password, verify_password, create_access_token
from backend.app.models.access import User, Role, Department
from backend.app.models.audit import AuditLog
from backend.app.schemas.auth import UserCreate, UserUpdate


class AuthError(Exception):
    """Base exception for authentication failures."""
    pass


class AuthenticationFailedError(AuthError):
    """Raised when provided credentials do not match or user is not found."""
    pass


class UserDeactivatedError(AuthError):
    """Raised when an inactive user attempts authentication."""
    pass


class UserError(Exception):
    """Base exception for user management failures."""
    pass


class UserNotFoundError(UserError):
    """Raised when a user account cannot be found."""
    pass


class UserConflictError(UserError):
    """Raised when a unique constraint (badge_number or email) is violated."""
    pass


class UserValidationError(UserError):
    """Raised when referenced role or department is invalid."""
    pass


class AuthService:
    """Service handling user credential authentication and session termination."""

    @staticmethod
    def authenticate(
        db: Session,
        username: str,
        password: str,
        ip_address: str = "127.0.0.1"
    ) -> Tuple[User, str, int]:
        """Authenticate user by badge number or email, emit audit log, and return access token."""
        username_clean = username.strip()
        user = (
            db.query(User)
            .options(
                joinedload(User.role),
                joinedload(User.department),
            )
            .filter(
                (User.badge_number == username_clean) | (func.lower(User.email) == username_clean.lower())
            )
            .first()
        )

        if not user or not verify_password(password, user.hashed_password):
            # Log authentication failure in append-only audit log
            audit_log = AuditLog(
                user_id=user.id if user else None,
                badge_number=username_clean,
                action="AUTH_LOGIN_FAILURE",
                resource_type="USER",
                resource_id=username_clean,
                ip_address=ip_address,
                payload_summary=json.dumps({"reason": "Invalid credentials", "attempted_identifier": username_clean}),
            )
            db.add(audit_log)
            db.commit()
            raise AuthenticationFailedError("Invalid badge number or password.")

        if not user.is_active:
            audit_log = AuditLog(
                user_id=user.id,
                badge_number=user.badge_number,
                action="AUTH_LOGIN_FAILURE",
                resource_type="USER",
                resource_id=str(user.id),
                ip_address=ip_address,
                payload_summary=json.dumps({"reason": "Account deactivated", "badge_number": user.badge_number}),
            )
            db.add(audit_log)
            db.commit()
            raise UserDeactivatedError("User account is deactivated.")

        # Update last login timestamp
        user.last_login_at = datetime.now(timezone.utc)
        
        # Log authentication success in audit log
        audit_log = AuditLog(
            user_id=user.id,
            badge_number=user.badge_number,
            action="AUTH_LOGIN_SUCCESS",
            resource_type="USER",
            resource_id=str(user.id),
            ip_address=ip_address,
            payload_summary=json.dumps({
                "badge_number": user.badge_number,
                "role": user.role.name if user.role else "UNKNOWN",
                "department": user.department.code if user.department else "UNKNOWN",
            }),
        )
        db.add(audit_log)
        db.commit()
        db.refresh(user)

        # Issue JWT Access Token
        token_claims = {
            "sub": str(user.id),
            "badge": user.badge_number,
            "role": user.role.name if user.role else "Operator",
            "dept": user.department.code if user.department else "GEN",
        }
        token = create_access_token(token_claims)
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        return user, token, expires_in

    @staticmethod
    def logout(db: Session, user: User, ip_address: str = "127.0.0.1") -> None:
        """Record session termination in append-only audit trail."""
        audit_log = AuditLog(
            user_id=user.id,
            badge_number=user.badge_number,
            action="AUTH_LOGOUT",
            resource_type="USER",
            resource_id=str(user.id),
            ip_address=ip_address,
            payload_summary=json.dumps({"badge_number": user.badge_number}),
        )
        db.add(audit_log)
        db.commit()


class UserService:
    """Service handling administrative user provisioning, retrieval, and updates."""

    @staticmethod
    def create_user(
        db: Session,
        data: UserCreate,
        current_user: User,
        ip_address: str = "127.0.0.1"
    ) -> User:
        """Create a new police personnel account with hashed password and audit trail."""
        # Check badge uniqueness
        existing_badge = db.query(User).filter(User.badge_number == data.badge_number.strip()).first()
        if existing_badge:
            raise UserConflictError(f"User with badge number '{data.badge_number}' already exists.")

        # Check email uniqueness
        existing_email = db.query(User).filter(func.lower(User.email) == data.email.lower().strip()).first()
        if existing_email:
            raise UserConflictError(f"User with email '{data.email}' already exists.")

        # Verify role exists
        role = db.query(Role).filter(Role.id == data.role_id).first()
        if not role:
            raise UserValidationError(f"Role with ID '{data.role_id}' does not exist.")

        # Verify department exists
        dept = db.query(Department).filter(Department.id == data.department_id).first()
        if not dept:
            raise UserValidationError(f"Department with ID '{data.department_id}' does not exist.")

        # Hash password with bcrypt cost 12
        hashed = hash_password(data.password)

        new_user = User(
            id=uuid.uuid4(),
            badge_number=data.badge_number.strip(),
            full_name=data.full_name.strip(),
            email=data.email.lower().strip(),
            hashed_password=hashed,
            role_id=role.id,
            department_id=dept.id,
            is_active=data.is_active,
        )
        db.add(new_user)
        db.flush()

        # Audit log creation
        audit_log = AuditLog(
            user_id=current_user.id,
            badge_number=current_user.badge_number,
            action="USER_CREATE",
            resource_type="USER",
            resource_id=str(new_user.id),
            ip_address=ip_address,
            payload_summary=json.dumps({
                "badge_number": new_user.badge_number,
                "role": role.name,
                "department": dept.code,
            }),
        )
        db.add(audit_log)
        db.commit()
        db.refresh(new_user)

        return new_user

    @staticmethod
    def get_user_by_id(db: Session, user_id: uuid.UUID) -> Optional[User]:
        """Retrieve user by UUID with eager-loaded role and department."""
        return (
            db.query(User)
            .options(
                joinedload(User.role),
                joinedload(User.department),
            )
            .filter(User.id == user_id)
            .first()
        )

    @staticmethod
    def list_users(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        role_name: Optional[str] = None
    ) -> Tuple[List[User], int]:
        """List registered users with optional role filtering and pagination."""
        query = (
            db.query(User)
            .options(
                joinedload(User.role),
                joinedload(User.department),
            )
        )
        if role_name:
            query = query.join(Role).filter(Role.name == role_name)
        
        total = query.count()
        items = query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()
        return items, total

    @staticmethod
    def update_user(
        db: Session,
        user_id: uuid.UUID,
        data: UserUpdate,
        current_user: User,
        ip_address: str = "127.0.0.1"
    ) -> User:
        """Modify an existing user profile."""
        user = UserService.get_user_by_id(db=db, user_id=user_id)
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        updated_fields = []
        if data.full_name is not None:
            user.full_name = data.full_name.strip()
            updated_fields.append("full_name")

        if data.email is not None:
            existing = db.query(User).filter(
                func.lower(User.email) == data.email.lower().strip(),
                User.id != user.id
            ).first()
            if existing:
                raise UserConflictError(f"Email '{data.email}' is already registered to another user.")
            user.email = data.email.lower().strip()
            updated_fields.append("email")

        if data.password is not None:
            user.hashed_password = hash_password(data.password)
            updated_fields.append("password")

        if data.role_id is not None:
            role = db.query(Role).filter(Role.id == data.role_id).first()
            if not role:
                raise UserValidationError(f"Role '{data.role_id}' not found.")
            user.role_id = role.id
            updated_fields.append("role_id")

        if data.department_id is not None:
            dept = db.query(Department).filter(Department.id == data.department_id).first()
            if not dept:
                raise UserValidationError(f"Department '{data.department_id}' not found.")
            user.department_id = dept.id
            updated_fields.append("department_id")

        if data.is_active is not None:
            user.is_active = data.is_active
            updated_fields.append("is_active")

        audit_log = AuditLog(
            user_id=current_user.id,
            badge_number=current_user.badge_number,
            action="USER_UPDATE",
            resource_type="USER",
            resource_id=str(user.id),
            ip_address=ip_address,
            payload_summary=json.dumps({
                "updated_fields": updated_fields,
                "badge_number": user.badge_number,
            }),
        )
        db.add(audit_log)
        db.commit()
        db.refresh(user)

        return user
