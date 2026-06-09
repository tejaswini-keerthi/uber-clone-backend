"""User profile endpoint tests."""
from __future__ import annotations

ME = "/api/v1/users/me"


async def test_get_my_profile(client, auth_headers, registered_user):
    resp = await client.get(ME, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == registered_user["payload"]["email"]


async def test_get_my_profile_requires_auth(client):
    resp = await client.get(ME)
    assert resp.status_code == 403


async def test_update_profile_full_name_and_phone(client, auth_headers):
    resp = await client.patch(
        ME, headers=auth_headers, json={"full_name": "Renamed", "phone": "+15559998888"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Renamed"
    assert body["phone"] == "+15559998888"


async def test_update_profile_partial_only_phone(client, auth_headers, registered_user):
    resp = await client.patch(ME, headers=auth_headers, json={"phone": "+15551112222"})
    assert resp.status_code == 200
    body = resp.json()
    # full_name unchanged
    assert body["full_name"] == registered_user["payload"]["full_name"]
    assert body["phone"] == "+15551112222"


async def test_update_profile_persists(client, auth_headers):
    await client.patch(ME, headers=auth_headers, json={"full_name": "Persisted Name"})
    resp = await client.get(ME, headers=auth_headers)
    assert resp.json()["full_name"] == "Persisted Name"
