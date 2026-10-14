"""Community provider-cost accounting (no payments, wallet, or markup). Reservations are not charges; transactions are append-only.

All limit decisions and settlements serialize with PostgreSQL transaction advisory locks. No
task foreign key: deleting a conversation must never delete its usage history.
"""

import json, os, time, csv, io
from decimal import Decimal, ROUND_CEILING, InvalidOperation

SCALE = 1_000_000_000
MARKUP = 1


class CreditError(ValueError):
    pass


def nanos(value):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid monetary amount")
    if not d.is_finite() or d < 0 or d > Decimal("1000000"):
        raise ValueError("Invalid monetary amount")
    return int((d * SCALE).to_integral_value(rounding=ROUND_CEILING))


def usd(value):
    return float(value) / SCALE


def initialize(c):
    c.execute_schema("""
 CREATE TABLE IF NOT EXISTS usage_operations(
  id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,service TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,hold_nano BIGINT NOT NULL,
  cost_nano BIGINT,charge_nano BIGINT,provider_id TEXT,metadata TEXT NOT NULL DEFAULT '{}',
  created DOUBLE PRECISION NOT NULL,updated DOUBLE PRECISION NOT NULL);
 CREATE INDEX IF NOT EXISTS usage_owner ON usage_operations(owner,created);
 CREATE UNIQUE INDEX IF NOT EXISTS usage_provider ON usage_operations(service,provider_id)
  WHERE provider_id IS NOT NULL AND provider_id<>'';
 CREATE TABLE IF NOT EXISTS usage_adjustments(id TEXT PRIMARY KEY,operation TEXT NOT NULL,old_cost_nano BIGINT,new_cost_nano BIGINT NOT NULL,reference TEXT NOT NULL,created DOUBLE PRECISION NOT NULL);
 CREATE TABLE IF NOT EXISTS runtime_meters(
  name TEXT PRIMARY KEY,task TEXT NOT NULL,kind TEXT NOT NULL,operation TEXT NOT NULL,
  started DOUBLE PRECISION NOT NULL,expires DOUBLE PRECISION NOT NULL,rate TEXT NOT NULL);
 """)
    # A community database has no wallet or welcome-credit trigger.
    c.execute("DROP TRIGGER IF EXISTS welcome_credit ON users")
    c.execute("DROP FUNCTION IF EXISTS aster_welcome_credit()")


def require_credit(owner):
    """Compatibility entry point: only account access is checked, never a balance."""
    from . import accounts

    accounts.require(owner)


def reserve(owner, task, amount, service="model", model="", metadata=None):
    from . import accounts

    hold = nanos(amount)
    now = time.time()
    rid = core.ident()
    with core.db() as c:
        c.begin_write()
        policy = accounts.require(owner, c=c)
        if not c.execute("SELECT 1 FROM users WHERE id=%s", (owner,)).fetchone():
            raise ValueError("Account not found")
        held = c.execute(
            "SELECT coalesce(sum(hold_nano),0) FROM usage_operations WHERE owner=%s AND status IN ('reserved','pending')",
            (owner,),
        ).fetchone()[0]
        cap = policy["limits"].get("daily_spend_usd", 0)
        if cap:
            spent = c.execute(
                "SELECT coalesce(sum(charge_nano),0) FROM usage_operations WHERE owner=%s AND created>=%s",
                (owner, int(now) // 86400 * 86400),
            ).fetchone()[0]
            if spent + held + hold > cap * SCALE:
                raise CreditError(
                    "Daily spending limit reached. Work is paused until the next UTC day or an administrator raises the limit."
                )
        c.execute(
            "INSERT INTO usage_operations(id,owner,task,service,model,status,hold_nano,metadata,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                rid,
                owner,
                task,
                service,
                model,
                "reserved",
                hold,
                json.dumps(metadata or {}),
                now,
                now,
            ),
        )
        c.commit()
    return rid


def record(rid, provider_id=None, metadata=None, pending=False):
    with core.db() as c:
        c.begin_write()
        r = c.execute("SELECT * FROM usage_operations WHERE id=%s", (rid,)).fetchone()
        if not r:
            return
        data = json.loads(r["metadata"])
        data.update(metadata or {})
        # Never replace the first generation id: it is the reconciliation identity.
        pid = r["provider_id"] or (str(provider_id)[:200] if provider_id else None)
        if (
            pid
            and c.execute(
                "SELECT 1 FROM usage_operations WHERE service=%s AND provider_id=%s AND id<>%s",
                (r["service"], pid, rid),
            ).fetchone()
        ):
            data["duplicate_provider_id"] = pid
            pid = r["provider_id"]
        c.execute(
            "UPDATE usage_operations SET provider_id=%s,metadata=%s,status=%s,updated=%s WHERE id=%s",
            (
                pid,
                json.dumps(data),
                "pending" if pending and r["status"] == "reserved" else r["status"],
                time.time(),
                rid,
            ),
        )
        c.commit()


def settle(rid, actual, metadata=None, provider_id=None):
    if actual is None:
        record(rid, provider_id, metadata, pending=True)
        return
    cost = nanos(actual)
    now = time.time()
    with core.db() as c:
        c.begin_write()
        r = c.execute("SELECT * FROM usage_operations WHERE id=%s", (rid,)).fetchone()
        if not r or r["status"] == "settled":
            return
        data = json.loads(r["metadata"])
        data.update(metadata or {})
        pid = r["provider_id"] or (str(provider_id)[:200] if provider_id else None)
        other = (
            c.execute(
                "SELECT id,status FROM usage_operations WHERE service=%s AND provider_id=%s AND id<>%s",
                (r["service"], pid, rid),
            ).fetchone()
            if pid
            else None
        )
        if other or data.get("duplicate_provider_id"):
            data["duplicate_of"] = (
                other["id"] if other else data["duplicate_provider_id"]
            )
            cost = 0
            pid = r["provider_id"]
        charge = cost
        # Record upstream overruns faithfully; estimates are not provider hard caps.
        c.execute(
            "UPDATE usage_operations SET status=%s,cost_nano=%s,charge_nano=%s,provider_id=%s,metadata=%s,updated=%s WHERE id=%s",
            ("settled", cost, charge, pid, json.dumps(data), now, rid),
        )
        c.commit()


def runtime_rate(kind):
    return Decimal(
        os.getenv(
            "ASTER_" + ("BROWSER" if kind == "browser" else "CODE") + "_COST_PER_HOUR",
            "0",
        )
    )


def start_runtime(name, task, kind):
    with core.db() as c:
        existing = c.execute(
            "SELECT * FROM runtime_meters WHERE name=%s", (name,)
        ).fetchone()
        owner = c.execute("SELECT owner FROM tasks WHERE id=%s", (task,)).fetchone()
    if not owner:
        raise CreditError("Workspace account is unavailable")
    if existing:
        if existing["expires"] > time.time():
            return
        stop_runtime(name)
    now = existing["expires"] if existing else time.time()
    rate = runtime_rate(kind)
    rid = reserve(
        owner["owner"],
        task,
        rate / Decimal(60),
        kind,
        metadata={"rate_per_hour": str(rate), "basis": "allocated_runtime"},
    )
    with core.db() as c:
        c.execute(
            "INSERT INTO runtime_meters VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (name, task, kind, rid, now, now + 60, str(rate)),
        )


def stop_runtime(name, now=None):
    with core.db() as c:
        r = c.execute("SELECT * FROM runtime_meters WHERE name=%s", (name,)).fetchone()
    if not r:
        return
    seconds = max(
        0, min(now if now is not None else time.time(), r["expires"]) - r["started"]
    )
    settle(
        r["operation"],
        Decimal(str(seconds)) * Decimal(r["rate"]) / 3600,
        {"seconds": seconds, "rate_per_hour": r["rate"], "basis": "allocated_runtime"},
    )
    with core.db() as c:
        c.execute(
            "DELETE FROM runtime_meters WHERE name=%s AND operation=%s",
            (name, r["operation"]),
        )


def activity(
    owner,
    days=30,
    offset=0,
    service="all",
    limit=50,
    status="all",
    mode="all",
    query="",
    start_date="",
    end_date="",
    sort="newest",
    min_charge="",
    max_charge="",
    model="all",
    provider="all",
    task="",
    min_tokens="",
    max_tokens="",
):
    from datetime import datetime, timezone

    days = max(1, min(366, int(days)))
    offset = max(0, int(offset))
    limit = max(1, min(1000, int(limit)))
    today = int(time.time()) // 86400 * 86400
    start = today - (days - 1) * 86400
    end = today + 86400
    try:
        if start_date:
            start = int(
                datetime.strptime(start_date, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        if end_date:
            end = (
                int(
                    datetime.strptime(end_date, "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                + 86400
            )
    except ValueError:
        raise ValueError("Use valid dates in YYYY-MM-DD format")
    if end <= start or end - start > 366 * 86400:
        raise ValueError("Choose a date range between 1 and 366 days")
    days = int((end - start) / 86400)
    # Normalize once, and use the expression (not an ambiguous SQL alias) for
    # filters, rows and aggregation. Legacy operations may outlive their task.
    public_mode = "CASE WHEN (u.metadata::jsonb->>'mode') IN ('chat','work') THEN (u.metadata::jsonb->>'mode') WHEN t.mode IN ('chat','work') THEN t.mode ELSE 'work' END"
    category_mode = (
        "CASE WHEN u.service='model' THEN (" + public_mode + ") ELSE 'all' END"
    )
    # None is reserved for the admin-only aggregate endpoint. Public routes always
    # pass their authenticated owner; no query string can select this scope.
    owner_sql = "owner=%s AND " if owner is not None else ""
    owner_args = [owner] if owner is not None else []
    where = (
        "u.owner=%s AND " if owner is not None else ""
    ) + "u.created>=%s AND u.created<%s"
    args = [*owner_args, start, end]
    if service != "all":
        where += " AND u.service=%s"
        args.append(service)
    if mode != "all":
        where += " AND (" + public_mode + ")=%s"
        args.append(mode)
    if status == "provisional":
        where += (
            " AND coalesce(u.metadata::jsonb->>'provisional','false') IN ('true','1')"
        )
    elif status != "all":
        where += " AND u.status=%s"
        args.append(status)
    query = str(query).strip()[:120]
    if query:
        where += " AND (strpos(lower(coalesce(t.title,'')),lower(%s))>0 OR strpos(u.task,%s)>0 OR strpos(u.id,%s)>0)"
        args.extend([query, query, query])
    if min_charge != "" and max_charge != "" and nanos(min_charge) > nanos(max_charge):
        raise ValueError("Minimum charge cannot exceed maximum charge")
    if min_charge != "":
        where += " AND u.charge_nano>=%s"
        args.append(nanos(min_charge))
    if max_charge != "":
        where += " AND u.charge_nano<=%s"
        args.append(nanos(max_charge))
    if model != "all":
        where += " AND u.model=%s"
        args.append(str(model)[:300])
    if provider != "all":
        where += " AND split_part(u.model,'/',1)=%s"
        args.append(str(provider)[:100])
    if task:
        where += " AND u.task=%s"
        args.append(str(task)[:100])
    token_sql = "(coalesce((u.metadata::jsonb->>'prompt_tokens')::bigint,0)+coalesce((u.metadata::jsonb->>'completion_tokens')::bigint,0))"
    for value, op in ((min_tokens, ">="), (max_tokens, "<=")):
        if value != "":
            try:
                count = int(value)
            except (ValueError, TypeError):
                raise ValueError("Token limits must be whole numbers")
            if not 0 <= count <= 10**12:
                raise ValueError("Token limit is out of range")
            where += " AND " + token_sql + op + "%s"
            args.append(count)
    if min_tokens != "" and max_tokens != "" and int(min_tokens) > int(max_tokens):
        raise ValueError("Minimum tokens cannot exceed maximum tokens")
    source = "usage_operations u LEFT JOIN tasks t ON t.id=u.task AND t.owner=u.owner"
    order = {
        "newest": "u.created DESC,u.id DESC",
        "oldest": "u.created ASC,u.id ASC",
        "highest": "u.charge_nano DESC NULLS LAST,u.created DESC,u.id DESC",
        "lowest": "u.charge_nano ASC NULLS FIRST,u.created DESC,u.id DESC",
    }.get(sort, "u.created DESC,u.id DESC")
    with core.db() as c:
        c.begin_read()
        total = c.execute(
            "SELECT count(*) FROM " + source + " WHERE " + where, args
        ).fetchone()[0]
        offset = min(offset, max(0, ((total - 1) // limit) * limit))
        rows = c.execute(
            "SELECT u.*,t.title conversation,"
            + public_mode
            + " public_mode FROM "
            + source
            + " WHERE "
            + where
            + " ORDER BY "
            + order
            + " LIMIT %s OFFSET %s",
            (*args, limit, offset),
        ).fetchall()
        totals = dict(
            c.execute(
                "SELECT coalesce(sum(u.charge_nano),0) charge,count(*) requests,"
                + ",".join(
                    "coalesce(sum((u.metadata::jsonb->>'"
                    + k
                    + "')::double precision),0) "
                    + label
                    for k, label in [
                        ("prompt_tokens", "input_tokens"),
                        ("completion_tokens", "output_tokens"),
                        ("cached_tokens", "cached_tokens"),
                        ("reasoning_tokens", "reasoning_tokens"),
                        ("seconds", "seconds"),
                    ]
                )
                + " FROM "
                + source
                + " WHERE "
                + where,
                args,
            ).fetchone()
        )
        daily = [
            dict(r)
            for r in c.execute(
                "SELECT FLOOR(u.created/86400)::bigint*86400 AS day,coalesce(sum(u.charge_nano),0) charge,count(*) requests FROM "
                + source
                + " WHERE "
                + where
                + " GROUP BY day ORDER BY day",
                args,
            )
        ]
        breakdown = [
            dict(r)
            for r in c.execute(
                "SELECT u.service,"
                + category_mode
                + " mode,coalesce(sum(u.charge_nano),0) charge,count(*) requests FROM "
                + source
                + " WHERE "
                + where
                + " GROUP BY u.service,"
                + category_mode
                + " ORDER BY charge DESC,u.service,2",
                args,
            )
        ]
        model_breakdown = [
            dict(r)
            for r in c.execute(
                "SELECT u.model,"
                + public_mode
                + " mode,coalesce(sum(u.charge_nano),0) charge,count(*) requests,"
                + ",".join(
                    "coalesce(sum((u.metadata::jsonb->>'"
                    + k
                    + "')::double precision),0) "
                    + label
                    for k, label in [
                        ("prompt_tokens", "input_tokens"),
                        ("completion_tokens", "output_tokens"),
                        ("cached_tokens", "cached_tokens"),
                        ("reasoning_tokens", "reasoning_tokens"),
                    ]
                )
                + " FROM "
                + source
                + " WHERE "
                + where
                + " AND u.model<>'' GROUP BY u.model,"
                + public_mode
                + " ORDER BY charge DESC,u.model,mode",
                args,
            )
        ]
        facets = [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT model FROM usage_operations WHERE "
                + owner_sql
                + "model<>'' ORDER BY model",
                owner_args,
            )
        ]
        account_created = (
            c.execute("SELECT created FROM users WHERE id=%s", (owner,)).fetchone()[0]
            if owner is not None
            else c.execute(
                "SELECT coalesce(min(created),%s) FROM users", (time.time(),)
            ).fetchone()[0]
        )
        forecast_start = max(time.time() - 30 * 86400, account_created)
        recent = c.execute(
            "SELECT coalesce(sum(charge_nano),0),count(*) FROM usage_operations WHERE "
            + owner_sql
            + "created>=%s AND status='settled'",
            (*owner_args, forecast_start),
        ).fetchone()
    result = []
    for r in rows:
        m = json.loads(r["metadata"])
        result.append(
            {
                "id": r["id"],
                "task": r["task"],
                "conversation": r["conversation"]
                or (
                    "Temporary chat"
                    if str(r["task"]).startswith("tmp-")
                    else "Deleted conversation"
                ),
                "service": r["service"],
                "model": r["model"],
                "provider": r["model"].split("/")[0] if r["model"] else "",
                "mode": r["public_mode"],
                "status": r["status"],
                "created": r["created"],
                "charge": (
                    usd(r["charge_nano"]) if r["charge_nano"] is not None else None
                ),
                "reserved": usd(r["hold_nano"]),
                "metadata": {
                    k: m[k]
                    for k in (
                        "prompt_tokens",
                        "completion_tokens",
                        "cached_tokens",
                        "reasoning_tokens",
                        "seconds",
                        "result_count",
                        "provisional",
                    )
                    if k in m
                },
            }
        )
    for x in daily + breakdown + model_breakdown:
        x["charge"] = usd(x["charge"])
    totals["charge"] = usd(totals["charge"])
    observed = max(1, (time.time() - forecast_start) / 86400)
    projected = usd(recent[0]) / observed * 30
    return {
        "currency": "USD",
        "days": days,
        "start": start,
        "end": end,
        "total": total,
        "offset": offset,
        "limit": limit,
        "rows": result,
        "totals": totals,
        "daily": daily,
        "breakdown": breakdown,
        "models": model_breakdown,
        "facets": {
            "models": facets,
            "providers": sorted({m.split("/")[0] for m in facets}),
        },
        "forecast": {
            "amount": projected,
            "observed_days": round(observed, 1),
            "sample_count": recent[1],
            "daily_average": projected / 30,
        },
    }


def export_csv(owner, days=30, service="all", **filters):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "UTC",
            "Operation",
            "Conversation ID",
            "Conversation",
            "Service",
            "Mode",
            "Model",
            "Provider",
            "Status",
            "Provider cost USD",
            "Estimated pending USD",
            "Provisional",
            "Input tokens",
            "Output tokens",
            "Cached tokens",
            "Reasoning tokens",
            "Runtime seconds",
        ]
    )
    offset = 0
    while True:
        data = activity(owner, days, offset, service, 1000, **filters)
        batch = data["rows"]
        for r in batch:
            m = r["metadata"]
            values = [
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["created"])),
                r["id"],
                r["task"],
                r["conversation"],
                r["service"],
                r["mode"],
                r["model"],
                r["provider"],
                r["status"],
                r["charge"],
                r["reserved"],
                bool(m.get("provisional")),
                m.get("prompt_tokens", 0),
                m.get("completion_tokens", 0),
                m.get("cached_tokens", 0),
                m.get("reasoning_tokens", 0),
                m.get("seconds", 0),
            ]
            w.writerow(
                [
                    (
                        "'" + v
                        if isinstance(v, str)
                        and v.startswith(("=", "+", "-", "@", "\t", "\r"))
                        else v
                    )
                    for v in values
                ]
            )
        offset += len(batch)
        if len(batch) < 1000 or offset >= data["total"]:
            break
    return out.getvalue()


from . import core


def reconcile_operation(rid, actual, reference):
    """Operator-only provider-cost correction with an immutable adjustment record."""
    if not isinstance(reference, str) or len(reference.strip()) < 8:
        raise ValueError(
            "Supply an invoice or provider evidence reference (at least 8 characters)"
        )
    cost = nanos(actual)
    with core.db() as c:
        c.begin_write()
        r = c.execute("SELECT * FROM usage_operations WHERE id=%s", (rid,)).fetchone()
        if not r:
            raise ValueError("Unknown usage operation")
        # Retrying a correction must not duplicate the adjustment record.
        key = core.digest(rid + ":" + str(cost) + ":" + reference)
        if c.execute("SELECT 1 FROM usage_adjustments WHERE id=%s", (key,)).fetchone():
            return
        charge = cost
        delta = (r["charge_nano"] or 0) - charge
        meta = json.loads(r["metadata"])
        meta.update(
            provisional=False,
            reconciled=True,
            reconciliation_reference=reference,
            cost_basis="Operator-verified provider billing",
        )
        c.execute(
            "INSERT INTO usage_adjustments VALUES(%s,%s,%s,%s,%s,%s)",
            (key, rid, r["cost_nano"], cost, reference, time.time()),
        )

        c.execute(
            "UPDATE usage_operations SET cost_nano=%s,charge_nano=%s,status='settled',metadata=%s,updated=%s WHERE id=%s",
            (cost, charge, json.dumps(meta), time.time(), rid),
        )
        c.commit()
