"""Transactional scheduling, calendar recurrence and explicit per-schedule input consent."""

import calendar, json, math, re, time, uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from . import core, billing, profile

UTC = timezone.utc
ACTIVE = ("queued", "running", "approval", "paused")


def initialize(c):
    c.execute_schema("""
 CREATE TABLE IF NOT EXISTS schedule_settings(id TEXT PRIMARY KEY REFERENCES schedules(id) ON DELETE CASCADE,body TEXT NOT NULL,version BIGINT NOT NULL DEFAULT 1,updated DOUBLE PRECISION NOT NULL,blocked TEXT NOT NULL DEFAULT '');
 CREATE TABLE IF NOT EXISTS scheduled_runs(id TEXT PRIMARY KEY,schedule TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,owner TEXT NOT NULL,task TEXT UNIQUE,due DOUBLE PRECISION NOT NULL,created DOUBLE PRECISION NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '',UNIQUE(schedule,due));
 CREATE INDEX IF NOT EXISTS scheduled_runs_schedule ON scheduled_runs(schedule,created);
 """)


def readiness(owner, prompt, schedule_id=None, connection=None):
    text = str(prompt).strip()
    if not 3 <= len(text) <= 24000:
        raise ValueError("Describe the work in 3–24,000 characters")
    lower = text.lower()
    keys = []
    questions = []
    warnings = []
    saved = profile.values(owner, connection)
    if schedule_id:
        with core.db() as c:
            prior = c.execute(
                "SELECT x.body FROM schedule_settings x JOIN schedules r ON r.id=x.id WHERE x.id=%s AND r.owner=%s",
                (schedule_id, owner),
            ).fetchone()
        if prior:
            for k, v in json.loads(core.dec(prior["body"])).get("inputs", {}).items():
                if not k.startswith("task_"):
                    saved.setdefault(k, v)
    interactive = bool(
        re.search(
            r"\b(book|buy|order|purchase|ship|checkout|register|sign.?up|apply|submit|send|email|message)\b",
            lower,
        )
    )
    if interactive:
        keys = ["full_name", "email", "phone"]
        questions.append(("task_destination", "Website or service to use", True))
        warnings.append(
            "Website sign-in, CAPTCHA, verification codes and final purchases or submissions may still need you at run time."
        )
    if re.search(r"\b(ship|deliver|buy|order|purchase)\b", lower):
        keys += [
            "shipping_line1",
            "shipping_city",
            "shipping_region",
            "shipping_postal",
            "shipping_country",
        ]
    if re.search(r"\b(book|reserve|flight|hotel|appointment)\b", lower):
        questions += [
            ("task_booking", "Dates, destination, people and booking preferences", True)
        ]
    if re.search(r"\b(buy|purchase|order|book|reserve)\b", lower):
        questions += [
            (
                "task_spending",
                "Maximum purchase amount and acceptable alternatives",
                True,
            )
        ]
    if re.search(r"\b(send|email|message|publish)\b", lower):
        questions += [
            (
                "task_recipient",
                "Intended recipients / destination and message requirements",
                True,
            )
        ]
    questions.append(
        ("task_output", "Expected result, sources and other instructions", False)
    )
    rows = [
        {
            "key": k,
            "label": profile.FIELDS[k],
            "required": True,
            "value": saved.get(k, {}).get("value", ""),
            "source": "personal" if k in saved else "missing",
        }
        for k in keys
    ]
    urls = re.findall(r"https?://[^\s<>]+", text)
    rows += [
        {
            "key": k,
            "label": label,
            "required": required,
            "value": urls[0].rstrip(".,") if k == "task_destination" and urls else "",
            "source": "task",
        }
        for k, label, required in questions
    ]
    rows += [
        {
            "key": k,
            "label": v["label"],
            "required": False,
            "value": "",
            "source": "optional",
            "suggested": v["value"],
        }
        for k, v in saved.items()
        if k not in keys
    ]
    return {
        "fields": rows,
        "warnings": warnings,
        "note": "Readiness checks cover common requirements. Unexpected site-specific questions pause the run for your input.",
    }


def wall_time(value, tz):
    try:
        d = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError("Choose a valid start date and time")
    if d.tzinfo is not None:
        raise ValueError("Use local time with the separate time zone selector")
    d = d.replace(second=0, microsecond=0)
    aware = d.replace(tzinfo=tz, fold=0)
    # Gap: reject initial nonexistent wall times. Repeating schedules skip that date.
    if datetime.fromtimestamp(aware.timestamp(), tz).replace(tzinfo=None) != d:
        raise ValueError(
            "This local time does not exist because clocks change. Choose another time"
        )
    return aware.timestamp()


def config(row, extra=None):
    if extra:
        return json.loads(core.dec(extra["body"]))
    return {
        "name": core.dec(row["prompt"])[:80],
        "prompt": core.dec(row["prompt"]),
        "timezone": "UTC",
        "recurrence": "interval" if row["interval"] else "once",
        "interval_hours": row["interval"] / 3600 if row["interval"] else 24,
        "local_start": datetime.fromtimestamp(row["next"], UTC).strftime(
            "%Y-%m-%dT%H:%M"
        ),
        "inputs": {},
        "missed": "latest",
        "budget": None,
        "max_runs": None,
        "ends_at": None,
        "legacy": True,
        "start_timestamp": row["next"],
    }


def next_time(cfg, after):
    tz = ZoneInfo(cfg["timezone"])
    start = cfg.get("start_timestamp") or wall_time(cfg["local_start"], tz)
    kind = cfg["recurrence"]
    if kind == "once":
        candidate = start if start > after else None
    elif kind == "interval":
        seconds = cfg["interval_hours"] * 3600
        candidate = start + max(0, math.floor((after - start) / seconds) + 1) * seconds
    else:
        first = datetime.fromtimestamp(start, tz)
        date = max(first.date(), datetime.fromtimestamp(after, tz).date())
        candidate = None
        for i in range(740):
            day = date + timedelta(days=i)
            if kind == "weekly" and day.weekday() not in cfg["weekdays"]:
                continue
            if kind == "monthly" and day.day != min(
                cfg["month_day"], calendar.monthrange(day.year, day.month)[1]
            ):
                continue
            local = datetime.combine(day, first.time().replace(tzinfo=None)).isoformat(
                timespec="minutes"
            )
            try:
                ts = wall_time(local, tz)
            except ValueError:
                continue
            if ts >= start and ts > after:
                candidate = ts
                break
    if candidate and cfg.get("ends_at") and candidate > cfg["ends_at"]:
        return None
    return candidate


def validate(owner, b, now=None):
    now = time.time() if now is None else now
    if not isinstance(b, dict):
        raise ValueError("Invalid schedule")
    prompt = str(b.get("prompt", "")).strip()
    check = readiness(owner, prompt, b.get("id"))
    name = str(b.get("name", "")).strip()[:100] or prompt[:80]
    try:
        tz = ZoneInfo(str(b.get("timezone", "UTC")))
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Choose a valid IANA time zone")
    kind = b.get("recurrence", "once")
    if kind not in ("once", "interval", "daily", "weekly", "monthly"):
        raise ValueError("Choose a supported recurrence")
    start = wall_time(b.get("local_start", ""), tz)
    try:
        hours = float(b.get("interval_hours", 24))
        weekdays = sorted(set(int(x) for x in b.get("weekdays", [0])))
        month_day = int(b.get("month_day", 1))
        budget = None if b.get("budget") in ("", None) else float(b["budget"])
        max_runs = None if b.get("max_runs") in ("", None) else int(b["max_runs"])
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Invalid schedule limits")
    if (
        not math.isfinite(hours)
        or not 1 <= hours <= 8760
        or not weekdays
        or any(x < 0 or x > 6 for x in weekdays)
        or not 1 <= month_day <= 31
    ):
        raise ValueError("Invalid recurrence settings")
    if budget is not None and (
        not math.isfinite(budget) or not 0.01 <= budget <= 10000
    ):
        raise ValueError("Per-run cost limit must be $0.01–$10,000")
    if max_runs is not None and not 1 <= max_runs <= 10000:
        raise ValueError("Run count must be 1–10,000")
    missed = b.get("missed", "latest")
    if missed not in ("latest", "skip"):
        raise ValueError("Invalid missed-run policy")
    inputs = b.get("inputs", {})
    if not isinstance(inputs, dict) or len(inputs) > 60:
        raise ValueError("Invalid scheduled inputs")
    allowed = {**profile.FIELDS, **{x["key"]: x["label"] for x in check["fields"]}}
    allowed.update({k: v["label"] for k, v in profile.values(owner).items()})
    clean = {}
    for key, val in inputs.items():
        if key not in allowed:
            raise ValueError("Unknown scheduled input; run the readiness check again")
        value = profile.safe_text(allowed[key], val)
        if value:
            clean[key] = {"label": allowed[key], "value": value}
    enabled = b.get("enabled", True)
    if type(b.get("consent", False)) is not bool:
        raise ValueError("Confirm schedule input consent with the checkbox")
    if type(enabled) is not bool:
        raise ValueError("Invalid schedule state")
    missing = [
        x["label"] for x in check["fields"] if x["required"] and not clean.get(x["key"])
    ]
    if enabled and missing:
        raise ValueError("Complete the readiness check: " + ", ".join(missing))
    if enabled and clean and b.get("consent") is not True:
        raise ValueError(
            "Confirm which details this schedule may use while you are away"
        )
    ends = None
    if b.get("end_date"):
        try:
            ends = wall_time(str(b["end_date"]) + "T23:59", tz) + 59
        except ValueError:
            raise ValueError("Choose a valid end date")
        if ends <= now:
            raise ValueError("End date must be in the future")
    cfg = {
        "name": name,
        "prompt": prompt,
        "timezone": str(tz),
        "recurrence": kind,
        "local_start": str(b["local_start"]),
        "interval_hours": hours,
        "weekdays": weekdays,
        "month_day": month_day,
        "inputs": clean,
        "missed": missed,
        "budget": budget,
        "max_runs": max_runs,
        "ends_at": ends,
        "end_date": b.get("end_date", ""),
        "consent": bool(b.get("consent")),
    }
    upcoming = next_time(cfg, now)
    if not upcoming and enabled:
        raise ValueError("Choose a future run time within the end date")
    return cfg, upcoming or start, enabled


def save(owner, b, id=None):
    from . import accounts

    accounts.require(owner, "schedules")
    updating = id is not None
    if updating:
        with core.db() as c:
            if not c.execute(
                "SELECT 1 FROM schedules WHERE id=%s AND owner=%s", (id, owner)
            ).fetchone():
                raise KeyError("Schedule not found")
    cfg, when, enabled = validate(owner, b)
    id = id or core.ident()
    now = time.time()
    from . import skills

    selected = (
        skills.selection(owner, b.get("skills"))
        if "skills" in b or not updating
        else None
    )
    with core.db() as c:
        c.begin_write()
        row = c.execute(
            "SELECT * FROM schedules WHERE id=%s AND owner=%s", (id, owner)
        ).fetchone()
        extra = c.execute(
            "SELECT * FROM schedule_settings WHERE id=%s", (id,)
        ).fetchone()
        if updating and not row:
            raise KeyError("Schedule not found")
        if row and b.get("version") != (extra["version"] if extra else 0):
            raise ValueError(
                "This schedule changed in another tab. Reload before saving"
            )
        if (
            not row
            and c.execute(
                "SELECT count(*) FROM schedules WHERE owner=%s", (owner,)
            ).fetchone()[0]
            >= 100
        ):
            raise ValueError("Keep up to 100 schedules per account")
        cfg["skills"] = (
            selected
            if selected is not None
            else config(row, extra).get(
                "skills", {"mode": "auto", "pins": [], "resolved": False}
            )
        )
        interval = (
            int(cfg["interval_hours"] * 3600) if cfg["recurrence"] == "interval" else 0
        )
        c.execute(
            "INSERT INTO schedules VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET prompt=excluded.prompt,next=excluded.next,interval=excluded.interval,enabled=excluded.enabled",
            (id, owner, core.enc(cfg["prompt"]), when, interval, int(enabled)),
        )
        c.execute(
            "INSERT INTO schedule_settings VALUES(%s,%s,1,%s,'') ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=schedule_settings.version+1,updated=excluded.updated,blocked=''",
            (id, core.enc(json.dumps(cfg)), now),
        )
        c.commit()
    return {"id": id}


def list_schedules(owner):
    with core.db() as c:
        rows = c.execute(
            "SELECT * FROM schedules WHERE owner=%s ORDER BY next", (owner,)
        ).fetchall()
        out = []
        for row in rows:
            extra = c.execute(
                "SELECT * FROM schedule_settings WHERE id=%s", (row["id"],)
            ).fetchone()
            cfg = config(row, extra)
            runs = c.execute(
                "SELECT r.*,t.status task_status FROM scheduled_runs r LEFT JOIN tasks t ON t.id=r.task AND t.owner=r.owner WHERE r.schedule=%s ORDER BY r.created DESC LIMIT 20",
                (row["id"],),
            ).fetchall()
            history = [
                {
                    "id": r["id"],
                    "task": r["task"] if r["task_status"] else None,
                    "due": r["due"],
                    "created": r["created"],
                    "status": r["task_status"]
                    or ("deleted" if r["task"] else r["status"]),
                    "reason": r["reason"],
                }
                for r in runs
            ]
            count = c.execute(
                "SELECT count(*) FROM scheduled_runs WHERE schedule=%s AND task IS NOT NULL",
                (row["id"],),
            ).fetchone()[0]
            out.append(
                {
                    **dict(row),
                    **cfg,
                    "inputs": {k: v["value"] for k, v in cfg.get("inputs", {}).items()},
                    "enabled": bool(row["enabled"]),
                    "version": extra["version"] if extra else 0,
                    "blocked": extra["blocked"] if extra else "",
                    "history": history,
                    "run_count": count,
                }
            )
    return out


def dispatch_due(now=None, only=None, owner=None, manual_token=None):
    now = time.time() if now is None else now
    created = []
    with core.db() as c:
        c.begin_write()
        rows = (
            c.execute(
                "SELECT * FROM schedules WHERE id=%s AND owner=%s", (only, owner)
            ).fetchall()
            if only
            else c.execute(
                "SELECT * FROM schedules WHERE enabled=1 AND next<=%s ORDER BY next LIMIT 200",
                (now,),
            ).fetchall()
        )
        if only and not rows:
            raise KeyError("Schedule not found")
        for r in rows:
            extra = c.execute(
                "SELECT * FROM schedule_settings WHERE id=%s", (r["id"],)
            ).fetchone()
            cfg = config(r, extra)
            if only:
                prior = c.execute(
                    "SELECT task FROM scheduled_runs WHERE id=%s",
                    (
                        str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL, r["id"] + ":manual:" + manual_token
                            )
                        ),
                    ),
                ).fetchone()
                if prior:
                    if prior["task"]:
                        created.append(prior["task"])
                    continue
                if not r["enabled"]:
                    raise ValueError("Activate the schedule before running it now")

            def blocked(reason):
                if extra:
                    c.execute(
                        "UPDATE schedule_settings SET blocked=%s WHERE id=%s",
                        (reason, r["id"]),
                    )
                if only:
                    raise ValueError(reason)

            from . import accounts

            policy = accounts.effective(r["owner"], c)
            if (
                policy["disabled"]
                or not policy["features"]["work"]
                or not policy["features"]["schedules"]
            ):
                blocked("Scheduled work is disabled for this account.")
                continue
            pins = cfg.get("skills", {}).get("pins", [])
            unavailable = any(
                not c.execute(
                    "SELECT 1 FROM skills s JOIN skill_versions v ON v.skill=s.id WHERE s.id=%s AND s.owner=%s AND v.id=%s AND s.enabled AND NOT s.archived AND NOT s.deleted",
                    (p["id"], r["owner"], p["version_id"]),
                ).fetchone()
                for p in pins
            )
            if unavailable:
                blocked(
                    "A pinned Skill is unavailable. Edit Skills for this schedule before running."
                )
                continue
            if cfg.get("ends_at") and now > cfg["ends_at"]:
                if only:
                    raise ValueError(
                        "This schedule has passed its end date. Edit it before running again"
                    )
                c.execute("UPDATE schedules SET enabled=0 WHERE id=%s", (r["id"],))
                continue
            count = c.execute(
                "SELECT count(*) FROM scheduled_runs WHERE schedule=%s AND task IS NOT NULL",
                (r["id"],),
            ).fetchone()[0]
            if cfg.get("max_runs") and count >= cfg["max_runs"]:
                if only:
                    raise ValueError(
                        "This schedule has reached its run limit. Edit it before running again"
                    )
                c.execute("UPDATE schedules SET enabled=0 WHERE id=%s", (r["id"],))
                continue
            if only:
                existing = c.execute(
                    "SELECT task FROM scheduled_runs WHERE id=%s",
                    (
                        str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL, r["id"] + ":manual:" + manual_token
                            )
                        ),
                    ),
                ).fetchone()
                if existing:
                    if existing["task"]:
                        created.append(existing["task"])
                    continue
            last = c.execute(
                "SELECT r.id,t.status FROM scheduled_runs r JOIN tasks t ON t.id=r.task WHERE r.schedule=%s ORDER BY r.created DESC LIMIT 1",
                (r["id"],),
            ).fetchone()
            if (
                last
                and last["status"] == "failed"
                and cfg.get("acknowledged_run") != last["id"]
            ):
                c.execute("UPDATE schedules SET enabled=0 WHERE id=%s", (r["id"],))
                blocked(
                    "Previous run failed. Inspect it, then resume the schedule when ready."
                )
                continue
            previous = c.execute(
                "SELECT t.status FROM scheduled_runs r JOIN tasks t ON t.id=r.task WHERE r.schedule=%s AND t.status IN ('queued','running','approval','paused') LIMIT 1",
                (r["id"],),
            ).fetchone()
            if previous:
                blocked(
                    "Previous run is "
                    + previous["status"]
                    + ". Open it to continue or stop it."
                )
                continue
            active = c.execute(
                "SELECT count(*) FROM tasks WHERE owner=%s AND mode='work' AND status IN ('queued','running')",
                (r["owner"],),
            ).fetchone()[0]
            if active >= policy["limits"]["active_work"]:
                blocked("Waiting for an available Work slot")
                continue
            due = float(r["next"]) if not only else now
            run_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    r["id"] + ":" + ("manual:" + manual_token if only else str(due)),
                )
            )
            if (
                only
                and c.execute(
                    "SELECT 1 FROM scheduled_runs WHERE id=%s", (run_id,)
                ).fetchone()
            ):
                continue
            if not only and cfg.get("missed") == "skip" and now - due > 900:
                c.execute(
                    "INSERT INTO scheduled_runs VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        run_id,
                        r["id"],
                        r["owner"],
                        None,
                        due,
                        now,
                        "skipped",
                        "Missed by more than 15 minutes",
                    ),
                )
            else:
                task_id = run_id
                s = core.initial_state(cfg["prompt"], "work")
                s["schedule_id"] = r["id"]
                s["schedule_inputs"] = cfg.get("inputs", {})
                s["schedule_budget"] = cfg.get("budget")
                s["skills"] = cfg.get(
                    "skills", {"mode": "auto", "pins": [], "resolved": False}
                )
                c.execute(
                    "INSERT INTO tasks(id,owner,title,state,status,mode,created,updated) VALUES(%s,%s,%s,%s,%s,'work',%s,%s) ON CONFLICT DO NOTHING",
                    (
                        task_id,
                        r["owner"],
                        cfg["name"][:120],
                        core.enc(json.dumps(s)),
                        "queued",
                        now,
                        now,
                    ),
                )
                from . import notebook

                notebook.seed(c, task_id, cfg["prompt"])
                c.execute(
                    "INSERT INTO scheduled_runs VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (run_id, r["id"], r["owner"], task_id, due, now, "queued", ""),
                )
                c.execute(
                    "INSERT INTO events(task,kind,body,created) VALUES(%s,%s,%s,%s)",
                    (
                        task_id,
                        "created",
                        core.enc(
                            json.dumps(
                                {"text": "Scheduled work started", "mode": "work"}
                            )
                        ),
                        now,
                    ),
                )
                created.append(task_id)
            # Coalesce missed recurring slots; never create a catch-up burst or overlapping run.
            if not only or cfg["recurrence"] == "once":
                nxt = None if only else next_time(cfg, now)
                c.execute(
                    "UPDATE schedules SET next=%s,enabled=%s WHERE id=%s",
                    (nxt or due, int(nxt is not None), r["id"]),
                )
            if extra:
                c.execute(
                    "UPDATE schedule_settings SET blocked='' WHERE id=%s", (r["id"],)
                )
        c.commit()
    return {"tasks": created}


def confirmed_answer(state, args):
    keys = profile.requested_keys(args)
    values = state.get("schedule_inputs", {})
    fields = profile.form_fields(args)
    if fields:
        if any(
            f["sensitive"] or not f["profile_key"] or f["profile_key"] not in values
            for f in fields
        ):
            return ""
        return (
            values[fields[0]["profile_key"]]["value"]
            if len(fields) == 1
            else "\n".join(
                f["label"] + ": " + values[f["profile_key"]]["value"] for f in fields
            )
        )
    if not keys or not all(k in values for k in keys):
        return ""
    return (
        values[keys[0]]["value"]
        if len(keys) == 1
        else "\n".join(values[k]["label"] + ": " + values[k]["value"] for k in keys)
    )


def set_enabled(owner, id, enabled, version):
    with core.db() as c:
        c.begin_write()
        r = c.execute(
            "SELECT * FROM schedules WHERE id=%s AND owner=%s", (id, owner)
        ).fetchone()
        if not r:
            raise KeyError("Schedule not found")
        extra = c.execute(
            "SELECT * FROM schedule_settings WHERE id=%s", (id,)
        ).fetchone()
        if version != (extra["version"] if extra else 0):
            raise ValueError("Schedule changed. Refresh and try again")
        cfg = config(r, extra)
        nxt = r["next"]
        if enabled:
            if cfg.get("inputs") and not cfg.get("consent"):
                raise ValueError(
                    "Edit the schedule and confirm which details it may use first"
                )
            missing = [
                x["label"]
                for x in readiness(owner, cfg["prompt"], connection=c)["fields"]
                if x["required"] and not cfg.get("inputs", {}).get(x["key"])
            ]
            if missing and not cfg.get("legacy"):
                raise ValueError(
                    "Edit the schedule and complete its readiness check first"
                )
            nxt = next_time(cfg, time.time())
            if nxt is None:
                raise ValueError("Edit the schedule to choose a future run time")
            last = c.execute(
                "SELECT id FROM scheduled_runs WHERE schedule=%s ORDER BY created DESC LIMIT 1",
                (id,),
            ).fetchone()
            cfg["acknowledged_run"] = last["id"] if last else None
        c.execute(
            "UPDATE schedules SET enabled=%s,next=%s WHERE id=%s",
            (int(enabled), nxt, id),
        )
        c.execute(
            "INSERT INTO schedule_settings VALUES(%s,%s,1,%s,'') ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=schedule_settings.version+1,updated=excluded.updated,blocked=''",
            (id, core.enc(json.dumps(cfg)), time.time()),
        )
        c.commit()
    return {"ok": True}
