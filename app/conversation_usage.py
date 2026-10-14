"""Content-free, all-time usage aggregates scoped to one owned conversation."""

from . import core, billing


def summary(owner, task):
    with core.db() as c:
        groups = c.execute(
            "SELECT model,service,status,count(*) requests,coalesce(sum(charge_nano),0) charge,coalesce(sum(CASE WHEN status IN ('reserved','pending') THEN hold_nano ELSE 0 END),0) reserved,coalesce(sum((metadata::jsonb->>'seconds')::double precision),0) seconds,"
            + ",".join(
                "coalesce(sum((metadata::jsonb->>'" + k + "')::bigint),0) " + alias
                for k, alias in [
                    ("prompt_tokens", "input_tokens"),
                    ("completion_tokens", "output_tokens"),
                    ("cached_tokens", "cached_tokens"),
                    ("reasoning_tokens", "reasoning_tokens"),
                ]
            )
            + " FROM usage_operations WHERE owner=%s AND task=%s GROUP BY model,service,status ORDER BY charge DESC,model,service,status",
            (owner, task),
        ).fetchall()
    rows = [
        {
            **dict(r),
            "charge": billing.usd(r["charge"]),
            "reserved": billing.usd(r["reserved"]),
        }
        for r in groups
    ]
    totals = {
        k: sum(r[k] for r in rows)
        for k in (
            "requests",
            "charge",
            "reserved",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "reasoning_tokens",
            "seconds",
        )
    }
    models = {}
    services = {}
    for r in rows:
        service = services.setdefault(
            r["service"], {"service": r["service"], **{k: 0 for k in totals}}
        )
        for k in totals:
            service[k] += r[k]
        if r["model"]:
            m = models.setdefault(
                r["model"], {"model": r["model"], **{k: 0 for k in totals}}
            )
            for k in totals:
                m[k] += r[k]
    return {
        "totals": totals,
        "models": list(models.values()),
        "services": list(services.values()),
        "details": rows,
        "currency": "USD",
    }
