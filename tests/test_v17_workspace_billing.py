"""v17 regressions: human input state, lifecycle, private billing and a real PTY."""

import asyncio, json, time, uuid
import pytest
from app import core, main, billing, broker, providers
from conftest import login
from test_sandbox import sandbox, sc
from test_billing import account, operation


def test_human_preview_mutex_is_not_ai_activity(client, monkeypatch):
    headers = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Preview", mode="work")
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed',lease=0 WHERE id=%s", (tid,))

    async def proxy(task, op, body):
        assert op == "dev-action"
        row = core.owned(owner, tid)
        assert row["busy"] > time.time()
        assert not main.detail_payload(row, core.state(row), [])["busy"]
        return {"ok": True}

    monkeypatch.setattr(main, "broker", proxy)
    for _ in range(5):
        assert (
            client.post(
                f"/api/tasks/{tid}/workspace",
                headers=headers,
                json={"op": "preview", "kind": "input", "args": {"events": []}},
            ).status_code
            == 200
        )
    assert not client.get("/api/tasks/" + tid).json()["busy"]
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='running',lease=%s,busy=%s WHERE id=%s",
            (time.time() + 60, time.time() + 60, tid),
        )
    assert client.get("/api/tasks/" + tid).json()["busy"]
    assert (
        client.post(
            f"/api/tasks/{tid}/workspace",
            headers=headers,
            json={"op": "terminal", "action": "input", "data": "ls\r"},
        ).status_code
        == 409
    )


def test_stopped_observation_cannot_start_billing(monkeypatch):
    class Request:
        async def json(self):
            return {"op": "list"}

    async def forbidden(*a, **k):
        raise AssertionError("Observation allocated workspace")

    monkeypatch.setattr(broker, "endpoint", forbidden)
    tid = str(uuid.uuid4())
    assert asyncio.run(broker.dispatch(tid, "services", Request())) == {"services": []}
    assert asyncio.run(broker.dispatch(tid, "status", Request()))["status"] == "stopped"
    assert broker.name(tid) not in broker.touch


def test_stopping_clears_preview_and_preserves_state(client, monkeypatch):
    headers = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Preview", mode="work")
    s = core.state(core.owned(owner, tid))
    s["app_preview"] = {"port": 3000}
    s["test_marker"] = "preserved"
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='completed',state=%s WHERE id=%s",
            (core.enc(json.dumps(s)), tid),
        )
    calls = []

    async def proxy(*args):
        calls.append(args)
        return {"stopped": True}

    monkeypatch.setattr(main, "broker", proxy)
    assert (
        client.post(
            f"/api/tasks/{tid}/workspace-stop", headers=headers, json={}
        ).status_code
        == 200
    )
    saved = core.state(core.owned(owner, tid))
    assert "app_preview" not in saved and saved["test_marker"] == "preserved"
    assert calls == [(tid, "stop")]
    assert client.get("/api/tasks/" + tid).json()["app_preview"] is None


def test_usage_filters_sort_pagination_export_and_private_fields():
    owner, tid = account()
    for i in range(31):
        rid = billing.reserve(
            owner,
            tid,
            0.001,
            model="openai/gpt-secret",
            metadata={
                "mode": "chat" if i % 2 else "work",
                "provider": "secret",
                "pricing": {"prompt": 1},
                "prompt_tokens": 100,
            },
        )
        billing.settle(rid, 0.00001 * (i + 1), provider_id="private-" + str(i))
    result = billing.activity(owner, mode="work", limit=10, sort="highest")
    assert (
        result["total"] == 16
        and len(result["rows"]) == 10
        and result["rows"][0]["charge"] > result["rows"][-1]["charge"]
    )
    assert len(billing.activity(owner, mode="work", limit=10, offset=10)["rows"]) == 6
    assert billing.activity(owner, min_charge=".00025")["total"] == 7
    assert billing.activity(owner, query="no match")["total"] == 0
    for text in [json.dumps(result), billing.export_csv(owner)]:
        # v22 intentionally exposes model IDs and derived publishers for analytics.
        assert "openai/gpt-secret" in text
        for secret in [
            "provider_id",
            "cost_basis",
            "private-",
            "pricing",
            "cost_nano",
            '"provider": "secret"',
        ]:
            assert secret not in text
    assert billing.activity(owner)["forecast"]["sample_count"] == 31
    assert (
        billing.activity(owner, service="search")["forecast"]
        == billing.activity(owner)["forecast"]
    )


def test_bad_dates_return_clear_400(client):
    login(client)
    assert client.get("/api/usage?start_date=garbage").status_code == 400
    assert (
        client.get("/api/usage?start_date=2026-09-10&end_date=2026-09-01").status_code
        == 400
    )
    assert client.get("/api/usage?min_charge=-1").status_code == 400


def test_pricing_exposes_allowed_models_but_not_internal_price_fields(
    client, monkeypatch
):
    login(client)

    async def catalog():
        return {
            providers.configured_model(m): {
                "name": "Secret upstream",
                "pricing": {
                    "prompt": ".000001",
                    "completion": ".000003",
                    "internal": "2",
                },
            }
            for m in ("chat", "work")
        }

    monkeypatch.setattr(providers, "catalog", catalog)
    r = client.get("/api/pricing")
    assert r.status_code == 200
    # v20 deliberately exposes account-allowed model names; infrastructure/pricing internals stay private.
    assert [m["model"] for m in r.json()["models"]] == [
        providers.configured_model(m) for m in ("chat", "work")
    ]
    for secret in ["openrouter", "Exa", "multiplier", "internal"]:
        assert secret not in r.text
    assert r.json()["models"][0]["pricing"]["prompt"] == 0.000001


def test_terminal_real_pty_cwd_input_history_resize_interrupt_reconnect(sc):
    def call(op, **body):
        r = sc.post("/terminal", json={"op": op, **body})
        assert r.status_code == 200, r.text
        return r.json()

    def until(text, cursor=0):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            r = call("read", cursor=cursor)
            if text in r["output"]:
                return r
            time.sleep(0.03)
        raise AssertionError((text, r))

    try:
        call("open", cols=90, rows=26)
        call(
            "input",
            data="export ASTER_PTY_TEST=kept; mkdir -p terminal-cwd; cd terminal-cwd; printf 'PTY_%s\\n' \"$ASTER_PTY_TEST\"\r",
        )
        r = until("PTY_kept")
        cursor = r["cursor"]
        assert r["running"]
        call("open")
        call("resize", cols=105, rows=32)
        call("input", data="pwd; stty size; printf 'STATE_%s\\n' \"$ASTER_PTY_TEST\"\r")
        r = until("STATE_kept", cursor)
        assert "terminal-cwd" in r["output"] and "32 105" in r["output"]
        cursor = r["cursor"]
        call("input", data="sleep 30\r")
        time.sleep(0.1)
        call("input", data="\x03")
        call("input", data="printf 'INTERRUPT_%s\\n' ok\r")
        r = until("INTERRUPT_ok", cursor)
        assert r["running"]
        cursor = r["cursor"]
        call("input", data="\x1b[A\r")
        assert until("INTERRUPT_ok", cursor)["running"]
    finally:
        call("close")
    assert sc.post("/terminal", json={"op": "read"}).status_code == 410


def test_terminal_auth_and_browser_isolation(sc, monkeypatch):
    monkeypatch.setenv("ASTER_SANDBOX_KEY", "secret")
    assert sc.post("/terminal", json={"op": "open"}).status_code == 401
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    assert (
        sc.post(
            "/terminal", headers={"X-Aster-Sandbox": "secret"}, json={"op": "open"}
        ).status_code
        == 403
    )


def test_terminal_does_not_bypass_task_owner_or_csrf(client):
    h = login(client)
    assert (
        client.post(
            "/api/tasks/" + str(uuid.uuid4()) + "/workspace",
            headers=h,
            json={"op": "terminal", "action": "open"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/tasks/" + str(uuid.uuid4()) + "/workspace",
            json={"op": "terminal", "action": "open"},
        ).status_code
        == 403
    )


def test_published_rate_card_survives_temporary_feed_outage(client, monkeypatch):
    login(client)

    async def rates():
        return {
            providers.configured_model(m): {
                "pricing": {"prompt": ".000001", "completion": ".000003"}
            }
            for m in ("chat", "work")
        }

    monkeypatch.setattr(providers, "catalog", rates)
    first = client.get("/api/pricing").json()

    async def fail():
        raise providers.ProviderError("feed unavailable", 503)

    monkeypatch.setattr(providers, "catalog", fail)
    second = client.get("/api/pricing").json()
    assert (
        second["models"] == first["models"]
        and second["rates_updated"] == first["rates_updated"]
    )
    assert "OpenRouter" not in json.dumps(second)


def test_preview_reopen_waits_for_prior_input_without_replaying_it():
    owner, tid = account()
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed',lease=0 WHERE id=%s", (tid,))
    core.begin_action(tid, "ai", workspace=True)

    async def exercise():
        async def release():
            await asyncio.sleep(0.08)
            core.end_action(tid)

        releasing = asyncio.create_task(release())
        start = time.monotonic()
        await main.begin_workspace_action(tid, owner)
        await releasing
        assert time.monotonic() - start >= 0.07
        assert not main.ai_busy(core.owned(owner, tid))
        core.end_action(tid)

    asyncio.run(exercise())


def test_worker_does_not_start_during_a_human_workspace_action():
    owner, tid = account()
    with core.db() as c:
        c.execute("UPDATE tasks SET busy=%s WHERE id=%s", (time.time() + 60, tid))
    assert core.acquire() is None
    core.end_action(tid)
    assert core.acquire()["id"] == tid


def test_stopped_workspace_error_is_returned_as_readable_json(client, monkeypatch):
    from app.tools import SandboxError

    headers = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Stopped project", mode="work")
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (tid,))

    async def stopped(*args):
        raise SandboxError(410, "Workspace stopped. Start the app from Services first.")

    monkeypatch.setattr(main, "broker", stopped)
    r = client.post(
        "/api/tasks/" + tid + "/workspace",
        headers=headers,
        json={"op": "preview", "kind": "open"},
    )
    assert r.status_code == 410 and r.json()["detail"].startswith("Workspace stopped")
