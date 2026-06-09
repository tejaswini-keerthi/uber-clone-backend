"""User profile business logic.

Small, but kept in the service layer to preserve the strict three-layer rule:
routes never mutate models or call repositories directly.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserUpdate


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        return await self.users.update_profile(
            user, full_name=data.full_name, phone=data.phone
        )
