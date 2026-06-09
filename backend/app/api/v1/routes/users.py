"""User profile endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserServiceDep
from app.schemas.user import UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_my_profile(current_user: CurrentUser) -> UserRead:
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    data: UserUpdate, current_user: CurrentUser, service: UserServiceDep
) -> UserRead:
    return await service.update_profile(current_user, data)
