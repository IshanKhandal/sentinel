"""Pydantic schemas for authentication, authorization, and user management.

Protocol Standards:
- docs/api-contract.md Section 1 (Authentication) & Section 2 (Users & Personnel)
- RFC 7807 compliant error schemas
- Strictly exclude plaintext passwords and hashed_password from read responses
"""

import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict, AliasChoices


# ============================================================================
# Authentication Schemas
# ============================================================================

class LoginRequest(BaseModel):
    """User credential login payload."""
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        validation_alias=AliasChoices("username", "identifier"),
        min_length=1,
        max_length=100,
        description="Badge number or police email address"
    )
    password: str = Field(..., min_length=1, max_length=128, description="User plaintext password")


class UserSummary(BaseModel):
    """Minimal user profile summary returned upon login."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID = Field(..., description="Unique user UUID")
    badge_number: str = Field(..., description="Official police badge identifier")
    full_name: str = Field(..., description="Officer or operator full name")
    role: str = Field(..., description="Assigned clearance role")


class LoginResponse(BaseModel):
    """Standardized JWT authentication response."""
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(..., description="Stateless JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token validity duration in seconds")
    user: UserSummary = Field(..., description="Summary of authenticated user")


class UserProfileResponse(BaseModel):
    """Detailed profile of the currently authenticated officer."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID = Field(..., description="User UUID")
    badge_number: str = Field(..., description="Badge identifier")
    full_name: str = Field(..., description="Full officer name")
    email: str = Field(..., description="Official email address")
    role: str = Field(..., description="Assigned role name")
    department_id: uuid.UUID = Field(..., description="Department UUID")
    department_name: str = Field(..., description="Department or jurisdiction unit name")
    department_code: str = Field(..., description="Department identifier code")
    permissions: List[str] = Field(default_factory=list, description="Granted permission codes")
    is_active: bool = Field(..., description="Whether user account is active")
    last_login_at: Optional[datetime] = Field(default=None, description="Previous login timestamp")
    created_at: datetime = Field(..., description="Account creation timestamp")


# ============================================================================
# User Management Schemas
# ============================================================================

class UserCreate(BaseModel):
    """Payload to provision a new police operator or investigator account."""
    model_config = ConfigDict(extra="forbid")

    badge_number: str = Field(..., min_length=2, max_length=50, description="Unique badge identifier")
    full_name: str = Field(..., min_length=2, max_length=150, description="Full officer name")
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Unique police email address")
    password: str = Field(..., min_length=8, max_length=128, description="Initial plaintext password to hash")
    role_id: uuid.UUID = Field(..., description="Clearance role UUID")
    department_id: uuid.UUID = Field(..., description="Assigned department UUID")
    is_active: bool = Field(default=True, description="Account active status")


class UserUpdate(BaseModel):
    """Payload to modify existing police user account."""
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    email: Optional[str] = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    role_id: Optional[uuid.UUID] = Field(default=None)
    department_id: Optional[uuid.UUID] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class UserRead(BaseModel):
    """User account representation excluding password hashes."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID = Field(..., description="User UUID")
    badge_number: str = Field(..., description="Badge identifier")
    full_name: str = Field(..., description="Full officer name")
    email: str = Field(..., description="Official email address")
    is_active: bool = Field(..., description="Active status")
    role_id: uuid.UUID = Field(..., description="Role UUID")
    role_name: str = Field(..., description="Role name")
    department_id: uuid.UUID = Field(..., description="Department UUID")
    department_name: str = Field(..., description="Department name")
    department_code: str = Field(..., description="Department code")
    last_login_at: Optional[datetime] = Field(default=None, description="Last login timestamp")
    created_at: datetime = Field(..., description="Account creation timestamp")


class UserListResponse(BaseModel):
    """Paginated list of registered police operators and personnel."""
    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., ge=0, description="Total matching user count")
    items: List[UserRead] = Field(..., description="List of user account objects")
