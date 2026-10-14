import asyncio, base64, json, time
import pytest
from app import (
    core,
    accounts,
    billing,
    main,
    worker,
    code_network as net,
    package_proxy as proxy,
)
from test_admin_documents import make_owner
from conftest import login


def current_owner():
    with core.db() as c:
        return c.execute("SELECT id FROM users WHERE email='a@example.com'").fetchone()[
            0
        ]


def admin():
    uid = make_owner()
    accounts.bootstrap("admin@example.com")
    return uid


@pytest.mark.parametrize(
    "text",
    [
        "Let me know if you want any changes.",
        "What is an API? An API exposes operations.",
        "Can you explain the error? Here is the explanation.",
        "Please enter your username in the sample form.",
    ],
)
def test_coding_prose_never_becomes_form(text):
    for state in (
        {"browser_used": True, "coding_used": True},
        {"browser_used": True, "app_preview": {"port": 3000}},
        {"browser_used": True, "input_context": "code"},
        {"browser_used": False},
    ):
        assert worker.input_request({"content": text}, state) is None
        assert worker.completion_reason(state, {"content": text}) == ""


@pytest.mark.parametrize(
    "args",
    [
        {"question": "Which UI do you prefer?"},
        '{"question":"Which UI do you prefer?"}',
        "null",
        "broken",
    ],
)
def test_nonbrowser_ask_user_is_chat_not_approval(monkeypatch, args):
    uid = make_owner()
    tid = core.create_task(uid, "Build an app")
    r = core.acquire()
    s = core.state(r)
    s["coding_used"] = True
    s["browser_used"] = True
    call = {
        "id": "question1",
        "type": "function",
        "function": {"name": "ask_user", "arguments": args},
    }
    s["messages"].append({"role": "assistant", "content": "", "tool_calls": [call]})
    s["pending"] = {"calls": [call], "index": 0}
    core.save(r, s)

    async def forbidden(*a):
        raise AssertionError("No browser or model call needed")

    monkeypatch.setattr(worker, "broker", forbidden)
    monkeypatch.setattr(worker, "model_call", forbidden)
    asyncio.run(worker.step(core.acquire()))
    r = core.owned(uid, tid)
    state = core.state(r)
    assert r["status"] == "completed" and not state["pending"] and state["result"]
    assert main.detail_payload(r, state, [])["approval"] is None
    assert state["messages"][-1]["role"] == "assistant"


@pytest.mark.parametrize(
    "destination",
    [
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.0/8",
        "0.0.0.0/0",
        "::1",
        "fd00::/8",
        "224.0.0.1",
        "64:ff9b::a00:1",
        "https://example.com",
        "example.com/path",
        "evil.*.com",
        "localhost",
    ],
)
def test_network_bad_destinations(destination):
    with pytest.raises(ValueError):
        net.validate({"rules": [{"destination": destination, "ports": [443]}]})


def test_network_policy_inheritance_versions_and_account_only_unrestricted():
    actor = admin()
    uid = make_owner("user@example.com")
    other = make_owner("other@example.com")
    assert set(r["destination"] for r in net.read()["policy"]["rules"]) == set(
        proxy.HOSTS
    )
    net.save(
        actor,
        "global",
        {"rules": [{"destination": "*.Example.COM.", "ports": [443, 80]}]},
        0,
    )
    assert net.effective(uid)["rules"] == [
        {"destination": "*.example.com", "ports": [80, 443]}
    ]
    net.save(
        actor,
        uid,
        {
            "rules": [{"destination": "8.8.8.0/24", "ports": "*"}],
            "inherit": True,
            "unrestricted": False,
        },
        0,
    )
    p = net.effective(uid)
    assert len(p["rules"]) == 2 and len(net.effective(other)["rules"]) == 1
    assert net.permits(p, "dns.google", "8.8.8.8", 53)
    assert net.permits(p, "api.example.com", "1.1.1.1", 443)
    assert not net.permits(p, "example.com", "1.1.1.1", 443)
    assert not net.permits(p, "badexample.com", "1.1.1.1", 443)
    assert not net.permits(p, "api.example.com", "10.0.0.1", 443)
    assert not net.permits(p, "api.example.com", "1.1.1.1", 22)
    with pytest.raises(ValueError):
        net.save(actor, uid, {"rules": [], "inherit": False, "unrestricted": True}, 0)
    with pytest.raises(ValueError):
        net.save(actor, "global", {"rules": [], "unrestricted": True}, 1)
    net.save(actor, uid, {"rules": [], "inherit": False, "unrestricted": True}, 1)
    assert net.permits(net.effective(uid), "elsewhere.com", "1.1.1.1", 22)
    assert not net.permits(net.effective(uid), "metadata", "169.254.169.254", 80)
    with core.db() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM admin_audit WHERE action='code_network_updated'"
            ).fetchone()[0]
            == 3
        )


def test_network_scope_auth_csrf_and_disable_live(client):
    h = login(client)
    assert client.get("/api/admin/code-network/global").status_code == 403
    accounts.bootstrap("a@example.com")
    r = client.get("/api/admin/code-network/global")
    assert r.status_code == 200 and len(r.json()["policy"]["rules"]) == 19
    assert (
        client.put(
            "/api/admin/code-network/global",
            json={"policy": {"rules": []}, "version": 0},
        ).status_code
        == 403
    )
    uid = current_owner()
    tid = core.create_task(uid, "Code")
    assert net.task_policy(tid)["rules"]
    assert (
        client.put(
            "/api/admin/code-network/global",
            headers=h,
            json={"policy": {"rules": []}, "version": 0},
        ).status_code
        == 200
    )
    assert net.task_policy(tid)["rules"] == []
    with core.db() as c:
        c.execute("UPDATE account_settings SET disabled=TRUE WHERE owner=%s", (uid,))
    with pytest.raises(ValueError):
        net.task_policy(tid)


@pytest.mark.parametrize("kind", ["code", "browser"])
def test_conversation_usage_and_stop_scopes(client, monkeypatch, kind):
    h = login(client)
    uid = current_owner()
    tid = core.create_task(uid, "Build app")
    foreign = core.create_task(make_owner("other@example.com"), "Other")
    rid = billing.reserve(
        uid,
        tid,
        0.1,
        model="fixture/model",
        metadata={
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "cached_tokens": 10,
            "reasoning_tokens": 4,
        },
    )
    billing.settle(rid, 0.01)
    hold = billing.reserve(uid, tid, 0.02, model="fixture/other")
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (tid,))
    calls = []

    async def broker(task, op, *a):
        calls.append((task, op))
        return (
            {
                "runtimes": [
                    {"kind": "code", "status": "running", "billing_active": True}
                ]
            }
            if op == "resources"
            else {"stopped": True}
        )

    monkeypatch.setattr(main, "broker", broker)
    r = client.get(f"/api/tasks/{tid}/usage")
    assert r.status_code == 200
    r = r.json()
    assert (
        r["totals"]["input_tokens"] == 120
        and r["totals"]["output_tokens"] == 30
        and r["totals"]["charge"] == 0.01
        and r["totals"]["reserved"] == 0.02
    )
    assert len(r["models"]) == 2 and r["runtime_available"]
    assert client.get(f"/api/tasks/{foreign}/usage").status_code == 404
    assert (
        client.post(f"/api/tasks/{tid}/runtime-stop", json={"kind": kind}).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/tasks/{foreign}/runtime-stop", headers=h, json={"kind": kind}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/tasks/{tid}/runtime-stop", headers=h, json={"kind": kind}
        ).status_code
        == 200
    )
    assert calls[-1] == (tid, "stop-" + kind)
    with core.db() as c:
        c.execute("UPDATE tasks SET status='running' WHERE id=%s", (tid,))
    assert (
        client.post(
            f"/api/tasks/{tid}/runtime-stop", headers=h, json={"kind": kind}
        ).status_code
        == 409
    )


def test_usage_runtime_failure_and_temporary_isolation(client, monkeypatch):
    h = login(client)
    uid = current_owner()
    tid = core.create_task(uid, "Code")

    async def fail(*a):
        raise OSError("private broker details")

    monkeypatch.setattr(main, "broker", fail)
    r = client.get(f"/api/tasks/{tid}/usage").json()
    assert (
        not r["runtime_available"]
        and r["runtimes"] is None
        and "private" not in json.dumps(r)
    )
    tmp = client.post(
        "/api/tasks",
        headers=h,
        json={"prompt": "Hello", "mode": "chat", "temporary": True},
    ).json()["id"]
    r = client.get(f"/api/tasks/{tmp}/usage")
    assert r.status_code == 200 and r.json()["mode"] == "chat"


def test_proxy_real_stream_http_and_live_revocation(monkeypatch):
    async def exercise():
        current = {"rules": [], "unrestricted": True}
        seen = []
        writers = []

        async def upstream(reader, writer):
            writers.append(writer)
            try:
                raw = await reader.read(4096)
                seen.append(raw)
                if raw.startswith(b"GET "):
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
                    )
                    await writer.drain()
                    return
                writer.write(raw)
                await writer.drain()
                await reader.read()
            finally:
                writer.close()

        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        connect = asyncio.open_connection

        async def pinned(ip, p):
            assert ip == "8.8.8.8"
            return await connect("127.0.0.1", port)

        async def policy(task):
            return current

        async def addresses(*a):
            return ["8.8.8.8"]

        monkeypatch.setattr(proxy.asyncio, "open_connection", pinned)
        monkeypatch.setattr(proxy, "policy", policy)
        monkeypatch.setattr(proxy, "public_addresses", addresses)
        service = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        proxyport = service.sockets[0].getsockname()[1]
        tid = core.ident()
        auth = base64.b64encode((tid + ":" + proxy.credential(tid)).encode()).decode()
        try:
            reader, writer = await connect("127.0.0.1", proxyport)
            writer.write(
                f"GET http://example.com/a?q=1 HTTP/1.1\r\nHost: evil.com\r\nProxy-Authorization: Basic {auth}\r\n\r\n".encode()
            )
            await writer.drain()
            assert (await asyncio.wait_for(reader.read(), 3)).endswith(b"ok")
            writer.close()
            assert (
                b"GET /a?q=1" in seen[0]
                and b"Host: example.com" in seen[0]
                and b"Proxy-Authorization" not in seen[0]
            )
            reader, writer = await connect("127.0.0.1", proxyport)
            writer.write(
                f"CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: Basic {auth}\r\n\r\n".encode()
            )
            await writer.drain()
            assert b"200" in await reader.readuntil(b"\r\n\r\n")
            writer.write(b"hello")
            await writer.drain()
            assert await reader.readexactly(5) == b"hello"
            current = {"rules": [], "unrestricted": False}
            assert await asyncio.wait_for(reader.read(), 3) == b""
            writer.close()
        finally:
            for w in writers:
                w.close()
            service.close()
            server.close()
            await service.wait_closed()
            await server.wait_closed()

    asyncio.run(exercise())


def test_upgrade_recovers_only_coding_forms():
    from app import input_routing

    uid = make_owner()
    code = core.create_task(uid, "Code")
    browser = core.create_task(uid, "Browse")
    for tid in (code, browser):
        s = core.state(core.owned(uid, tid))
        s["browser_used"] = True
        if tid == code:
            s["app_preview"] = {"port": 3000}
        s["pending"] = {
            "calls": [
                {
                    "id": "ask",
                    "function": {
                        "name": "ask_user",
                        "arguments": '{"question":"Which theme?"}',
                    },
                }
            ],
            "index": 0,
        }
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET status='approval',state=%s WHERE id=%s",
                (core.enc(json.dumps(s)), tid),
            )
    with core.db() as c:
        input_routing.repair_existing(c)
        input_routing.repair_existing(c)
    assert (
        core.owned(uid, code)["status"] == "completed"
        and core.owned(uid, browser)["status"] == "approval"
    )
    s = core.state(core.owned(uid, code))
    assert s["messages"][-1]["content"] == "Which theme?" and s["pending"] is None


@pytest.mark.parametrize("kind", ["code", "browser"])
def test_broker_stops_only_requested_kind_and_inspection_is_passive(monkeypatch, kind):
    from app import broker

    uid = make_owner()
    tid = core.create_task(uid, "App")
    stopped = []
    for key, value in [
        ("urls", {}),
        ("touch", {}),
        ("inuse", set()),
        ("stopping", {}),
        ("retiring", set()),
    ]:
        monkeypatch.setattr(broker, key, value)

    async def cmd(*args):
        return "\n".join(
            [
                broker.name(tid, "code"),
                broker.name(tid, "browser"),
                broker.name(core.ident(), "code"),
            ]
        )

    async def retire(name):
        stopped.append(name)
        return {"stopped": True}

    monkeypatch.setattr(broker, "cmd", cmd)
    monkeypatch.setattr(broker, "retire", retire)
    result = asyncio.run(broker.dispatch(tid, "resources", None))
    assert len(result["runtimes"]) == 2
    assert all(
        r["status"] == "running" and not r["billing_active"] for r in result["runtimes"]
    )
    assert broker.touch == {} and broker.urls == {}
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM runtime_meters").fetchone()[0] == 0
    asyncio.run(broker.dispatch(tid, "stop-" + kind, None))
    assert stopped == [broker.name(tid, kind)]


@pytest.mark.parametrize("kind", ["code", "browser"])
def test_preview_proxy_is_code_only_and_bypasses_only_loopback(monkeypatch, kind):
    from test_sandbox import sandbox

    monkeypatch.setenv("ASTER_SANDBOX_KIND", kind)
    monkeypatch.setenv("ASTER_CODE_PROXY", "http://workspace:token@172.31.0.1:8093")
    config = sandbox.coding_proxy()
    if kind == "browser":
        assert config == {}
    else:
        assert config == {
            "proxy": {
                "server": "http://172.31.0.1:8093",
                "username": "workspace",
                "password": "token",
                "bypass": "localhost,127.0.0.1,[::1]",
            }
        }
