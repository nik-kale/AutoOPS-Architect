"""Authentication and authorization for the API."""

import os
import secrets
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field


# Configuration
SECRET_KEY = os.getenv("AUTOOPS_SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTOOPS_TOKEN_EXPIRE_MINUTES", "60"))
API_KEY_HEADER_NAME = "X-API-Key"

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
    email: Optional[str] = None
    full_name: Optional[str] = None
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

    username: Optional[str] = None
    roles: list[Role] = Field(default_factory=list)


class APIKey(BaseModel):
    """API key model."""

    key: str
    name: str
    roles: list[Role]
    created_at: datetime
    expires_at: Optional[datetime] = None
    disabled: bool = False


# Simple in-memory storage (replace with database in production)
fake_users_db: dict[str, UserInDB] = {}
fake_api_keys_db: dict[str, APIKey] = {}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def get_user(username: str) -> Optional[UserInDB]:
    """Get a user from the database."""
    return fake_users_db.get(username)


def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    """Authenticate a user with username and password."""
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(
    data: dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
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


def validate_api_key(api_key: str) -> Optional[APIKey]:
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
    bearer_token: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
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
        return User(**user.dict())

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


# Helper function to create a default admin user (for setup)
def create_default_admin(username: str = "admin", password: str = "admin") -> UserInDB:
    """Create a default admin user (for development/setup only)."""
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
    expires_days: Optional[int] = None,
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


# Initialize with a default admin user if none exists (for development)
if not fake_users_db and os.getenv("AUTOOPS_CREATE_ADMIN", "false").lower() == "true":
    default_admin = create_default_admin()
    print(f"Created default admin user: {default_admin.username}")
    print("Default password: admin (CHANGE THIS IN PRODUCTION!)")

