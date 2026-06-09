"""Authentication business logic.

Owns the rules the API layer must not: duplicate-email checks, credential
verification, token minting, and refresh-token rotation. Talks to the database
exclusively through UserRepository and raises domain errors (app.core.exceptions)
that the API layer maps to HTTP responses.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EmailAlreadyExistsError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.user import UserCreate


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)

    async def register(self, data: UserCreate) -> User:
        if await self.users.get_by_email(data.email):
            raise EmailAlreadyExistsError()
        return await self.users.create(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role=data.role,
        )

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        # Verify against the stored hash even when the user is missing would be
        # ideal for timing-safety; here we keep it simple but return a single
        # generic error so we don't leak which emails exist.
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InactiveUserError()
        return user

    async def _issue_token_pair(self, user: User) -> TokenPair:
        access = create_access_token(user.id)
        refresh, jti, expires_at = create_refresh_token(user.id)
        await self.users.add_refresh_token(
            user_id=user.id, jti=jti, expires_at=expires_at
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.authenticate(email, password)
        return await self._issue_token_pair(user)

    async def rotate_refresh_token(self, refresh_token: str) -> TokenPair:
        """Validate a refresh token and rotate it.

        Rotation = the presented token is revoked and a brand-new access/refresh
        pair is issued. A revoked or already-used token is rejected, so a stolen
        refresh token is single-use at best.
        """
        payload = decode_token(refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        stored = await self.users.get_refresh_token(payload.get("jti", ""))
        if stored is None or stored.revoked:
            raise InvalidTokenError("Refresh token is no longer valid")
        if stored.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError("Refresh token has expired")

        await self.users.revoke_refresh_token(stored)

        user = await self.users.get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise InvalidTokenError()
        return await self._issue_token_pair(user)

    async def logout(self, refresh_token: str) -> None:
        """Revoke a refresh token. Best-effort: a malformed/expired token simply
        has nothing to revoke, so logout is idempotent."""
        try:
            payload = decode_token(refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        except InvalidTokenError:
            return
        stored = await self.users.get_refresh_token(payload.get("jti", ""))
        if stored is not None and not stored.revoked:
            await self.users.revoke_refresh_token(stored)
