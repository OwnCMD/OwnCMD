from test_billing import pending_estimate

"""Browser lifetime regressions using the real metering ledger and fake containers."""
import asyncio, json, time
from types import SimpleNamespace
import httpx, pytest
from app import broker, billing, core, main
from conftest import login


@pytest.fixture
def live(monkeypatch):
    for key in (
        "touch",
        "urls",
        "uses",
        "session_base",
        "started_at",
        "stopping",
        "human_session_saved",
    ):
        monkeypatch.setattr(broker, key, {})
    for key in ("inuse", "retiring"):
        monkeypatch.setattr(broker, key, set())
    owner = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (owner, owner + "@test.com", "unused", time.time()),
        )
    task = core.create_task(owner, "Browse", mode="work")
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='paused',control='human' WHERE id=%s", (task,)
        )
    now = [1000.0]
    monkeypatch.setattr(broker.time, "time", lambda: now[0])
    n = broker.name(task, "browser")
    names = {n}
    removed = []
    broker.urls[n] = "http://sandbox"
    broker.touch[n] = now[0]
    billing.start_runtime(n, task, "browser")

    async def cmd(*args):
        if args[0] == "ps":
            return "\n".join(names)
        if args[0] == "rm":
            names.discard(args[-1])
            removed.append(args[-1])
            return ""
        raise AssertionError(args)

    async def checkpoint(n):
        pass

    monkeypatch.setattr(broker, "cmd", cmd)
    monkeypatch.setattr(broker, "checkpoint_container", checkpoint)
    return SimpleNamespace(
        owner=owner, task=task, n=n, now=now, names=names, removed=removed
    )


def seconds(owner):
    with core.db() as c:
        return sum(
            json.loads(r["metadata"]).get("seconds", 0)
            for r in c.execute(
                "SELECT metadata FROM usage_operations WHERE owner=%s AND service='browser'",
                (owner,),
            )
        )


def test_passive_requests_do_not_touch_or_restart_meter(live, monkeypatch):
    original = httpx.AsyncClient

    async def fixture(req):
        return httpx.Response(200, content=b"jpeg", request=req)

    monkeypatch.setattr(
        broker.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(fixture)),
    )

    class Request:
        async def json(self):
            return {
                "kind": "resize",
                "args": {"width": 390, "height": 600, "mobile": True},
            }

    async def run():
        live.now[0] = 1060
        await broker.maintain_runtimes()
        live.now[0] = 1119
        await broker.frame_jpg(live.task)
        await broker.dispatch(live.task, "action", Request())
        assert broker.touch[live.n] == 1000
        assert seconds(live.owner) == 60
        for moment in range(1120, 1900, 60):
            live.now[0] = moment
            await broker.maintain_runtimes()
            assert live.n not in live.removed
        live.now[0] = 1899
        await broker.maintain_runtimes()
        assert live.n not in live.removed
        live.now[0] = 1900
        await broker.maintain_runtimes()
        assert live.n in live.removed
        assert seconds(live.owner) == 900
        with pytest.raises(Exception) as e:
            await broker.frame_jpg(live.task)
        assert e.value.status_code == 410
        live.now[0] = 9000
        await broker.maintain_runtimes()
        assert seconds(live.owner) == 900

    asyncio.run(run())


def test_explicit_stop_settles_only_elapsed_time_and_preserves_code(live):
    code = broker.name(live.task)
    live.names.add(code)
    broker.urls[code] = "http://code"
    broker.touch[code] = 1000
    live.now[0] = 1023
    result = asyncio.run(broker.dispatch(live.task, "stop-browser", None))
    assert result["stopped"] and result["scope"] == "browser"
    assert live.removed == [live.n] and code in live.names
    assert seconds(live.owner) == 23 and pending_estimate(live.owner) == 0
    asyncio.run(broker.dispatch(live.task, "stop-browser", None))
    assert seconds(live.owner) == 23


def test_failed_session_save_still_stops_browser_and_billing(live, monkeypatch):
    async def fail(n):
        raise RuntimeError("session service unavailable")

    monkeypatch.setattr(broker, "checkpoint_container", fail)
    live.now[0] = 1012
    result = asyncio.run(broker.retire(live.n))
    assert result["session_warning"] and live.n in live.removed
    assert seconds(live.owner) == 12 and live.n not in broker.stopping


def test_failed_removal_never_resumes_charging(live, monkeypatch):
    real = broker.cmd
    attempt = [0]

    async def cmd(*args):
        if args[0] == "rm" and not attempt[0]:
            attempt[0] += 1
            raise RuntimeError("Docker unavailable")
        return await real(*args)

    monkeypatch.setattr(broker, "cmd", cmd)
    live.now[0] = 1017
    with pytest.raises(RuntimeError):
        asyncio.run(broker.retire(live.n))
    assert broker.stopping[live.n] == 1017 and seconds(live.owner) == 17
    live.now[0] = 2000
    asyncio.run(broker.maintain_runtimes())
    assert seconds(live.owner) == 17 and live.n not in live.names


def test_agent_release_stops_browser_keeps_running_code_service(live, monkeypatch):
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='completed',control='ai',updated=1010 WHERE id=%s",
            (live.task,),
        )
    code = broker.name(live.task)
    live.names.add(code)
    broker.urls[code] = "http://code"
    broker.touch[code] = 1000
    original = httpx.AsyncClient

    async def fixture(req):
        return httpx.Response(
            200, json={"services": [{"status": "running"}]}, request=req
        )

    monkeypatch.setattr(
        broker.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(fixture)),
    )
    live.now[0] = 1010
    result = asyncio.run(broker.dispatch(live.task, "release", None))
    assert result["retained"] and live.n not in live.names and code in live.names
    assert seconds(live.owner) == 10


def test_completed_agent_cleanup_without_release(live):
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='completed',control='ai',updated=1010 WHERE id=%s",
            (live.task,),
        )
    live.now[0] = 1015
    asyncio.run(broker.maintain_runtimes())
    assert seconds(live.owner) == 10 and live.n not in live.names


def test_active_action_is_not_evicted_at_idle_deadline(live):
    broker.use(live.n)
    live.now[0] = 1900
    asyncio.run(broker.maintain_runtimes())
    assert live.n in live.names
    broker.touch[live.n] = 1900
    broker.unuse(live.n)
    assert broker.runtime_cutoff(live.n, 1901) is None


def test_stop_endpoint_owner_and_action_guards(client, monkeypatch):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    task = core.create_task(owner, "Browse", mode="work")
    calls = []

    async def call(task, op, *args):
        calls.append(op)
        return {"stopped": True}

    monkeypatch.setattr(main, "broker", call)
    assert (
        client.post("/api/tasks/" + task + "/browser-stop", headers=h).status_code
        == 409
    )
    assert not calls
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='completed',lease=0,busy=0 WHERE id=%s", (task,)
        )
    assert (
        client.post("/api/tasks/" + task + "/browser-stop", headers=h).status_code
        == 200
    )
    assert calls == ["stop-browser"]
    client.cookies.clear()
    assert (
        client.post("/api/tasks/" + task + "/browser-stop", headers=h).status_code
        == 401
    )


def test_restart_cleans_existing_containers_without_renewing_charges(live, monkeypatch):
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='running',control='ai',updated=1020 WHERE id=%s",
            (live.task,),
        )

    async def inspect(n, kind):
        return "http://sandbox"

    monkeypatch.setattr(broker, "inspect_url", inspect)
    live.now[0] = 1020
    asyncio.run(broker.startup())
    assert live.n not in live.names and seconds(live.owner) == 20
    assert pending_estimate(live.owner) == 0


def test_human_can_close_browser_after_taking_control_of_running_task(
    client, monkeypatch
):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    task = core.create_task(owner, "Browse", mode="work")
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='running',control='human',lease=0,busy=0 WHERE id=%s",
            (task,),
        )

    async def call(task, op, *args):
        assert op == "stop-browser"
        return {"stopped": True}

    monkeypatch.setattr(main, "broker", call)
    assert (
        client.post("/api/tasks/" + task + "/browser-stop", headers=h).status_code
        == 200
    )


def test_code_frame_and_service_polling_do_not_extend_workspace_lifetime(
    live, monkeypatch
):
    code = broker.name(live.task)
    live.names.add(code)
    broker.urls[code] = "http://code"
    broker.touch[code] = 1000
    original = httpx.AsyncClient

    async def fixture(req):
        return httpx.Response(200, json={"services": []}, request=req)

    monkeypatch.setattr(
        broker.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(fixture)),
    )

    class Request:
        async def json(self):
            return {"op": "list"}

    async def run():
        live.now[0] = 1800
        await broker.development_frame(live.task)
        await broker.dispatch(live.task, "services", Request())
        assert broker.touch[code] == 1000
        assert broker.runtime_cutoff(code, 1899) is None
        assert broker.runtime_cutoff(code, 1900) == 1900

    asyncio.run(run())


def test_browser_close_rechecks_task_resumption_under_action_mutex(client, monkeypatch):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    task = core.create_task(owner, "Browse", mode="work")
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='completed',lease=0,busy=0 WHERE id=%s", (task,)
        )
    original = core.begin_action

    def resumed(*args, **kwargs):
        with core.db() as c:
            c.execute("UPDATE tasks SET status='queued' WHERE id=%s", (task,))
        return original(*args, **kwargs)

    async def call(*args, **kwargs):
        raise AssertionError("Must not stop resumed task")

    monkeypatch.setattr(core, "begin_action", resumed)
    monkeypatch.setattr(main, "broker", call)
    response = client.post("/api/tasks/" + task + "/browser-stop", headers=h)
    assert response.status_code == 400 and "resumed" in response.json()["detail"]


@pytest.mark.parametrize("control", ["ai", "human"])
def test_pending_request_has_bounded_response_window(live, control):
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='approval',control=%s,updated=1010 WHERE id=%s",
            (control, live.task),
        )
    # A newly delivered request gives time to fill in details, even if the last
    # browser action happened earlier. Polling does not move the deadline.
    assert broker.runtime_cutoff(live.n, 1130) is None
    assert broker.runtime_cutoff(live.n, 1909) is None
    assert broker.runtime_cutoff(live.n, 1910) == 1910
    broker.stop_meter(live.n, 1100)
    assert broker.runtime_cutoff(live.n, 1150) == 1100


def test_answered_request_returns_to_normal_idle_policy(live):
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='approval',updated=1010 WHERE id=%s", (live.task,)
        )
    assert broker.runtime_cutoff(live.n, 1200) is None
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET status='paused',updated=1200 WHERE id=%s", (live.task,)
        )
    assert broker.runtime_cutoff(live.n, 1899) is None
    assert broker.runtime_cutoff(live.n, 1900) == 1900
