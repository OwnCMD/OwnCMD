"""Account policy is enforced at execution time, not just in the model picker."""

import json, time, math
from . import core, billing

FEATURES = (
    "chat",
    "work",
    "search",
    "browser",
    "code",
    "uploads",
    "skills",
    "memory",
    "schedules",
)
LIMITS = {
    "file_mb": (1, 512, 100),
    "storage_mb": (1, 102400, 2048),
    "active_work": (1, 50, 5),
    "tasks_hour": (1, 1000, 60),
    "workspace_mb": (16, 1536, 1536),
    "workspace_files": (100, 500000, 100000),
    "daily_spend_usd": (0, 10000, 0),
}


def initialize(c):
    c.execute_schema("""
 CREATE TABLE IF NOT EXISTS admin_settings(id TEXT PRIMARY KEY,body TEXT NOT NULL,version BIGINT NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS account_settings(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,role TEXT NOT NULL DEFAULT 'user',disabled BOOLEAN NOT NULL DEFAULT FALSE,body TEXT NOT NULL DEFAULT '{}',version BIGINT NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS admin_audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,target TEXT NOT NULL,action TEXT NOT NULL,body TEXT NOT NULL,created DOUBLE PRECISION NOT NULL);
 CREATE INDEX IF NOT EXISTS admin_audit_created ON admin_audit(created);
 CREATE INDEX IF NOT EXISTS admin_audit_actor_time ON admin_audit(actor,created DESC);
 CREATE INDEX IF NOT EXISTS admin_audit_target_time ON admin_audit(target,created DESC);
 CREATE INDEX IF NOT EXISTS admin_audit_action_time ON admin_audit(action,created DESC);
 CREATE TABLE IF NOT EXISTS account_policy_provenance(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,explicit_modes TEXT[] NOT NULL);
 """)
    repair_legacy_inheritance(c)


def repair_legacy_inheritance(c):
    # Earlier account editors copied the entire effective policy into overrides.
    # Repair only copies proven by their audit history; never widen a deliberate
    # model restriction or infer intent from a model merely matching today's list.
    rows = c.execute(
        "SELECT a.* FROM account_settings a LEFT JOIN account_policy_provenance p ON p.owner=a.owner WHERE p.owner IS NULL"
    ).fetchall()
    if not rows:
        return
    changes = []
    for r in c.execute(
        "SELECT body,created FROM admin_audit WHERE target='global' AND action='policy_updated' ORDER BY created,id"
    ):
        try:
            changes.append((r["created"], json.loads(core.dec(r["body"]))))
        except Exception:
            continue
    initial = (
        changes[0][1].get("before", defaults())
        if changes
        else global_policy(c)["policy"]
    )
    for row in rows:
        body = json.loads(row["body"])
        proof = {}
        last = {}
        for event in c.execute(
            "SELECT body,created FROM admin_audit WHERE target=%s AND action='account_updated' ORDER BY created,id",
            (row["owner"],),
        ):
            try:
                d = json.loads(core.dec(event["body"]))
                after = d["after"]["overrides"]
                before = d["before"]["overrides"]
            except Exception:
                continue
            at = initial
            for ts, change in changes:
                if ts <= event["created"]:
                    at = change.get("after", at)
            copied = (
                all(section in after for section in ("models", "features", "limits"))
                and set(after.get("models", {})) == {"chat", "work"}
                and len(after.get("features", {})) >= len(FEATURES)
            )
            for mode, value in after.get("models", {}).items():
                old = before.get("models", {}).get(mode)
                if old == value and mode in proof:
                    pass
                elif old is None and copied and value == at.get("models", {}).get(mode):
                    proof[mode] = True
                else:
                    proof[mode] = False
            last = after
        repaired = [
            m
            for m, v in body.get("models", {}).items()
            if proof.get(m) and v == last.get("models", {}).get(m)
        ]
        for mode in repaired:
            body["models"].pop(mode)
        if "models" in body and not body["models"]:
            body.pop("models")
        if repaired:
            c.execute(
                "UPDATE account_settings SET body=%s,version=version+1 WHERE owner=%s",
                (json.dumps(body), row["owner"]),
            )
            audit(
                c,
                "system",
                row["owner"],
                "model_inheritance_repaired",
                {
                    "modes": repaired,
                    "reason": "Legacy full-policy copy confirmed by account/global audit history",
                },
            )
        c.execute(
            "INSERT INTO account_policy_provenance VALUES(%s,%s)",
            (row["owner"], list(body.get("models", {}))),
        )


def defaults():
    from .providers import configured_model

    return {
        "models": {
            mode: {"allowed": [configured_model(mode)], "auto": configured_model(mode)}
            for mode in ("chat", "work")
        },
        "features": {k: True for k in FEATURES},
        "limits": {k: v[2] for k, v in LIMITS.items()},
        "registration": False,
    }


def global_policy(c=None):
    if c is None:
        with core.db() as c:
            return global_policy(c)
    r = c.execute("SELECT * FROM admin_settings WHERE id='global'").fetchone()
    policy = defaults()
    if r:
        stored = json.loads(r["body"])
        for section in ("models", "features", "limits"):
            policy[section].update(stored.get(section, {}))
        policy["registration"] = False
    return {"policy": policy, "version": r["version"] if r else 0}


def account(owner, c=None):
    if c is None:
        with core.db() as c:
            return account(owner, c)
    r = c.execute("SELECT * FROM account_settings WHERE owner=%s", (owner,)).fetchone()
    return {
        "role": r["role"] if r else "user",
        "disabled": bool(r and r["disabled"]),
        "overrides": json.loads(r["body"]) if r else {},
        "version": r["version"] if r else 0,
    }


def effective(owner, c=None):
    if c is None:
        with core.db() as c:
            return effective(owner, c)
    base = global_policy(c)["policy"]
    a = account(owner, c)
    for section in ("models", "features", "limits"):
        base[section].update(a["overrides"].get(section, {}))
    return {**base, "role": a["role"], "disabled": a["disabled"]}


def require(owner, feature=None, c=None):
    p = effective(owner, c)
    if p["disabled"]:
        raise ValueError("This account is suspended. Contact your administrator.")
    if feature and not p["features"].get(feature, False):
        raise ValueError(f"{feature.title()} is disabled for this account.")
    return p


def resolve_model(owner, mode, choice="auto"):
    if mode not in ("chat", "work"):
        raise ValueError("Invalid mode")
    p = require(owner, mode)["models"][mode]
    if choice == "auto":
        return p["auto"]
    if not isinstance(choice, str) or choice not in p["allowed"]:
        raise ValueError(
            "This model is no longer available for your account. Choose Auto or an available model."
        )
    return choice


TOOL_FEATURE = {
    "search_web": "search",
    "read_web": "search",
    "browse": "browser",
    "run_code": "code",
    "write_file": "code",
    "read_file": "code",
    "list_files": "code",
    "start_service": "code",
    "test_app": "code",
    "preview": "code",
    "publish_file": "code",
    "remember": "memory",
    "recall": "memory",
    "schedule_task": "schedules",
    "read_attachment": "uploads",
    "stage_attachment": "code",
}


def check_tool(owner, name):
    require(owner, TOOL_FEATURE.get(name))
    if name == "stage_attachment":
        require(owner, "uploads")


def filter_tools(owner, tools):
    p = require(owner)
    return [
        t
        for t in tools
        if p["features"].get(TOOL_FEATURE.get(t["function"]["name"]), True)
    ]


async def validate_policy(value, partial=False):
    from .providers import catalog

    if not isinstance(value, dict) or set(value) - (
        {"models", "features", "limits"}
        if partial
        else {"models", "features", "limits", "registration"}
    ):
        raise ValueError("Invalid policy fields")
    if not partial and set(value) != {"models", "features", "limits", "registration"}:
        raise ValueError("A complete global policy is required")
    for section in ("features", "limits", "models"):
        if section in value and not isinstance(value[section], dict):
            raise ValueError("Invalid " + section)
        if not partial and section not in value:
            raise ValueError("Missing " + section)
    if set(value.get("features", {})) - set(FEATURES) or any(
        type(v) != bool for v in value.get("features", {}).values()
    ):
        raise ValueError("Invalid feature settings")
    if not partial and set(value["features"]) != set(FEATURES):
        raise ValueError("All feature settings are required")
    if "registration" in value and type(value["registration"]) != bool:
        raise ValueError("Invalid registration setting")
    if set(value.get("limits", {})) - set(LIMITS):
        raise ValueError("Invalid limits")
    for k, v in value.get("limits", {}).items():
        if type(v) != int or not LIMITS[k][0] <= v <= LIMITS[k][1]:
            raise ValueError(f"{k} must be between {LIMITS[k][0]} and {LIMITS[k][1]}")
    if not partial and set(value["limits"]) != set(LIMITS):
        raise ValueError("All limits are required")
    if set(value.get("models", {})) - {"chat", "work"}:
        raise ValueError("Invalid model mode")
    if not partial and set(value["models"]) != {"chat", "work"}:
        raise ValueError("Both model modes are required")
    models = await catalog() if value.get("models") else {}
    for mode, p in value.get("models", {}).items():
        if (
            not isinstance(p, dict)
            or set(p) != {"allowed", "auto"}
            or not isinstance(p["allowed"], list)
            or not 1 <= len(p["allowed"]) <= 50
            or any(not isinstance(x, str) for x in p["allowed"])
            or len(set(p["allowed"])) != len(p["allowed"])
            or p["auto"] not in p["allowed"]
        ):
            raise ValueError(
                "Select 1–50 unique models and an Auto default from that list"
            )
        for id in p["allowed"]:
            m = models.get(id, {})
            if not m or "tools" not in m.get("supported_parameters", []):
                raise ValueError("Model unavailable or does not support tools: " + id)
            for key in ("prompt", "completion"):
                try:
                    price = float(m["pricing"][key])
                except (KeyError, ValueError, TypeError):
                    raise ValueError("Model pricing is unavailable: " + id)
                if not math.isfinite(price) or price < 0:
                    raise ValueError("Invalid model pricing: " + id)
    return value


def audit(c, actor, target, action, body):
    c.execute(
        "INSERT INTO admin_audit VALUES(%s,%s,%s,%s,%s,%s)",
        (core.ident(), actor, target, action, core.enc(json.dumps(body)), time.time()),
    )


def guard_admin(c, actor):
    a = account(actor, c)
    if actor != "operator" and (a["role"] != "admin" or a["disabled"]):
        raise ValueError("Administrator access is no longer available")


def save_global(actor, policy, version):
    with core.db() as c:
        c.begin_write()
        guard_admin(c, actor)
        old = global_policy(c)
        if old["version"] != version:
            raise ValueError("Settings changed elsewhere. Reload before saving.")
        c.execute(
            "INSERT INTO admin_settings VALUES('global',%s,%s) ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=excluded.version",
            (json.dumps(policy), version + 1),
        )
        audit(
            c,
            actor,
            "global",
            "policy_updated",
            {"before": old["policy"], "after": policy},
        )
        c.commit()
    return global_policy()


def save_account(actor, owner, body):
    if (
        not isinstance(body, dict)
        or set(body) != {"role", "disabled", "overrides", "version"}
        or body["role"] not in ("user", "admin")
        or type(body["disabled"]) != bool
    ):
        raise ValueError("Invalid account settings")
    with core.db() as c:
        c.begin_write()
        guard_admin(c, actor)
        if not c.execute("SELECT id FROM users WHERE id=%s", (owner,)).fetchone():
            raise ValueError("Account not found")
        old = account(owner, c)
        if old["version"] != body["version"]:
            raise ValueError("Account changed elsewhere. Reload before saving.")
        if (
            old["role"] == "admin"
            and not old["disabled"]
            and (body["role"] != "admin" or body["disabled"])
        ):
            if (
                c.execute(
                    "SELECT count(*) FROM account_settings WHERE role='admin' AND disabled=FALSE"
                ).fetchone()[0]
                <= 1
            ):
                raise ValueError("Keep at least one active administrator")
        if actor == owner and body["disabled"]:
            raise ValueError("You cannot suspend your own account")
        c.execute(
            "INSERT INTO account_settings VALUES(%s,%s,%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET role=excluded.role,disabled=excluded.disabled,body=excluded.body,version=excluded.version",
            (
                owner,
                body["role"],
                body["disabled"],
                json.dumps(body["overrides"]),
                old["version"] + 1,
            ),
        )
        c.execute(
            "INSERT INTO account_policy_provenance VALUES(%s,%s) ON CONFLICT(owner) DO UPDATE SET explicit_modes=excluded.explicit_modes",
            (owner, list(body["overrides"].get("models", {}))),
        )
        if body["disabled"]:
            c.execute("DELETE FROM sessions WHERE owner=%s", (owner,))
            c.execute(
                "UPDATE tasks SET status='paused' WHERE owner=%s AND status IN ('queued','running')",
                (owner,),
            )
            c.execute("UPDATE schedules SET enabled=0 WHERE owner=%s", (owner,))
        audit(c, actor, owner, "account_updated", {"before": old, "after": body})
        c.commit()
    return account(owner)


def bootstrap(email):
    with core.db() as c:
        c.begin_write()
        u = c.execute(
            "SELECT id FROM users WHERE email=%s", (email.strip().lower(),)
        ).fetchone()
        if not u:
            raise ValueError("Register this account first")
        c.execute(
            "INSERT INTO account_settings(owner,role) VALUES(%s,'admin') ON CONFLICT(owner) DO UPDATE SET role='admin',disabled=FALSE,version=account_settings.version+1",
            (u["id"],),
        )
        audit(c, "operator", u["id"], "admin_granted", {})
        c.commit()
