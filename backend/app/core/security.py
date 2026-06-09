"""Security primitives: password hashing (bcrypt via passlib) and JWT handling.

Two token types are minted here, distinguished by a `type` claim so an access
token can never be replayed as a refresh token (or vice-versa):
  - access  (short-lived, 15 min) — carried in the Authorization header
  - refresh (long-lived, 7 days)  — exchanged at /auth/refresh, rotated on use

Every token gets a unique `jti`; the refresh `jti` is persisted so it can be
revoked (rotation / logout). This module is pure — no DB, no FastAPI.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


# --- Passwords ---------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# --- JWT ---------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str | uuid.UUID) -> str:
    """Mint a short-lived access token. `subject` is the user id."""
    now = _now()
    payload = {
        "sub": str(subject),
        "type": ACCESS_TOKEN_TYPE,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return _encode(payload)


def create_refresh_token(subject: str | uuid.UUID) -> tuple[str, str, datetime]:
    """Mint a long-lived refresh token.

    Returns (token, jti, expires_at) so the caller can persist the jti for
    revocation/rotation.
    """
    now = _now()
    jti = uuid.uuid4().hex
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(subject),
        "type": REFRESH_TOKEN_TYPE,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": expires_at,
    }
    return _encode(payload), jti, expires_at


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """Decode and validate a JWT. Raises TokenExpiredError / InvalidTokenError.

    When `expected_type` is given, the token's `type` claim must match — this is
    what prevents an access token from being used at the refresh endpoint.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except JWTError as exc:
        raise InvalidTokenError() from exc

    if expected_type is not None and payload.get("type") != expected_type:
        raise InvalidTokenError("Invalid token type")
    return payload
