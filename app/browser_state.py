"""Owner-scoped encrypted browser state. Never returned to UI or model tools."""

import json, time
from . import core

EMPTY = {"cookies": [], "origins": []}


def init():
    with core.db() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS browser_profiles(owner TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, body TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL)"
        )


def load(owner):
    init()
    with core.db() as c:
        r = c.execute(
            "SELECT body,updated FROM browser_profiles WHERE owner=%s", (owner,)
        ).fetchone()
    if not r or time.time() - r["updated"] > 30 * 86400:
        return {"cookies": [], "origins": []}
    return json.loads(core.dec(r["body"]))


def merge(base, current, latest):
    result = {}
    for group, key in [
        ("cookies", lambda x: (x["domain"], x["path"], x["name"])),
        ("origins", lambda x: x["origin"]),
    ]:
        old = {key(x): x for x in base.get(group, [])}
        new = {key(x): x for x in current.get(group, [])}
        saved = {key(x): x for x in latest.get(group, [])}
        for k in old.keys() - new.keys():
            if saved.get(k) == old[k]:
                saved.pop(k, None)
        for k, v in new.items():
            if old.get(k) != v:
                saved[k] = v
        result[group] = list(saved.values())
    return result


def save(owner, base, current):
    if len(json.dumps(current)) > 8 * 1024 * 1024:
        raise ValueError("Browser session storage exceeds 8 MB")
    init()
    with core.db() as c:
        c.begin_write()
        r = c.execute(
            "SELECT body,updated FROM browser_profiles WHERE owner=%s", (owner,)
        ).fetchone()
        merged = merge(
            base,
            current,
            (
                json.loads(core.dec(r["body"]))
                if r and time.time() - r["updated"] <= 30 * 86400
                else EMPTY
            ),
        )
        if len(json.dumps(merged)) > 8 * 1024 * 1024:
            raise ValueError("Combined browser session storage exceeds 8 MB")
        c.execute(
            "INSERT INTO browser_profiles VALUES(%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET body=excluded.body,updated=excluded.updated",
            (owner, core.enc(json.dumps(merged)), time.time()),
        )
        c.commit()
    return current


def clear(owner):
    init()
    with core.db() as c:
        c.execute("DELETE FROM browser_profiles WHERE owner=%s", (owner,))
