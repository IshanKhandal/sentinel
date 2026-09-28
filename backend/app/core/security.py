"""Security utilities: password hashing (bcrypt cost 12) and JWT token management.

Protocol Standards:
- docs/security-architecture.md Section 1 (Authentication & Token Management)
- docs/engineering-rules.md Rule 41 (Secrets Management & Sanitization)
- bcrypt work factor 12
- JWT HS256 with standard claims (sub, badge, role, dept, exp, iat)
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import bcrypt
import jwt

from backend.app.core.config import settings


class SecurityError(Exception):
    """Base exception for security-related failures."""
    pass


class TokenExpiredError(SecurityError):
    """Raised when a JWT has passed its expiration time."""
    pass


class TokenInvalidError(SecurityError):
    """Raised when a JWT is malformed, has an invalid signature, or invalid claims."""
    pass


# ============================================================================
# Password Hashing & Verification (Bcrypt Cost 12)
# ============================================================================

def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt with frozen cost 12.
    
    Never logs or persists the plaintext password.
    """
    if not plain_password:
        raise ValueError("Password cannot be empty.")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.
    
    Returns False on mismatch or malformed hash format.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# ============================================================================
# JWT Token Generation & Verification
# ============================================================================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Generate a signed JWT access token.
    
    Adheres strictly to the frozen token claims:
    - sub: string UUID of the user
    - badge: badge number
    - role: user role name
    - dept: department code
    - exp: expiration UTC timestamp
    - iat: issued-at UTC timestamp
    """
    to_encode = data.copy()
    now_utc = datetime.now(timezone.utc)
    
    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "iat": int(now_utc.timestamp()),
        "exp": int(expire.timestamp()),
    })
    
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token.
    
    Raises:
        TokenExpiredError: If token expiration (exp) has passed.
        TokenInvalidError: If signature is invalid or payload is malformed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalidError("Invalid or malformed token.") from exc


# ============================================================================
# Sensitive Data Sanitization for Logging & Audit
# ============================================================================

SENSITIVE_KEYS_REGEX = re.compile(
    r"(password|token|secret|authorization|key|access_token|refresh_token|hashed_password)",
    re.IGNORECASE
)


def scrub_sensitive_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively scrub sensitive keys from dictionaries before logging or audit trail."""
    sanitized: Dict[str, Any] = {}
    for k, v in data.items():
        if SENSITIVE_KEYS_REGEX.search(str(k)):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = scrub_sensitive_dict(v)
        elif isinstance(v, list):
            sanitized[k] = [
                scrub_sensitive_dict(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized
