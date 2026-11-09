"""Authentication and authorization for the API."""

import os
import secrets
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Security, params, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError
from pydantic import BaseModel, Field

from autoops_architect.logging import get_logger

logger = get_logger(__name__)

# Configuration


def _load_secret_key() -> str:
    """Read the JWT signing key; an empty value (as compose passes) means unset."""
    return os.getenv("AUTOOPS_SECRET_KEY") or secrets.token_urlsafe(32)


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTOOPS_TOKEN_EXPIRE_MINUTES", "60"))
API_KEY_HEADER_NAME = "X-API-Key"

# bcrypt only reads the first 72 bytes of a password and bcrypt>=5 raises on more.
BCRYPT_MAX_PASSWORD_BYTES = 72

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


class Role(str, Enum):
    """User roles for RBAC."""

    VIEWER = "viewer"  # Read-only access
    OPERATOR = "operator"  # Execute workflows
    ADMIN = "admin"  # Full access


# Role permissions
ROLE_PERMISSIONS = {
    Role.VIEWER: {
        "read:workflows",
        "read:templates",
        "read:memory",
        "read:health",
    },
    Role.OPERATOR: {
        "read:workflows",
        "read:templates",
        "read:memory",
        "read:health",
        "execute:workflows",
        "create:workflows",
    },
    Role.ADMIN: {
        "*",  # All permissions
    },
}


class User(BaseModel):
    """User model."""

    username: str = Field(..., min_length=3, max_length=50)
    email: str | None = None
    full_name: str | None = None
    disabled: bool = False
    roles: list[Role] = Field(default_factory=lambda: [Role.VIEWER])


class UserInDB(User):
    """User model with password hash."""

    hashed_password: str


class Token(BaseModel):
    """Access token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """Token payload data."""

    username: str | None = None
    roles: list[Role] = Field(default_factory=list)


class APIKey(BaseModel):
    """API key model."""

    key: str
    name: str
    roles: list[Role]
    created_at: datetime
    expires_at: datetime | None = None
    disabled: bool = False


# Simple in-memory storage (replace with database in production)
fake_users_db: dict[str, UserInDB] = {}
fake_api_keys_db: dict[str, APIKey] = {}


def _password_bytes(password: str) -> bytes:
    """Encode a password for bcrypt, which ignores everything past 72 bytes."""
    return password.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(_password_bytes(plain_password), hashed_password.encode("ascii"))
    except ValueError:
        # A malformed stored hash is a failed login, not a server error.
        return False


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("ascii")


def get_user(username: str) -> UserInDB | None:
    """Get a user from the database."""
    return fake_users_db.get(username)


def authenticate_user(username: str, password: str) -> UserInDB | None:
    """Authenticate a user with username and password."""
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> TokenData:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        roles_str = payload.get("roles", [])
        roles = [Role(r) for r in roles_str]
        return TokenData(username=username, roles=roles)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def validate_api_key(api_key: str) -> APIKey | None:
    """Validate an API key."""
    key_data = fake_api_keys_db.get(api_key)
    if not key_data:
        return None
    if key_data.disabled:
        return None
    if key_data.expires_at and key_data.expires_at < datetime.utcnow():
        return None
    return key_data


async def get_current_user(
    bearer_token: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> User:
    """
    Get the current authenticated user.

    Supports both JWT bearer tokens and API keys.
    """
    # Try API key first
    if api_key:
        key_data = validate_api_key(api_key)
        if key_data:
            return User(
                username=key_data.name,
                roles=key_data.roles,
                disabled=False,
            )

    # Try JWT bearer token
    if bearer_token:
        token_data = decode_access_token(bearer_token.credentials)
        user = get_user(token_data.username)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        if user.disabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is disabled",
            )
        return User(**user.model_dump())

    # No valid authentication found
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def has_permission(user: User, permission: str) -> bool:
    """Check if a user has a specific permission."""
    for role in user.roles:
        permissions = ROLE_PERMISSIONS.get(role, set())
        if "*" in permissions or permission in permissions:
            return True
    return False


def require_permission(permission: str):
    """Dependency to require a specific permission."""

    async def check_permission(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission} required",
            )
        return user

    return check_permission


def auth_enabled() -> bool:
    """Whether API authentication is switched on for this process."""
    return os.getenv("AUTOOPS_AUTH_ENABLED", "false").lower() == "true"


def requires(permission: str) -> params.Depends:
    """
    Route dependency that enforces a permission whenever authentication is enabled.

    The setting is read per request so that one app instance cannot end up with
    some routes protected and others not, depending on import order.
    """

    async def check(
        bearer_token: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
        api_key: str | None = Security(api_key_header),
    ) -> None:
        if not auth_enabled():
            return

        user = await get_current_user(bearer_token, api_key)
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission} required",
            )

    return Depends(check)


def require_role(role: Role):
    """Dependency to require a specific role."""

    async def check_role(user: User = Depends(get_current_user)) -> User:
        if role not in user.roles and Role.ADMIN not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {role.value} required",
            )
        return user

    return check_role


def create_default_admin(username: str, password: str) -> UserInDB:
    """Create an admin user with the given credentials."""
    admin_user = UserInDB(
        username=username,
        email=f"{username}@example.com",
        full_name="Administrator",
        disabled=False,
        roles=[Role.ADMIN],
        hashed_password=get_password_hash(password),
    )
    fake_users_db[username] = admin_user
    return admin_user


def create_api_key(
    name: str,
    roles: list[Role],
    expires_days: int | None = None,
) -> tuple[str, APIKey]:
    """Create a new API key."""
    key = secrets.token_urlsafe(32)
    expires_at = None
    if expires_days:
        expires_at = datetime.utcnow() + timedelta(days=expires_days)

    api_key_data = APIKey(
        key=key,
        name=name,
        roles=roles,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        disabled=False,
    )
    fake_api_keys_db[key] = api_key_data
    return key, api_key_data


def bootstrap_admin_from_env() -> UserInDB | None:
    """
    Create the first admin from AUTOOPS_ADMIN_USERNAME and AUTOOPS_ADMIN_PASSWORD.

    Only runs when AUTOOPS_CREATE_ADMIN=true and no users exist. There is no
    default password: without AUTOOPS_ADMIN_PASSWORD no account is created.
    """
    if os.getenv("AUTOOPS_CREATE_ADMIN", "false").lower() != "true" or fake_users_db:
        return None

    password = os.getenv("AUTOOPS_ADMIN_PASSWORD")
    if not password:
        logger.warning("admin_bootstrap_skipped", reason="AUTOOPS_ADMIN_PASSWORD is not set")
        return None

    admin = create_default_admin(os.getenv("AUTOOPS_ADMIN_USERNAME", "admin"), password)
    logger.info("admin_bootstrap_completed", username=admin.username)
    return admin


bootstrap_admin_from_env()
