"""Self-hosted identity lifecycle: protected bootstrap and manual invitations.

The installer generates a bootstrap secret. Its possession and an empty user
store are both required to claim the instance. The database write lock makes
bootstrap and single-use invite redemption atomic across API processes.
Internal legacy role names map to Owner (admin) and Member (user).
"""

import hmac
import os
import secrets
import time
from fastapi import HTTPException, Request
from . import accounts, core, integrations


def initialize(c):
    c.execute_schema("""
    CREATE TABLE IF NOT EXISTS community_invites(
      token TEXT PRIMARY KEY, email TEXT NOT NULL, creator TEXT NOT NULL,
      expires DOUBLE PRECISION NOT NULL, created DOUBLE PRECISION NOT NULL);
    """)


def identity(body):
    if not isinstance(body, dict):
        raise ValueError("A JSON object is required")
    email_value = body.get("email", "")
    if not isinstance(email_value, str):
        raise ValueError("Invalid email identifier")
    email = integrations.email_address(email_value.strip())
    password = body.get("password")
    name = body.get("name", "")
    if not isinstance(name, str):
        raise ValueError("Invalid display name")
    name = name.strip()
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("Password must be 12–128 characters")
    if password != body.get("confirm_password"):
        raise ValueError("Passwords do not match")
    if not 1 <= len(name) <= 100:
        raise ValueError("Display name must be 1–100 characters")
    return email, core.PH.hash(password), name


def insert_user(c, email, password_hash, name, role):
    if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
        raise ValueError("An account with this identifier already exists")
    owner = core.ident()
    c.execute(
        "INSERT INTO users VALUES(%s,%s,%s,%s)",
        (owner, email, password_hash, time.time()),
    )
    c.execute("INSERT INTO account_settings(owner,role) VALUES(%s,%s)", (owner, role))
    c.execute("INSERT INTO user_profiles(owner,name) VALUES(%s,%s)", (owner, name))
    return owner


def register(app, auth):
    # Reuse tested model, resource policy and session revocation operations.
    from .admin_routes import register as register_settings

    register_settings(app, auth)

    def owner(req):
        actor = auth(req)
        if accounts.require(actor)["role"] != "admin":
            raise HTTPException(403, "Instance owner access required")
        return actor

    @app.get("/api/setup")
    def setup_status():
        with core.db() as c:
            return {
                "required": not bool(
                    c.execute(
                        "SELECT 1 FROM users WHERE id<>'aster-installation-checks' LIMIT 1"
                    ).fetchone()
                )
            }

    @app.post("/api/setup")
    async def setup(req: Request):
        if not core.rate("setup:" + req.client.host, 10, 900):
            raise HTTPException(429, "Too many setup attempts")
        body = await req.json()
        secret = os.getenv("OWNCMD_SETUP_TOKEN", "")
        supplied = body.get("token", "") if isinstance(body, dict) else ""
        if (
            not secret
            or not isinstance(supplied, str)
            or not hmac.compare_digest(secret, supplied)
        ):
            raise HTTPException(403, "Use the setup token printed by the installer")
        email, password_hash, name = identity(body)
        with core.db() as c:
            c.begin_write()
            if c.execute(
                "SELECT 1 FROM users WHERE id<>'aster-installation-checks' LIMIT 1"
            ).fetchone():
                raise HTTPException(409, "This instance is already configured")
            actor = insert_user(c, email, password_hash, name, "admin")
            accounts.audit(c, actor, actor, "instance_initialized", {})
            c.commit()
        return {"ok": True}

    @app.get("/api/instance/providers")
    def providers(req: Request):
        owner(req)
        return integrations.public()

    @app.put("/api/instance/providers")
    async def save_providers(req: Request):
        return integrations.save(owner(req), await req.json())

    @app.post("/api/instance/invites")
    async def invite(req: Request):
        actor = owner(req)
        body = await req.json()
        if not isinstance(body, dict):
            raise ValueError("A JSON object is required")
        email = integrations.email_address(body.get("email", ""))
        token = secrets.token_urlsafe(32)
        now = time.time()
        with core.db() as c:
            c.begin_write()
            accounts.guard_admin(c, actor)
            if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
                raise ValueError("Account already exists")
            c.execute(
                "DELETE FROM community_invites WHERE email=%s OR expires<%s",
                (email, now),
            )
            c.execute(
                "INSERT INTO community_invites VALUES(%s,%s,%s,%s,%s)",
                (core.digest(token), email, actor, now + 86400, now),
            )
            accounts.audit(c, actor, email, "member_invited", {})
            c.commit()
        # Fragment keeps the token out of HTTP request logs and referrers.
        return {"url": core.ORIGIN + "/#invite=" + token, "expires": now + 86400}

    @app.delete("/api/instance/invites")
    async def revoke_invites(req: Request):
        actor = owner(req)
        with core.db() as c:
            c.begin_write()
            accounts.guard_admin(c, actor)
            c.execute("DELETE FROM community_invites")
            accounts.audit(c, actor, "instance", "invitations_revoked", {})
            c.commit()
        return {"ok": True}

    @app.post("/api/invite/accept")
    async def accept(req: Request):
        if not core.rate("invite:" + req.client.host, 10, 900):
            raise HTTPException(429, "Too many invitation attempts")
        body = await req.json()
        email, password_hash, name = identity(body)
        token = body.get("token", "")
        if not isinstance(token, str) or len(token) > 200:
            raise ValueError("Invalid invitation")
        with core.db() as c:
            c.begin_write()
            invitation = c.execute(
                "SELECT * FROM community_invites WHERE token=%s AND expires>%s",
                (core.digest(token), time.time()),
            ).fetchone()
            if not invitation or invitation["email"] != email:
                raise ValueError(
                    "Invitation is invalid, expired, or for a different email"
                )
            accounts.guard_admin(c, invitation["creator"])
            actor = insert_user(c, email, password_hash, name, "user")
            c.execute(
                "DELETE FROM community_invites WHERE token=%s", (core.digest(token),)
            )
            accounts.audit(c, actor, actor, "invitation_accepted", {})
            c.commit()
        return {"ok": True}
