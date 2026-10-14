"""Behavioral checks for bootstrap, invitations, roles, secrets and removed routes."""

import time
from fastapi.testclient import TestClient
from app import core, main, accounts

H = {"Origin": "https://testserver"}
IDENTITY = {
    "email": "owner@example.com",
    "name": "Owner",
    "password": "test-password-123",
    "confirm_password": "test-password-123",
    "token": "test-setup-token",
}


def setup(client):
    assert client.post("/api/setup", headers=H, json=IDENTITY).status_code == 200
    result = client.post("/api/login", headers=H, json=IDENTITY)
    return {**H, "X-CSRF": result.json()["csrf"]}


def test_setup_is_protected_and_one_time(client):
    assert client.get("/api/setup").json()["required"]
    assert (
        client.post(
            "/api/setup", headers=H, json={**IDENTITY, "token": "wrong"}
        ).status_code
        == 403
    )
    setup(client)
    assert not client.get("/api/setup").json()["required"]
    assert client.post("/api/setup", headers=H, json=IDENTITY).status_code == 409
    assert client.get("/api/me").json()["account"]["role"] == "admin"


def test_invitation_scope_single_use_and_member_permissions(client):
    h = setup(client)
    invitation = client.post(
        "/api/instance/invites", headers=h, json={"email": "member@example.com"}
    ).json()
    token = invitation["url"].split("#invite=")[1]
    with core.db() as c:
        assert c.execute("SELECT token FROM community_invites").fetchone()[0] != token
    with TestClient(main.app, base_url="https://testserver") as member:
        data = {**IDENTITY, "email": "wrong@example.com", "token": token}
        assert (
            member.post("/api/invite/accept", headers=H, json=data).status_code == 400
        )
        data["email"] = "member@example.com"
        assert (
            member.post("/api/invite/accept", headers=H, json=data).status_code == 200
        )
        assert (
            member.post("/api/invite/accept", headers=H, json=data).status_code == 400
        )
        csrf = member.post("/api/login", headers=H, json=data).json()["csrf"]
        mh = {**H, "X-CSRF": csrf}
        assert member.get("/api/instance/providers").status_code == 403
        assert (
            member.put(
                "/api/instance/providers",
                headers=mh,
                json={"settings": {}, "version": 0},
            ).status_code
            == 403
        )
        assert member.get("/api/admin/users").status_code == 403
        assert (
            member.post(
                "/api/tasks", headers=mh, json={"prompt": "Hello", "mode": "chat"}
            ).status_code
            == 200
        )
        assert client.get("/api/tasks").json() == []


def test_expiry_revocation_and_owner_lockout(client):
    h = setup(client)
    token = (
        client.post(
            "/api/instance/invites", headers=h, json={"email": "new@example.com"}
        )
        .json()["url"]
        .split("=")[1]
    )
    with core.db() as c:
        c.execute("UPDATE community_invites SET expires=%s", (time.time() - 1,))
    assert (
        client.post(
            "/api/invite/accept",
            headers=H,
            json={**IDENTITY, "email": "new@example.com", "token": token},
        ).status_code
        == 400
    )
    user = client.get("/api/admin/users").json()["users"][0]
    current = client.get("/api/admin/users/" + user["id"]).json()
    body = {k: current[k] for k in ("role", "disabled", "overrides", "version")}
    assert (
        client.put(
            "/api/admin/users/" + user["id"], headers=h, json={**body, "role": "user"}
        ).status_code
        == 400
    )
    assert (
        client.request(
            "DELETE", "/api/instance/invites", headers=h, json={}
        ).status_code
        == 200
    )


def test_encrypted_keys_live_update_remove_and_csrf(client, monkeypatch):
    from app import integrations

    h = setup(client)
    body = {"version": 0, "settings": {"openrouter_key": "private-provider-secret"}}
    assert (
        client.put("/api/instance/providers", headers=H, json=body).status_code == 403
    )
    assert (
        client.put("/api/instance/providers", headers=h, json=body).status_code == 200
    )
    assert integrations.credential("OPENROUTER_API_KEY") == "private-provider-secret"
    assert "private-provider-secret" not in client.get("/api/instance/providers").text
    with core.db() as c:
        assert (
            "private-provider-secret"
            not in c.execute("SELECT body FROM integration_settings").fetchone()[0]
        )
    assert (
        client.put("/api/instance/providers", headers=h, json=body).status_code == 400
    )
    assert (
        client.put(
            "/api/instance/providers",
            headers=h,
            json={"version": 1, "settings": {}, "remove": ["openrouter_key"]},
        ).status_code
        == 200
    )
    assert integrations.credential("OPENROUTER_API_KEY") == ""


def test_removed_commercial_routes_and_password_change(client):
    h = setup(client)
    for route in (
        "register",
        "register/verify",
        "register/resend",
        "password-reset/request",
        "password-reset/complete",
        "billing/checkout",
        "billing/stripe/webhook",
    ):
        assert client.post("/api/" + route, headers=h, json={}).status_code == 404
    assert client.get("/api/credits").status_code == 404
    assert (
        client.post(
            "/api/change-password",
            headers=h,
            json={
                "current": IDENTITY["password"],
                "new": "a-different-password-123",
                "confirm": "a-different-password-123",
            },
        ).status_code
        == 200
    )


def test_http_session_cookie_and_origin(client, monkeypatch):
    setup(client)
    monkeypatch.setattr(core, "ORIGIN", "http://testserver")
    with TestClient(main.app, base_url="http://testserver") as http:
        result = http.post(
            "/api/login", headers={"Origin": "http://testserver"}, json=IDENTITY
        )
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert (
            "HttpOnly" in cookie
            and "SameSite=strict" in cookie
            and "Secure" not in cookie
        )
        assert http.get("/api/me").status_code == 200
        assert (
            http.post(
                "/api/tasks",
                headers={"Origin": "http://evil.test", "X-CSRF": result.json()["csrf"]},
                json={"prompt": "hello"},
            ).status_code
            == 403
        )


def test_missing_keys_fail_before_provider_requests(client, monkeypatch):
    import asyncio
    from app import providers

    setup(client)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    import pytest

    with pytest.raises(providers.ProviderError, match="Instance settings"):
        asyncio.run(providers._prepare_model({}, {}, [], "hello"))
    with pytest.raises(providers.ProviderError, match="Instance settings"):
        asyncio.run(providers.search({}, {}, "hello"))
