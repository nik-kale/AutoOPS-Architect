"""Authentication routes."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from autoops_architect.api.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    Role,
    Token,
    User,
    authenticate_user,
    create_access_token,
    create_api_key,
    get_current_user,
    require_role,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginResponse(BaseModel):
    """Login response with token and user info."""

    access_token: str
    token_type: str
    expires_in: int
    user: User


class APIKeyRequest(BaseModel):
    """Request to create an API key."""

    name: str = Field(..., min_length=3, max_length=100, description="API key name")
    roles: list[Role] = Field(default_factory=lambda: [Role.VIEWER])
    expires_days: int | None = Field(None, ge=1, le=365, description="Expiration in days")


class APIKeyResponse(BaseModel):
    """Response with created API key."""

    key: str
    name: str
    roles: list[Role]
    expires_in_days: int | None
    message: str = "Store this key safely. It cannot be retrieved again."


@router.post("/login", response_model=LoginResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> LoginResponse:
    """
    Login with username and password to get an access token.

    The token can be used with the Bearer authentication scheme.
    """
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "roles": [r.value for r in user.roles]},
        expires_delta=access_token_expires,
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # In seconds
        user=User(**user.dict()),
    )


@router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)) -> User:
    """Get current user information."""
    return current_user


@router.post(
    "/api-keys",
    response_model=APIKeyResponse,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_new_api_key(request: APIKeyRequest) -> APIKeyResponse:
    """
    Create a new API key (admin only).

    The generated key should be stored safely as it cannot be retrieved again.
    """
    key, api_key_data = create_api_key(
        name=request.name,
        roles=request.roles,
        expires_days=request.expires_days,
    )

    return APIKeyResponse(
        key=key,
        name=api_key_data.name,
        roles=api_key_data.roles,
        expires_in_days=request.expires_days,
    )


@router.get("/permissions", response_model=dict[str, list[str]])
async def list_permissions() -> dict[str, list[str]]:
    """
    List all available roles and their permissions.

    No authentication required - this is public information.
    """
    from autoops_architect.api.auth import ROLE_PERMISSIONS

    return {
        role.value: list(perms) for role, perms in ROLE_PERMISSIONS.items()
    }

