import asyncio, json, time, uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from app import core, profile, scheduling, billing, worker, main
from conftest import login
from test_billing import account
from test_sandbox import sandbox, sc


@pytest.fixture(autouse=True)
def stable_schedule_clock(monkeypatch):
    # Calendar fixtures must remain valid when installer checks run in later years.
    monkeypatch.setattr(
        scheduling,
        "time",
        SimpleNamespace(
            time=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc).timestamp()
        ),
    )


def form(**kw):
    return {
        "name": "Daily research",
        "prompt": "Research the latest technology news",
        "timezone": "America/Toronto",
        "recurrence": "daily",
        "local_start": "2027-01-01T09:00",
        "interval_hours": 24,
        "weekdays": [0, 2, 4],
        "month_day": 31,
        "inputs": {},
        "consent": False,
        "enabled": True,
        **kw,
    }


def ts(value):
    return datetime.fromisoformat(value).timestamp()


def test_profile_encryption_isolation_version_and_sensitive_rejection(client):
    h = login(client)
    r = client.put(
        "/api/personal-details",
        headers=h,
        json={
            "version": 0,
            "fields": {
                "full_name": "Unique Private Person",
                "email": "private@example.test",
                "shipping_line1": "123 Secret Lane",
            },
            "custom": [
                {"id": "diet", "label": "Dietary preference", "value": "Vegetarian"}
            ],
        },
    )
    assert r.status_code == 200, r.text
    with core.db() as c:
        assert (
            "Unique Private Person"
            not in c.execute("SELECT body FROM personal_details").fetchone()[0]
        )
    assert (
        client.put(
            "/api/personal-details", headers=h, json={"version": 0, "fields": {}}
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/personal-details",
            headers=h,
            json={
                "version": 1,
                "custom": [
                    {"id": "card", "label": "Card number", "value": "4111111111111111"}
                ],
            },
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/personal-details",
            headers=h,
            json={"version": 1, "fields": {"delivery_notes": "4111 1111 1111 1111"}},
        ).status_code
        == 400
    )
    assert client.put("/api/personal-details", json={"version": 1}).status_code == 403
    client.post("/api/logout", headers=h, json={})
    login(client, "other@example.test")
    assert client.get("/api/personal-details").json()["fields"] == {}


def test_prefill_is_editable_scoped_and_never_used_for_secrets():
    owner, tid = account()
    profile.save(
        owner,
        {
            "version": 0,
            "fields": {"email": "person@example.test", "phone": "1234567890"},
        },
    )
    approval = {
        "name": "ask_user",
        "arguments": {"question": "Your email?", "input_type": "email"},
    }
    assert (
        profile.prefill(owner, approval)["prefill"][0]["value"] == "person@example.test"
    )
    assert (
        profile.requested_keys(
            {"question": "What is their email?", "input_type": "email"}
        )
        == []
    )
    assert (
        profile.requested_keys(
            {
                "question": "Password",
                "input_type": "secret",
                "profile_fields": ["email"],
            }
        )
        == []
    )
    p = profile.get(owner)
    p["enabled"] = False
    profile.save(owner, p)
    assert profile.prefill(owner, approval)["prefill"] == []


def test_schedule_readiness_blocks_missing_consent_and_missing_details():
    owner, _ = account()
    b = form(prompt="Buy and ship a book from https://example.com")
    with pytest.raises(ValueError, match="readiness"):
        scheduling.validate(owner, b)
    check = scheduling.readiness(owner, b["prompt"])
    b["inputs"] = {
        f["key"]: "confirmed information" for f in check["fields"] if f["required"]
    }
    with pytest.raises(ValueError, match="Confirm"):
        scheduling.validate(owner, b)
    b["consent"] = True
    cfg, _, _ = scheduling.validate(owner, b)
    assert cfg["inputs"]["full_name"]["value"] == "confirmed information"
    b["enabled"] = False
    b["inputs"] = {}
    assert scheduling.validate(owner, b)[2] is False


@pytest.mark.parametrize(
    "zone,start,after,expected",
    [
        (
            "America/Toronto",
            "2027-03-13T02:30",
            "2027-03-13T07:30:00+00:00",
            "2027-03-15T06:30:00+00:00",
        ),
        (
            "America/Toronto",
            "2027-11-06T01:30",
            "2027-11-07T05:30:00+00:00",
            "2027-11-08T06:30:00+00:00",
        ),
        (
            "Asia/Kolkata",
            "2027-01-01T09:00",
            "2027-01-01T03:30:00+00:00",
            "2027-01-02T03:30:00+00:00",
        ),
    ],
)
def test_calendar_dst_gap_fold_and_non_hour_offsets(zone, start, after, expected):
    cfg = form(timezone=zone, local_start=start)
    assert scheduling.next_time(cfg, ts(after)) == ts(expected)


def test_nonexistent_start_and_invalid_zone_are_rejected():
    owner, _ = account()
    with pytest.raises(ValueError, match="does not exist"):
        scheduling.validate(owner, form(local_start="2027-03-14T02:30"))
    with pytest.raises(ValueError, match="time zone"):
        scheduling.validate(owner, form(timezone="Bad/Zone"))


def test_month_end_weekdays_and_fixed_interval_anchor():
    assert scheduling.next_time(
        form(timezone="UTC", local_start="2027-01-31T09:00", recurrence="monthly"),
        ts("2027-01-31T09:00:00+00:00"),
    ) == ts("2027-02-28T09:00:00+00:00")
    assert scheduling.next_time(
        form(timezone="UTC", recurrence="weekly"), ts("2027-01-01T09:00:00+00:00")
    ) == ts("2027-01-04T09:00:00+00:00")
    assert scheduling.next_time(
        form(timezone="UTC", recurrence="interval", interval_hours=4),
        ts("2027-01-02T10:00:00+00:00"),
    ) == ts("2027-01-02T13:00:00+00:00")


def test_atomic_dispatch_no_overlap_or_catchup_burst():
    owner, tid = account()
    sid = scheduling.save(owner, form())["id"]
    due = ts("2027-01-01T14:00:00+00:00")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: scheduling.dispatch_due(now=due + 100000), range(4)))
    rows = scheduling.list_schedules(owner)
    assert rows[0]["run_count"] == 1
    scheduling.dispatch_due(now=due + 300000)
    assert scheduling.list_schedules(owner)[0]["run_count"] == 1
    assert "Previous run" in scheduling.list_schedules(owner)[0]["blocked"]


def test_one_shot_run_now_idempotency_consumes_schedule():
    owner, _ = account()
    sid = scheduling.save(owner, form(recurrence="once"))["id"]
    token = str(uuid.uuid4())
    first = scheduling.dispatch_due(only=sid, owner=owner, manual_token=token)
    second = scheduling.dispatch_due(only=sid, owner=owner, manual_token=token)
    assert first == second and len(first["tasks"]) == 1
    assert not scheduling.list_schedules(owner)[0]["enabled"]


def test_missed_skip_records_history_without_running():
    owner, _ = account()
    sid = scheduling.save(owner, form(missed="skip"))["id"]
    scheduling.dispatch_due(now=ts("2027-01-02T18:00:00+00:00"))
    row = scheduling.list_schedules(owner)[0]
    assert (
        row["run_count"] == 0
        and row["history"][0]["status"] == "skipped"
        and row["next"] > ts("2027-01-02T18:00:00+00:00")
    )


def test_end_limits_and_credit_shortage():
    owner, _ = account()
    sid = scheduling.save(owner, form(max_runs=1))["id"]
    result = scheduling.dispatch_due(now=ts("2027-01-01T14:00:00+00:00"))
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='completed' WHERE id=%s", (result["tasks"][0],)
        )
    scheduling.dispatch_due(now=ts("2027-01-02T14:00:00+00:00"))
    assert not scheduling.list_schedules(owner)[0]["enabled"]
    sid = scheduling.save(owner, form(name="Credit check"))["id"]
    assert scheduling.dispatch_due(now=ts("2027-01-02T14:00:00+00:00"))["tasks"]


def test_snapshot_inputs_encrypted_and_not_auto_updated_from_profile():
    owner, _ = account()
    b = form(inputs={"task_output": "Private report preference"}, consent=True)
    sid = scheduling.save(owner, b)["id"]
    with core.db() as c:
        assert (
            "Private report preference"
            not in c.execute(
                "SELECT body FROM schedule_settings WHERE id=%s", (sid,)
            ).fetchone()[0]
        )
    r = scheduling.dispatch_due(only=sid, owner=owner, manual_token=str(uuid.uuid4()))
    s = core.state(core.owned(owner, r["tasks"][0]))
    assert s["schedule_inputs"]["task_output"]["value"] == "Private report preference"
    assert (
        scheduling.confirmed_answer(
            {
                "schedule_inputs": {
                    "email": {"label": "Email", "value": "confirmed@example.test"}
                }
            },
            {"profile_fields": ["email"], "question": "Your email?"},
        )
        == "confirmed@example.test"
    )
    assert not scheduling.confirmed_answer(
        s,
        {
            "question": "What is the verification code?",
            "input_type": "otp",
            "profile_fields": ["task_output"],
        },
    )


def test_schedule_api_owner_csrf_stale_version_and_delete_preserves_run(client):
    h = login(client)
    r = client.post("/api/schedules", headers=h, json=form())
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    row = client.get("/api/schedules").json()[0]
    assert (
        client.put(
            "/api/schedules/" + sid, headers=h, json={**row, "version": 0}
        ).status_code
        == 400
    )
    r = client.post(
        "/api/schedules/" + sid + "/action",
        headers=h,
        json={"action": "run", "token": str(uuid.uuid4())},
    )
    tid = r.json()["tasks"][0]
    assert client.delete("/api/schedules/" + sid).status_code == 403
    client.post("/api/logout", headers=h, json={})
    h2 = login(client, "other@example.test")
    assert (
        client.put(
            "/api/schedules/" + sid, headers=h2, json={**row, "consent": True}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/schedules/" + sid + "/action",
            headers=h2,
            json={"action": "run", "token": str(uuid.uuid4())},
        ).status_code
        == 404
    )
    assert client.get("/api/schedules").json() == []
    client.post("/api/logout", headers=h2, json={})
    r = client.post(
        "/api/login",
        headers={"Origin": "https://testserver"},
        json={"email": "a@example.com", "password": "test-password-123"},
    )
    h = {"Origin": "https://testserver", "X-CSRF": r.json()["csrf"]}
    assert client.delete("/api/schedules/" + sid, headers=h).status_code == 200
    assert client.get("/api/tasks/" + tid).status_code == 200


def test_browser_batch_enforces_human_control_and_owner(client, monkeypatch):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Browser task")
    calls = []

    async def fake(*a):
        calls.append(a)
        return {"ok": True}

    monkeypatch.setattr(main, "broker", fake)
    b = {
        "kind": "input",
        "args": {"events": [{"kind": "text", "args": {"text": "hello"}}]},
    }
    assert (
        client.post(f"/api/tasks/{tid}/browser", headers=h, json=b).status_code == 400
    )
    core.takeover(owner, tid, "human")
    assert (
        client.post(f"/api/tasks/{tid}/browser", headers=h, json=b).status_code == 200
    )
    assert calls[0][1] == "action"
    assert client.post(f"/api/tasks/{tid}/browser", json=b).status_code == 403


def test_batch_guard_stops_before_payment_and_returns_only_unexecuted_events(
    sc, monkeypatch
):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    executed = []

    class Page:
        url = "https://example.test/checkout"

    async def get():
        return Page()

    async def guard(p, k, a, t=None):
        return (
            {"approval_required": True, "approval_token": "token"}
            if k == "pointer"
            else None
        )

    async def inp(p, k, a):
        executed.append(k)

    monkeypatch.setattr(sandbox, "getpage", get)
    monkeypatch.setattr(sandbox, "payment_guard", guard)
    monkeypatch.setattr(sandbox, "dev_input", inp)
    events = [
        {"kind": "text", "args": {"text": "hello"}},
        {"kind": "pointer", "args": {"x": 10, "y": 20}},
        {"kind": "key", "args": {"key": "Enter"}},
    ]
    r = sc.post("/action", json={"kind": "input", "args": {"events": events}})
    assert r.status_code == 200
    assert executed == ["text"]
    assert r.json()["pending_events"] == events[1:]
    assert (
        sc.post(
            "/action",
            json={"kind": "input", "args": {"events": [{"kind": "down", "args": {}}]}},
        ).status_code
        == 400
    )


def test_returning_browser_control_resumes_human_challenge(client):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Sign in")
    s = core.state(core.owned(owner, tid))
    args = {"question": "Complete sign-in", "browser_takeover": True}
    s["pending"] = {
        "calls": [
            {
                "id": "ask",
                "function": {"name": "ask_user", "arguments": json.dumps(args)},
            }
        ],
        "index": 0,
        "approval": {"name": "ask_user", "arguments": args},
    }
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='approval',control='human',state=%s WHERE id=%s",
            (core.enc(json.dumps(s)), tid),
        )
    assert (
        client.post(
            f"/api/tasks/{tid}/control", headers=h, json={"owner": "ai"}
        ).status_code
        == 200
    )
    r = core.owned(owner, tid)
    assert r["status"] == "queued" and "Observe" in core.state(r)["pending"]["answer"]


def test_paused_draft_cannot_activate_without_input_consent():
    owner, _ = account()
    sid = scheduling.save(
        owner,
        form(
            enabled=False, inputs={"task_output": "My private details"}, consent=False
        ),
    )["id"]
    with pytest.raises(ValueError, match="confirm"):
        scheduling.set_enabled(owner, sid, True, 1)


def test_failed_run_pauses_until_explicit_resume():
    owner, _ = account()
    sid = scheduling.save(owner, form())["id"]
    r = scheduling.dispatch_due(now=ts("2027-01-01T14:00:00+00:00"))
    with core.db() as c:
        c.execute("UPDATE tasks SET status='failed' WHERE id=%s", (r["tasks"][0],))
    scheduling.dispatch_due(now=ts("2027-01-02T14:00:00+00:00"))
    row = scheduling.list_schedules(owner)[0]
    assert not row["enabled"] and "Previous run failed" in row["blocked"]
    scheduling.set_enabled(owner, sid, True, row["version"])
    assert scheduling.list_schedules(owner)[0]["enabled"]


def test_budget_pauses_before_another_paid_step(monkeypatch):
    owner, tid = account()
    sid = scheduling.save(owner, form(budget=0.01))["id"]
    r = scheduling.dispatch_due(only=sid, owner=owner, manual_token=str(uuid.uuid4()))
    tid = r["tasks"][0]
    rid = billing.reserve(owner, tid, 0.02, service="model")
    billing.settle(rid, 0.02)
    row = dict(core.owned(owner, tid))
    asyncio.run(worker.step(row))
    after = core.owned(owner, tid)
    assert after["status"] == "paused" and "cost limit" in core.state(after)["error"]


def test_saved_schedule_details_survive_profile_removal():
    owner, _ = account()
    profile.save(
        owner,
        {
            "version": 0,
            "custom": [
                {"id": "meal", "label": "Meal preference", "value": "Vegetarian"}
            ],
        },
    )
    sid = scheduling.save(
        owner, form(inputs={"custom_meal": "Vegetarian"}, consent=True)
    )["id"]
    with core.db() as c:
        c.execute("DELETE FROM personal_details WHERE owner=%s", (owner,))
    row = scheduling.list_schedules(owner)[0]
    assert row["inputs"]["custom_meal"] == "Vegetarian"
    check = scheduling.readiness(owner, row["prompt"], sid)
    assert any(f["key"] == "custom_meal" for f in check["fields"])
    scheduling.save(owner, {**row, "name": "Updated name"}, sid)
    assert scheduling.list_schedules(owner)[0]["inputs"]["custom_meal"] == "Vegetarian"


def test_chat_schedule_tool_creates_readiness_drafts_and_normal_runs():
    from app import tools

    owner, tid = account()
    row = dict(core.owned(owner, tid))
    state = core.state(row)
    a = {
        "prompt": "Buy a book and ship it to me",
        "timestamp": time.time() + 7200,
        "interval": 86400,
    }
    result = asyncio.run(tools.execute(row, state, "schedule_task", a))
    assert result["draft"] and not result["scheduled"]
    a["prompt"] = "Research tomorrow’s news and provide a concise brief"
    result = asyncio.run(tools.execute(row, state, "schedule_task", a))
    assert result["scheduled"] and not result["draft"]
    assert len(scheduling.list_schedules(owner)) == 2


def test_legacy_one_off_can_be_edited_into_prepared_schedule():
    owner, _ = account()
    sid = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO schedules VALUES(%s,%s,%s,%s,%s,%s)",
            (
                sid,
                owner,
                core.enc("Research tomorrow’s news"),
                time.time() + 7200,
                0,
                1,
            ),
        )
    row = scheduling.list_schedules(owner)[0]
    assert row["version"] == 0 and row["recurrence"] == "once"
    scheduling.save(owner, {**row, "name": "Edited once"}, sid)
    assert scheduling.list_schedules(owner)[0]["version"] == 1


def test_worker_uses_only_confirmed_schedule_answer_and_pauses_for_unknown():
    owner, tid = account()
    row = dict(core.owned(owner, tid))
    state = core.state(row)
    state["schedule_inputs"] = {
        "email": {"label": "Email", "value": "confirmed@example.test"}
    }

    def pending(keys):
        return {
            "calls": [
                {
                    "id": "ask-contact",
                    "function": {
                        "name": "ask_user",
                        "arguments": json.dumps(
                            {
                                "question": "Confirm your contact information",
                                "profile_fields": keys,
                            }
                        ),
                    },
                }
            ],
            "index": 0,
        }

    state["pending"] = pending(["email"])
    core.save(row, state)
    asyncio.run(worker.step(dict(core.owned(owner, tid))))
    after = core.state(core.owned(owner, tid))
    assert (
        after["pending"] is None
        and "confirmed@example.test" in after["messages"][-1]["content"]
    )
    after["pending"] = pending(["phone"])
    core.save(dict(core.owned(owner, tid)), after)
    asyncio.run(worker.step(dict(core.owned(owner, tid))))
    assert core.owned(owner, tid)["status"] == "approval"
