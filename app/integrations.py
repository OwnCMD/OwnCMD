"""Encrypted provider credentials shared live by the API, worker and broker.

Only instance owners may update credentials. Blank input retains a value;
explicit removal also masks any environment fallback. Secrets never appear in
GET responses, audit details or member APIs.
"""

import json
import os
import re
from . import core, accounts

SECRETS = {"openrouter_key", "exa_key"}
ENV_KEYS = {"openrouter_key": "OPENROUTER_API_KEY", "exa_key": "EXA_API_KEY"}


def initialize(c):
    c.execute_schema("""
    CREATE TABLE IF NOT EXISTS integration_settings(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS user_profiles(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,country TEXT NOT NULL DEFAULT '',verified DOUBLE PRECISION NOT NULL DEFAULT 0,first_name TEXT NOT NULL DEFAULT '',last_name TEXT NOT NULL DEFAULT '');
    """)


def read(c=None):
    if c is None:
        with core.db() as conn:
            return read(conn)
    row = c.execute(
        "SELECT body,version FROM integration_settings WHERE id=1"
    ).fetchone()
    return (json.loads(core.dec(row["body"])), row["version"]) if row else ({}, 0)


def credential(name):
    field = {v: k for k, v in ENV_KEYS.items()}[name]
    settings, _ = read()
    return settings[field] if field in settings else os.getenv(name, "")


def email_address(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[^\s@<>]{1,100}@[^\s@.<>]+\.[^\s@<>]{2,100}", value
    ):
        raise ValueError("Use a valid email address as your login identifier")
    return value.strip().lower()


def public():
    settings, version = read()
    return {
        "version": version,
        "credentials": {
            field: {
                "configured": bool(
                    settings.get(field) if field in settings else os.getenv(env, "")
                ),
                "source": (
                    "Instance settings" if field in settings else "Server environment"
                ),
            }
            for field, env in ENV_KEYS.items()
        },
    }


def save(actor, body):
    if not isinstance(body, dict) or not isinstance(body.get("settings"), dict):
        raise ValueError("Settings are required")
    changes = body["settings"]
    if set(changes) - SECRETS:
        raise ValueError("Unknown provider setting")
    remove = body.get("remove", [])
    if not isinstance(remove, list) or any(x not in SECRETS for x in remove):
        raise ValueError("Unknown credential removal")
    with core.db() as c:
        c.begin_write()
        accounts.guard_admin(c, actor)
        settings, version = read(c)
        if body.get("version") != version:
            raise ValueError("Settings changed elsewhere. Reload before saving.")
        for key, value in changes.items():
            if (
                not isinstance(value, str)
                or len(value) > 4096
                or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)
            ):
                raise ValueError("Invalid credential format")
            if value:
                settings[key] = value
        for key in remove:
            settings[key] = ""
        c.execute(
            "INSERT INTO integration_settings VALUES(1,%s,%s) ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=excluded.version",
            (core.enc(json.dumps(settings)), version + 1),
        )
        accounts.audit(
            c,
            actor,
            "integrations",
            "providers_updated",
            {"fields": sorted(changes), "removed": remove},
        )
        c.commit()
    return public()
