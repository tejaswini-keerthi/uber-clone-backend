"""Auth endpoints. Thin: parse/validate in, delegate to AuthService, shape out.

No business logic here — registration rules, credential checks, and token
rotation all live in AuthService.
"""
from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import AuthServiceDep, CurrentUser
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenPair
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, service: AuthServiceDep) -> UserRead:
    """Create a new account."""
    user = await service.register(data)
    return user


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, service: AuthServiceDep) -> TokenPair:
    """Exchange credentials for an access + refresh token pair."""
    return await service.login(data.email, data.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, service: AuthServiceDep) -> TokenPair:
    """Rotate a refresh token: revokes the old one, returns a fresh pair."""
    return await service.rotate_refresh_token(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: LogoutRequest, service: AuthServiceDep) -> Response:
    """Revoke a refresh token (idempotent)."""
    await service.logout(data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead)
async def read_me(current_user: CurrentUser) -> UserRead:
    """Return the authenticated user (validates the access token)."""
    return current_user
