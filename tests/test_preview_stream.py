import asyncio, base64, json, time
import httpx, pytest
from fastapi import HTTPException
from fastapi.responses import Response
from app import core, main, broker, preview_stream
from test_sandbox import sandbox, sc
from conftest import login


class Session:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.handler = None

    def on(self, event, handler):
        assert event == "Page.screencastFrame"
        self.handler = handler

    async def send(self, method, args=None):
        self.calls.append((method, args))
        return {}

    async def detach(self):
        self.closed = True


@pytest.fixture
def cast(monkeypatch):
    sessions = []

    class Context:
        async def new_cdp_session(self, p):
            s = Session()
            sessions.append(s)
            return s

    class Page:
        url = "https://example.com/page"
        context = Context()

    p = Page()
    for k, v in {
        "cast_lock": asyncio.Lock(),
        "cast_session": None,
        "cast_page": None,
        "cast_users": 0,
        "frame_page": None,
        "frame_cache": b"",
        "frame_seq": 0,
        "frame_ts": 0,
        "frame_url": "",
        "browser": object(),
        "context": p.context,
        "lock": asyncio.Lock(),
    }.items():
        monkeypatch.setattr(sandbox, k, v)

    async def get():
        return p

    monkeypatch.setattr(sandbox, "getpage", get)
    return p, sessions, Page


def test_compositor_is_shared_acknowledged_and_switches_pages(cast):
    p, sessions, Page = cast

    async def run():
        await sandbox.ensure_cast(p)
        await sandbox.ensure_cast(p)
        assert len(sessions) == 1
        first = sessions[0]
        await first.handler(
            {"data": base64.b64encode(b"jpeg").decode(), "sessionId": 123}
        )
        assert sandbox.frame_cache == b"jpeg" and sandbox.frame_seq == 1
        assert first.calls[-1] == ("Page.screencastFrameAck", {"sessionId": 123})
        await sandbox.ensure_cast(Page())
        assert first.closed and len(sessions) == 2
        await first.handler(
            {"data": base64.b64encode(b"stale").decode(), "sessionId": 124}
        )
        assert sandbox.frame_cache == b"jpeg"
        await sandbox.stop_cast()
        assert sessions[-1].closed

    asyncio.run(run())


def test_stream_packets_and_disconnect_release_capture(cast):
    p, sessions, _ = cast

    class Request:
        async def is_disconnected(self):
            return False

    async def run():
        response = await sandbox.live_frames(Request())
        assert sandbox.cast_users == 0 and not sessions
        heartbeat = await anext(response.body_iterator)
        assert json.loads(heartbeat[4:])["length"] == 0
        await sessions[0].handler(
            {"data": base64.b64encode(b"jpeg").decode(), "sessionId": 1}
        )
        packet = await anext(response.body_iterator)
        size = int.from_bytes(packet[:4], "big")
        metadata = json.loads(packet[4 : 4 + size])
        assert (
            metadata["length"] == 4
            and metadata["url"] == p.url
            and packet[4 + size :] == b"jpeg"
        )
        assert sandbox.cast_users == 1
        await response.body_iterator.aclose()
        assert sandbox.cast_users == 0 and sessions[0].closed

    asyncio.run(run())


def test_passive_stream_does_not_launch_browser(cast, monkeypatch):
    monkeypatch.setattr(sandbox, "browser", None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(sandbox.live_frames(None))
    assert error.value.status_code == 410
    monkeypatch.setattr(sandbox, "browser", object())
    monkeypatch.setattr(sandbox, "cast_users", 4)
    with pytest.raises(HTTPException) as error:
        asyncio.run(sandbox.live_frames(None))
    assert error.value.status_code == 429


def test_stream_paths_enforce_sandbox_isolation_and_auth(sc, monkeypatch):
    assert sc.get("/frame-stream").status_code == 403
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    assert sc.get("/dev-stream").status_code == 403
    monkeypatch.setenv("ASTER_SANDBOX_KEY", "private")
    assert sc.get("/frame-stream").status_code == 401


@pytest.mark.parametrize("code", [False, True])
def test_input_acknowledgement_does_not_wait_for_screenshot(cast, monkeypatch, code):
    seen = []
    monkeypatch.setattr(sandbox, "preview_port", 3000)

    async def capture(*args):
        pytest.fail("Input waited for a screenshot")

    async def input(p, kind, args):
        assert sandbox.lock.locked()
        seen.append(kind)

    class Request:
        async def json(self):
            return {
                "kind": "input",
                "args": {"events": [{"kind": "scroll", "args": {"delta": 40}}]},
            }

    monkeypatch.setattr(sandbox, "refresh_frame", capture)
    monkeypatch.setattr(sandbox, "dev_input", input)
    result = asyncio.run((sandbox.dev_action if code else sandbox.action)(Request()))
    assert result["ok"] and seen == ["scroll"]


@pytest.mark.parametrize(
    "kind,operation", [("browser", "frame-stream"), ("code", "dev-stream")]
)
def test_broker_stream_is_passive_and_checks_stop(monkeypatch, kind, operation):
    task = core.ident()
    n = broker.name(task, kind)
    checks = []
    monkeypatch.setattr(broker, "urls", {n: "http://runtime:8001"})
    monkeypatch.setattr(broker, "touch", {n: 123})
    monkeypatch.setattr(broker, "inuse", set())
    monkeypatch.setattr(broker, "stopping", {})
    monkeypatch.setattr(broker, "retiring", set())

    async def relay(url, headers, check):
        assert (
            url == "http://runtime:8001/" + operation
            and headers == broker.sandbox_headers(task, kind)
        )
        check()
        checks.append(check)
        return Response(b"")

    monkeypatch.setattr(preview_stream, "relay", relay)
    asyncio.run(
        (broker.browser_stream if kind == "browser" else broker.development_stream)(
            task
        )
    )
    assert broker.touch[n] == 123 and not broker.inuse
    broker.stopping[n] = 456
    with pytest.raises(HTTPException):
        checks[0]()


@pytest.mark.parametrize("path", ["browser-stream", "workspace-stream"])
def test_api_stream_checks_account_owner_mode_and_session(client, monkeypatch, path):
    assert client.get("/api/tasks/" + core.ident() + "/" + path).status_code == 401
    headers = login(client)
    with core.db() as c:
        uid = c.execute("SELECT id FROM users").fetchone()[0]
    task = core.create_task(uid, "Project", mode="work")
    checks = []

    async def relay(url, headers, check):
        check()
        checks.append(check)
        return Response(b"", media_type=preview_stream.MEDIA)

    monkeypatch.setattr(preview_stream, "relay", relay)
    assert client.get("/api/tasks/" + task + "/" + path).status_code == 200
    assert client.get("/api/tasks/" + core.ident() + "/" + path).status_code == 404
    chat = core.create_task(uid, "Hello", mode="chat")
    assert client.get("/api/tasks/" + chat + "/" + path).status_code == 400
    with core.db() as c:
        c.execute("DELETE FROM sessions")
    with pytest.raises(HTTPException) as err:
        checks[0]()
    assert err.value.status_code == 401


def test_stream_relay_closes_upstream_on_disconnect_or_revocation(monkeypatch):
    original = httpx.AsyncClient
    clients = []
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first"
            yield b"second"

        async def aclose(self):
            closed.append(True)

    async def handler(req):
        return httpx.Response(
            200, headers={"content-type": preview_stream.MEDIA}, stream=Stream()
        )

    def client(**kwargs):
        c = original(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(c)
        return c

    monkeypatch.setattr(preview_stream.httpx, "AsyncClient", client)

    async def run():
        response = await preview_stream.relay("http://fixture", {}, lambda: None)
        assert await anext(response.body_iterator) == b"first"
        await response.body_iterator.aclose()
        assert clients[-1].is_closed and closed

        def revoked():
            raise HTTPException(401, "Session ended")

        response = await preview_stream.relay("http://fixture", {}, revoked)
        assert [x async for x in response.body_iterator] == [] and clients[-1].is_closed
        response = await preview_stream.relay("http://fixture", {}, lambda: None)

        async def send(message):
            raise OSError("Disconnected before response headers")

        with pytest.raises(Exception):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}}, None, send
            )
        assert clients[-1].is_closed

    asyncio.run(run())


def test_preview_input_keeps_long_conversation_state_unchanged(client, monkeypatch):
    headers = login(client)
    with core.db() as c:
        uid = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(uid, "Project", mode="work")
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (tid,))
        before = c.execute("SELECT state FROM tasks WHERE id=%s", (tid,)).fetchone()[0]

    async def broker(*args):
        return {"ok": True}

    monkeypatch.setattr(main, "broker", broker)
    r = client.post(
        "/api/tasks/" + tid + "/workspace",
        headers=headers,
        json={
            "op": "preview",
            "kind": "input",
            "args": {"events": [{"kind": "text", "args": {"text": "hello"}}]},
        },
    )
    assert r.status_code == 200
    with core.db() as c:
        assert (
            c.execute("SELECT state FROM tasks WHERE id=%s", (tid,)).fetchone()[0]
            == before
        )
