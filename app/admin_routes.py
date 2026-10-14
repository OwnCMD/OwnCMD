import asyncio, json, time
from fastapi import Request, HTTPException
from . import accounts, core, billing, providers


async def payload(req):
    b = await req.json()
    if not isinstance(b, dict):
        raise ValueError("A JSON object is required")
    return b


def register(app, auth):
    def admin(req):
        owner = auth(req)
        if accounts.require(owner)["role"] != "admin":
            raise HTTPException(403, "Administrator access required")
        return owner

    @app.get("/api/models")
    async def user_models(req: Request):
        owner = auth(req)
        p = accounts.require(owner)
        try:
            catalog = await asyncio.wait_for(providers.catalog(), 3)
        except Exception:
            catalog = {}
        overrides = accounts.account(owner)["overrides"].get("models", {})
        return {
            mode: {
                "enabled": p["features"][mode],
                "source": "account" if mode in overrides else "global",
                "auto": p["models"][mode]["auto"],
                "models": [
                    {
                        "id": id,
                        "name": catalog.get(id, {}).get("name", id),
                        "vision": "image"
                        in catalog.get(id, {})
                        .get("architecture", {})
                        .get("input_modalities", []),
                    }
                    for id in p["models"][mode]["allowed"]
                ],
            }
            for mode in ("chat", "work")
        }

    @app.get("/api/admin/settings")
    def settings(req: Request):
        admin(req)
        return {
            **accounts.global_policy(),
            "markup": billing.MARKUP,
            "limit_ranges": accounts.LIMITS,
        }

    @app.put("/api/admin/settings")
    async def save_settings(req: Request):
        actor = admin(req)
        b = await payload(req)
        p = await accounts.validate_policy(b.get("policy"))
        return accounts.save_global(actor, p, b.get("version"))

    @app.get("/api/admin/code-network/{scope}")
    def network_policy(req: Request, scope: str):
        admin(req)
        from . import code_network

        if scope != "global":
            with core.db() as c:
                if not c.execute(
                    "SELECT id FROM users WHERE id=%s", (scope,)
                ).fetchone():
                    raise HTTPException(404, "Account not found")
        return {
            **code_network.read(scope),
            "effective": code_network.effective(scope),
            "defaults": code_network.defaults(),
            "transport": "HTTP/HTTPS and TCP CONNECT via the sandbox proxy",
            "revocation_seconds": 1,
        }

    @app.put("/api/admin/code-network/{scope}")
    async def save_network(req: Request, scope: str):
        actor = admin(req)
        b = await payload(req)
        from . import code_network

        try:
            result = code_network.save(actor, scope, b.get("policy"), b.get("version"))
        except ValueError as e:
            raise HTTPException(409 if "changed elsewhere" in str(e) else 400, str(e))
        return {**result, "effective": code_network.effective(scope)}

    @app.get("/api/admin/models")
    async def models(req: Request):
        admin(req)
        rows = await providers.catalog()
        return [
            {
                "id": id,
                "name": m.get("name", id),
                "context": m.get("context_length"),
                "vision": "image"
                in m.get("architecture", {}).get("input_modalities", []),
                "pricing": m.get("pricing", {}),
            }
            for id, m in rows.items()
            if "tools" in m.get("supported_parameters", [])
        ]

    @app.get("/api/admin/users")
    def users(
        req: Request,
        q: str = "",
        offset: int = 0,
        role: str = "all",
        status: str = "all",
    ):
        admin(req)
        offset = max(0, offset)
        where = "strpos(lower(u.email),lower(%s))>0"
        args = [q[:200]]
        if role in ("user", "admin"):
            where += " AND coalesce(a.role,'user')=%s"
            args.append(role)
        if status in ("active", "suspended"):
            where += " AND coalesce(a.disabled,FALSE)=%s"
            args.append(status == "suspended")
        with core.db() as c:
            rows = c.execute(
                "SELECT u.id,u.email,u.created,coalesce(a.role,'user') AS role,coalesce(a.disabled,FALSE) AS disabled FROM users u LEFT JOIN account_settings a ON a.owner=u.id WHERE "
                + where
                + " ORDER BY u.created DESC,u.id LIMIT 51 OFFSET %s",
                (*args, offset),
            ).fetchall()
        return {
            "users": [dict(x) for x in rows[:50]],
            "next_offset": offset + 50 if len(rows) > 50 else None,
        }

    @app.get("/api/admin/users/{owner}")
    def user(req: Request, owner: str):
        admin(req)
        with core.db() as c:
            u = c.execute(
                "SELECT id,email,created FROM users WHERE id=%s", (owner,)
            ).fetchone()
            if not u:
                raise HTTPException(404, "Account not found")
            sessions = c.execute(
                "SELECT count(*) FROM sessions WHERE owner=%s AND expires>%s",
                (owner, time.time()),
            ).fetchone()[0]
            tasks = c.execute(
                "SELECT count(*) FROM tasks WHERE owner=%s", (owner,)
            ).fetchone()[0]
        with core.db() as c:
            profile = c.execute(
                "SELECT name,country,verified FROM user_profiles WHERE owner=%s",
                (owner,),
            ).fetchone()
        return {
            **dict(u),
            "profile": dict(profile) if profile else None,
            **accounts.account(owner),
            "effective": accounts.effective(owner),
            "sessions": sessions,
            "conversations": tasks,
        }

    @app.put("/api/admin/users/{owner}")
    async def update(req: Request, owner: str):
        actor = admin(req)
        b = await payload(req)
        await accounts.validate_policy(b.get("overrides"), True)
        result = accounts.save_account(actor, owner, b)
        if b.get("disabled"):
            from .tools import broker
            from . import temporary

            temporary.discard_owner(owner)
            with core.db() as c:
                tasks = c.execute(
                    "SELECT id FROM tasks WHERE owner=%s AND id IN (SELECT task FROM runtime_meters)",
                    (owner,),
                ).fetchall()
            # The broker maintenance loop also detects suspended owners after restart.
            for task in tasks:
                try:
                    await broker(task["id"], "stop")
                except Exception:
                    pass
        return result

    @app.post("/api/admin/users/{owner}/revoke-sessions")
    def revoke(req: Request, owner: str):
        actor = admin(req)
        with core.db() as c:
            c.begin_write()
            accounts.guard_admin(c, actor)
            c.execute("DELETE FROM sessions WHERE owner=%s", (owner,))
            accounts.audit(c, actor, owner, "sessions_revoked", {})
            c.commit()
        from . import temporary

        temporary.discard_owner(owner)
        return {"ok": True}

    @app.get("/api/admin/audit")
    def audit(req: Request):
        admin(req)
        from . import audit_log

        try:
            return audit_log.query(req.query_params)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/admin/audit/export.csv")
    def audit_export(req: Request):
        admin(req)
        from . import audit_log
        from fastapi.responses import Response

        try:
            data = audit_log.query(req.query_params, export=True)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return Response(
            audit_log.export_csv(data),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="owncmd-audit.csv"',
                "Cache-Control": "no-store",
            },
        )
