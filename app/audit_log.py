"""Administrator-only audit queries. Bodies remain encrypted and are decrypted per page."""

import csv, io, json, math, time
from . import core

CATEGORIES = {
    "access": ("account_updated", "admin_granted", "sessions_revoked"),
    "billing": ("credit_adjusted",),
    "policy": ("policy_updated", "code_network_updated", "model_inheritance_repaired"),
    "support": ("support_created", "support_reply", "support_note", "support_updated"),
    "knowledge": ("knowledge_saved",),
}


def category(action):
    return next((k for k, v in CATEGORIES.items() if action in v), "operations")


def query(params, export=False):
    def number(key, default):
        try:
            v = float(params.get(key) or default)
        except (ValueError, TypeError):
            raise ValueError("Invalid audit " + key)
        if not math.isfinite(v) or v < 0:
            raise ValueError("Invalid audit " + key)
        return v

    offset_value = number("offset", 0)
    limit_value = number("limit", 25)
    if (
        not offset_value.is_integer()
        or offset_value > 10000000
        or not limit_value.is_integer()
        or limit_value > 100
    ):
        raise ValueError("Invalid audit pagination")
    offset = int(offset_value)
    limit = max(10, int(limit_value))
    start = number("from", 0)
    end = number("to", time.time())
    snapshot = min(number("snapshot", time.time()), time.time())
    if start > end:
        raise ValueError("Start time must be before end time")
    order = params.get("sort", "newest")
    if order not in ("newest", "oldest"):
        raise ValueError("Invalid audit order")
    where = ["a.created >= %s", "a.created <= %s", "a.created <= %s"]
    args = [start, end, snapshot]
    for key in ("actor", "target", "action"):
        val = params.get(key, "")
        if val:
            where.append("a." + key + "=%s")
            args.append(val[:200])
    q = str(params.get("q", "")).strip()[:200]
    if q:
        where.append(
            "strpos(lower(concat_ws(' ',a.id,a.actor,a.target,a.action,u.email,t.email)),lower(%s))>0"
        )
        args.append(q)
    group = params.get("category", "")
    if group:
        if group not in (*CATEGORIES, "operations"):
            raise ValueError("Invalid audit category")
        actions = CATEGORIES.get(
            group, tuple(a for values in CATEGORIES.values() for a in values)
        )
        where.append(
            "a.action "
            + ("NOT IN" if group == "operations" else "IN")
            + " ("
            + ",".join("%s" for _ in actions)
            + ")"
        )
        args.extend(actions)
    joined = (
        " FROM admin_audit a LEFT JOIN users u ON u.id=a.actor LEFT JOIN users t ON t.id=a.target WHERE "
        + " AND ".join(where)
    )
    sort = "ASC" if order == "oldest" else "DESC"
    with core.db() as c:
        total = c.execute("SELECT count(*)" + joined, tuple(args)).fetchone()[0]
        if export and total > 10000:
            raise ValueError(
                "Export matches more than 10,000 events. Narrow the filters first."
            )
        rows = c.execute(
            "SELECT a.*,u.email actor_email,t.email target_email"
            + joined
            + " ORDER BY a.created "
            + sort
            + ",a.id "
            + sort
            + " LIMIT %s OFFSET %s",
            (*args, 10000 if export else limit, 0 if export else offset),
        ).fetchall()
        actions = [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT action FROM admin_audit ORDER BY action"
            )
        ]
    events = []
    for r in rows:
        d = dict(r)
        d["body"] = json.loads(core.dec(d["body"]))
        d["category"] = category(d["action"])
        events.append(d)
    return dict(
        events=events,
        total=total,
        offset=offset,
        limit=limit,
        next_offset=offset + limit if offset + limit < total else None,
        snapshot=snapshot,
        actions=actions,
        categories=list(CATEGORIES) + ["operations"],
    )


def export_csv(data):
    def cell(value):
        v = str(value or "")
        return "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "Event ID",
            "UTC time",
            "Action",
            "Category",
            "Actor",
            "Actor ID",
            "Target",
            "Target ID",
            "Details",
        ]
    )
    for e in data["events"]:
        writer.writerow(
            [
                cell(v)
                for v in (
                    e["id"],
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e["created"])),
                    e["action"],
                    e["category"],
                    e["actor_email"],
                    e["actor"],
                    e["target_email"],
                    e["target"],
                    json.dumps(e["body"], ensure_ascii=False),
                )
            ]
        )
    return out.getvalue()
