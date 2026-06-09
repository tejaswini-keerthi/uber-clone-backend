"""Auth flow tests: registration, login, JWT, refresh-token rotation, logout."""
from __future__ import annotations

import sqlalchemy as sa

from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


# --- Unit: security primitives ----------------------------------------------
def test_password_hash_roundtrip():
    hashed = hash_password("supersecret123")
    assert hashed != "supersecret123"
    assert verify_password("supersecret123", hashed)
    assert not verify_password("wrong", hashed)


def test_access_and_refresh_tokens_carry_type_claim():
    access = create_access_token("user-1")
    payload = decode_token(access, expected_type=ACCESS_TOKEN_TYPE)
    assert payload["sub"] == "user-1"
    assert payload["type"] == ACCESS_TOKEN_TYPE
    assert "jti" in payload and "exp" in payload


def test_decode_rejects_wrong_token_type():
    access = create_access_token("user-1")
    # An access token must not validate as a refresh token.
    import pytest

    from app.core.exceptions import InvalidTokenError

    with pytest.raises(InvalidTokenError):
        decode_token(access, expected_type=REFRESH_TOKEN_TYPE)


# --- Registration ------------------------------------------------------------
async def test_register_success(client):
    resp = await client.post(
        REGISTER,
        json={
            "email": "new@example.com",
            "password": "supersecret123",
            "full_name": "New User",
            "phone": "+15551234567",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "rider"
    assert body["is_active"] is True
    assert "id" in body and "created_at" in body
    assert "password" not in body and "hashed_password" not in body


async def test_register_persists_hashed_password(client, db):
    await client.post(
        REGISTER,
        json={
            "email": "hash@example.com",
            "password": "supersecret123",
            "full_name": "Hash User",
        },
    )
    stored = (
        await db.execute(
            sa.text("SELECT hashed_password FROM users WHERE email = :e"),
            {"e": "hash@example.com"},
        )
    ).scalar_one()
    assert stored != "supersecret123"
    assert verify_password("supersecret123", stored)


async def test_register_as_driver_role(client):
    resp = await client.post(
        REGISTER,
        json={
            "email": "driver@example.com",
            "password": "supersecret123",
            "full_name": "Drive R",
            "role": "driver",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "driver"


async def test_register_duplicate_email_conflicts(client, registered_user):
    resp = await client.post(REGISTER, json=registered_user["payload"])
    assert resp.status_code == 409


async def test_register_invalid_email_422(client):
    resp = await client.post(
        REGISTER,
        json={"email": "not-an-email", "password": "supersecret123", "full_name": "X"},
    )
    assert resp.status_code == 422


async def test_register_short_password_422(client):
    resp = await client.post(
        REGISTER,
        json={"email": "a@b.com", "password": "short", "full_name": "X"},
    )
    assert resp.status_code == 422


# --- Login -------------------------------------------------------------------
async def test_login_success_returns_token_pair(client, registered_user):
    payload = registered_user["payload"]
    resp = await client.post(
        LOGIN, json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert decode_token(body["access_token"], ACCESS_TOKEN_TYPE)["sub"]
    assert decode_token(body["refresh_token"], REFRESH_TOKEN_TYPE)["sub"]


async def test_login_wrong_password_401(client, registered_user):
    resp = await client.post(
        LOGIN,
        json={"email": registered_user["payload"]["email"], "password": "nope"},
    )
    assert resp.status_code == 401


async def test_login_unknown_user_401(client):
    resp = await client.post(
        LOGIN, json={"email": "ghost@example.com", "password": "whatever12"}
    )
    assert resp.status_code == 401


async def test_two_logins_issue_distinct_refresh_tokens(client, registered_user):
    creds = {
        "email": registered_user["payload"]["email"],
        "password": registered_user["payload"]["password"],
    }
    first = (await client.post(LOGIN, json=creds)).json()
    second = (await client.post(LOGIN, json=creds)).json()
    assert first["refresh_token"] != second["refresh_token"]


# --- Protected route (get_current_user) --------------------------------------
async def test_me_requires_auth(client):
    resp = await client.get(ME)
    assert resp.status_code == 403  # HTTPBearer: missing credentials


async def test_me_with_valid_token(client, auth_headers, registered_user):
    resp = await client.get(ME, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == registered_user["payload"]["email"]


async def test_me_with_garbage_token_401(client):
    resp = await client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


async def test_me_rejects_refresh_token_as_access(client, auth_tokens):
    resp = await client.get(
        ME, headers={"Authorization": f"Bearer {auth_tokens['refresh_token']}"}
    )
    assert resp.status_code == 401


async def test_expired_access_token_rejected(client, registered_user, monkeypatch):
    from app.core.config import settings

    # Mint a token that is already expired.
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    expired = create_access_token(registered_user["user"]["id"])
    resp = await client.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


# --- Refresh rotation --------------------------------------------------------
async def test_refresh_returns_new_pair(client, auth_tokens):
    resp = await client.post(REFRESH, json={"refresh_token": auth_tokens["refresh_token"]})
    assert resp.status_code == 200, resp.text
    new = resp.json()
    assert new["access_token"] != auth_tokens["access_token"]
    assert new["refresh_token"] != auth_tokens["refresh_token"]


async def test_old_refresh_token_revoked_after_rotation(client, auth_tokens):
    # First use rotates and revokes the presented token.
    await client.post(REFRESH, json={"refresh_token": auth_tokens["refresh_token"]})
    # Reusing the now-revoked token must fail.
    resp = await client.post(REFRESH, json={"refresh_token": auth_tokens["refresh_token"]})
    assert resp.status_code == 401


async def test_rotated_token_can_be_used_again(client, auth_tokens):
    rotated = (
        await client.post(REFRESH, json={"refresh_token": auth_tokens["refresh_token"]})
    ).json()
    resp = await client.post(REFRESH, json={"refresh_token": rotated["refresh_token"]})
    assert resp.status_code == 200


async def test_refresh_with_access_token_rejected(client, auth_tokens):
    resp = await client.post(REFRESH, json={"refresh_token": auth_tokens["access_token"]})
    assert resp.status_code == 401


async def test_refresh_with_garbage_rejected(client):
    resp = await client.post(REFRESH, json={"refresh_token": "garbage"})
    assert resp.status_code == 401


# --- Logout ------------------------------------------------------------------
async def test_logout_revokes_refresh_token(client, auth_tokens):
    resp = await client.post(LOGOUT, json={"refresh_token": auth_tokens["refresh_token"]})
    assert resp.status_code == 204
    # The token can no longer be rotated.
    after = await client.post(REFRESH, json={"refresh_token": auth_tokens["refresh_token"]})
    assert after.status_code == 401


async def test_logout_is_idempotent(client, auth_tokens):
    await client.post(LOGOUT, json={"refresh_token": auth_tokens["refresh_token"]})
    second = await client.post(LOGOUT, json={"refresh_token": auth_tokens["refresh_token"]})
    assert second.status_code == 204
