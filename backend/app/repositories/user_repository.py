"""Data access for users and their refresh tokens.

Repository layer: only SQLAlchemy queries here — no hashing, no token minting,
no policy decisions. Those belong to the service layer.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken, User, UserRole


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- Users ---
    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        hashed_password: str,
        full_name: str,
        phone: str | None,
        role: UserRole,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            phone=phone,
            role=role,
        )
        self.db.add(user)
        # Flush to surface DB-side defaults (created_at, server defaults) and any
        # unique-constraint violations now, while still inside the request txn.
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update_profile(
        self, user: User, *, full_name: str | None, phone: str | None
    ) -> User:
        if full_name is not None:
            user.full_name = full_name
        if phone is not None:
            user.phone = phone
        await self.db.flush()
        await self.db.refresh(user)
        return user

    # --- Refresh tokens ---
    async def add_refresh_token(
        self, *, user_id: uuid.UUID, jti: str, expires_at
    ) -> RefreshToken:
        token = RefreshToken(user_id=user_id, jti=jti, expires_at=expires_at)
        self.db.add(token)
        await self.db.flush()
        return token

    async def get_refresh_token(self, jti: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: RefreshToken) -> None:
        token.revoked = True
        await self.db.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        await self.db.flush()
