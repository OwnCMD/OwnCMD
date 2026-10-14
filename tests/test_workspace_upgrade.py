import asyncio, base64, copy, json, uuid
import pytest
from conftest import login
from app import core, main, browser_state, package_proxy
from test_sandbox import sandbox, sc


def test_owner_browser_profiles_are_encrypted_and_isolated(client):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    state = {
        "cookies": [
            {
                "domain": "example.com",
                "path": "/",
                "name": "session",
                "value": "sensitive-token",
            }
        ],
        "origins": [],
    }
    browser_state.save(owner, browser_state.EMPTY, state)
    assert browser_state.load(owner) == state
    assert browser_state.load(str(uuid.uuid4())) == browser_state.EMPTY
    with core.db() as c:
        assert (
            "sensitive-token"
            not in c.execute(
                "SELECT body FROM browser_profiles WHERE owner=%s", (owner,)
            ).fetchone()[0]
        )
    browser_state.clear(owner)
    assert browser_state.load(owner) == browser_state.EMPTY


def test_three_way_cookie_merge_does_not_resurrect_logout_or_overwrite_other_task():
    a = {"domain": "example.com", "path": "/", "name": "session", "value": "a"}
    base = {"cookies": [a], "origins": []}
    newer = {"cookies": [{**a, "value": "b"}], "origins": []}
    assert browser_state.merge(base, base, newer) == newer
    assert browser_state.merge(base, base, browser_state.EMPTY) == browser_state.EMPTY
    assert browser_state.merge(base, browser_state.EMPTY, base) == browser_state.EMPTY


def test_proxy_allows_only_authenticated_https_registries():
    tid = str(uuid.uuid4())
    token = package_proxy.credential(tid)
    value = "Basic " + base64.b64encode((tid + ":" + token).encode()).decode()
    assert package_proxy.authorized(value)
    assert not package_proxy.authorized(
        "Basic " + base64.b64encode((str(uuid.uuid4()) + ":" + token).encode()).decode()
    )
    assert package_proxy.target("registry.npmjs.org:443") == ("registry.npmjs.org", 443)
    for target in [
        "127.0.0.1:443",
        "registry.npmjs.org.evil.example:443",
        "registry.npmjs.org:80",
        "169.254.169.254:443",
        "user@registry.npmjs.org:443",
    ]:
        with pytest.raises(ValueError):
            package_proxy.target(target)


def test_registry_dns_rebinding_rejected(monkeypatch):
    async def exercise():
        loop = asyncio.get_running_loop()

        async def fake(*a, **k):
            return [(2, 1, 6, "", ("169.254.169.254", 443))]

        monkeypatch.setattr(loop, "getaddrinfo", fake)
        with pytest.raises(ValueError, match="Non-public"):
            await package_proxy.public_address("registry.npmjs.org", 443)

    asyncio.run(exercise())


def test_workspace_routes_enforce_mode_owner_csrf_and_running_lock(client, monkeypatch):
    h = login(client)
    work = client.post(
        "/api/tasks", headers=h, json={"prompt": "Code", "mode": "work"}
    ).json()["id"]
    chat = client.post(
        "/api/tasks", headers=h, json={"prompt": "Chat", "mode": "chat"}
    ).json()["id"]
    assert (
        client.post(
            f"/api/tasks/{work}/workspace", json={"op": "run", "command": "true"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/tasks/{work}/workspace",
            headers=h,
            json={"op": "run", "command": "true"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/tasks/{chat}/workspace",
            headers=h,
            json={"op": "run", "command": "true"},
        ).status_code
        == 400
    )
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (work,))
    calls = []

    async def fake(t, op, b=None):
        calls.append((t, op, b))
        return (
            {"exit_code": 0, "output": "pass"}
            if op == "run"
            else {"data": base64.b64encode(b"archive").decode()}
        )

    monkeypatch.setattr(main, "broker", fake)

    async def cp(t):
        calls.append((t, "checkpoint", None))

    monkeypatch.setattr(main, "checkpoint", cp)
    r = client.post(
        f"/api/tasks/{work}/workspace",
        headers=h,
        json={"op": "run", "command": "echo pass"},
    )
    assert r.status_code == 200 and calls[0][1] == "run" and calls[1][1] == "checkpoint"
    client.post("/api/logout", headers=h, json={})
    h2 = login(client, "other@example.com")
    assert (
        client.post(
            f"/api/tasks/{work}/workspace", headers=h2, json={"op": "services"}
        ).status_code
        == 404
    )
    assert client.get(f"/api/tasks/{work}/workspace-frame").status_code == 404
    assert client.get(f"/api/tasks/{work}/project.zip").status_code == 404


class Locator:
    def __init__(self, page):
        self.page = page

    async def count(self):
        return 1

    async def evaluate(self, *a):
        return {"label": self.page.label, "form": self.page.form}


class Page:
    url = "https://shop.example/checkout"
    label = "Pay now"
    form = "Total CAD 25.00"

    def locator(self, *a):
        return Locator(self)


def test_payment_approval_is_one_use_and_bound_to_amount_and_target():
    async def exercise():
        p = Page()
        args = {"ref": 5}
        result = await sandbox.payment_guard(p, "click", args)
        assert result["approval_required"]
        token = result["approval_token"]
        assert await sandbox.payment_guard(p, "click", args, token) is None
        assert (await sandbox.payment_guard(p, "click", args, token))[
            "approval_required"
        ]
        result = await sandbox.payment_guard(p, "click", args)
        p.form = "Total CAD 250.00"
        assert (
            await sandbox.payment_guard(p, "click", args, result["approval_token"])
        )["approval_required"]
        p.label = "Search"
        p.form = "Search products"
        assert await sandbox.payment_guard(p, "click", args) is None

    asyncio.run(exercise())


def test_checkout_enter_requires_approval():
    async def exercise():
        p = Page()
        p.label = ""
        p.form = "Card number Order total CAD 25.00"
        assert (await sandbox.payment_guard(p, "key", {"key": "Enter"}))[
            "approval_required"
        ]

    asyncio.run(exercise())


def test_project_services_logs_stop_and_archive(sc):
    r = sc.post(
        "/services",
        json={
            "op": "start",
            "name": "test",
            "command": "python3 -u -c 'import time; print(42); time.sleep(30)'",
            "port": 3456,
        },
    )
    assert r.status_code == 200
    r = sc.post("/services", json={"op": "list"})
    assert any(
        s["name"] == "test" and s["status"] == "running" for s in r.json()["services"]
    )
    assert (
        sc.post(
            "/services",
            json={"op": "start", "name": "test", "command": "true", "port": 3456},
        ).status_code
        == 409
    )
    assert (
        sc.post(
            "/services",
            json={"op": "start", "name": "bad", "command": "true", "port": 8001},
        ).status_code
        == 400
    )
    r = sc.post("/services", json={"op": "stop", "name": "test"})
    assert (
        next(s for s in r.json()["services"] if s["name"] == "test")["status"]
        == "stopped"
    )
    sc.post(
        "/file",
        json={"op": "write", "path": "project/src/a.txt", "content": "source survives"},
    )
    assert sc.get("/archive").content[:2] == b"PK"


def test_dependency_tree_is_pruned_from_files_and_snapshots(sc):
    sc.post(
        "/file",
        json={
            "op": "write",
            "path": "project/node_modules/vendor/a.js",
            "content": "dependency",
        },
    )
    assert (
        "project/node_modules/vendor/a.js"
        not in sc.post("/file", json={"op": "list"}).json()["files"]
    )
    import zipfile, io

    snap = sc.post("/snapshot", json={}).json()["data"]
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(snap))) as z:
        assert "project/node_modules/vendor/a.js" not in z.namelist()


def test_browser_cannot_access_development_or_download_project(sc, monkeypatch):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    for path in ["/services", "/dev-action"]:
        assert sc.post(path, json={}).status_code == 403
    for path in ["/dev-frame", "/archive"]:
        assert sc.get(path).status_code == 403


def test_payment_gate_pauses_worker_without_consuming_call(client, monkeypatch):
    from app import worker

    h = login(client)
    tid = client.post(
        "/api/tasks", headers=h, json={"prompt": "Buy after approval", "mode": "work"}
    ).json()["id"]
    row = core.acquire()
    s = core.state(row)
    call = {
        "id": "call-pay",
        "function": {
            "name": "browse",
            "arguments": json.dumps({"action": "click", "ref": 2}),
        },
    }
    s["pending"] = {"calls": [call], "index": 0}
    s["restored"] = True
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET state=%s WHERE id=%s", (core.enc(json.dumps(s)), tid)
        )
    row = core.owned(row["owner"], tid)

    async def execute(*a):
        return {
            "approval_required": True,
            "approval_token": "private-challenge",
            "confirmation_reason": "CAD 25.00 to shop",
        }

    monkeypatch.setattr(worker, "execute", execute)
    asyncio.run(worker.step(row))
    saved = core.owned(row["owner"], tid)
    state = core.state(saved)
    assert saved["status"] == "approval" and state["pending"]["index"] == 0
    assert state["pending"]["payment_challenge"] == "private-challenge"
    public = client.get("/api/tasks/" + tid).json()
    assert "private-challenge" not in json.dumps(public)


def test_sqlite_checkpoint_includes_committed_wal_and_omits_sidecars(sc, tmp_path):
    import sqlite3, zipfile, io

    db = sandbox.root / "notes.sqlite"
    connection = sqlite3.connect(db)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE notes(text)")
        connection.execute("INSERT INTO notes VALUES('survives restart')")
        connection.commit()
        with zipfile.ZipFile(io.BytesIO(sc.get("/archive").content)) as z:
            assert (
                "notes.sqlite-wal" not in z.namelist()
                and "notes.sqlite-shm" not in z.namelist()
            )
            (tmp_path / "restored.sqlite").write_bytes(z.read("notes.sqlite"))
        with sqlite3.connect(tmp_path / "restored.sqlite") as restored:
            assert (
                restored.execute("SELECT text FROM notes").fetchone()[0]
                == "survives restart"
            )
    finally:
        connection.close()
        db.unlink()


def test_broker_eviction_blocks_new_requests_and_keeps_failed_checkpoint(monkeypatch):
    from app import broker as b
    from fastapi import HTTPException

    tid = str(uuid.uuid4())
    n = b.name(tid)
    b.urls[n] = "http://existing"

    async def exercise():
        called = []

        async def checkpoint(name):
            assert name in b.retiring
            with pytest.raises(HTTPException) as error:
                await b.endpoint(tid)
            assert error.value.status_code == 503
            called.append("saved")

        async def cmd(*args):
            called.append("removed")

        monkeypatch.setattr(b, "checkpoint_container", checkpoint)
        monkeypatch.setattr(b, "cmd", cmd)
        await b.retire(n)
        assert (
            called == ["saved", "removed"] and n not in b.urls and n not in b.retiring
        )
        b.urls[n] = "http://existing"

        async def fail(name):
            raise ValueError("disk full")

        monkeypatch.setattr(b, "checkpoint_container", fail)
        with pytest.raises(ValueError):
            await b.retire(n)
        assert n in b.urls and n not in b.retiring and called == ["saved", "removed"]

    try:
        asyncio.run(exercise())
    finally:
        b.forget(n)


def test_broker_checkpoint_encrypts_and_assigns_data_owner(monkeypatch):
    from app import broker as b
    import os

    tid = str(uuid.uuid4())
    n = b.name(tid)
    b.urls[n] = "http://existing"

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            import httpx

            return httpx.Response(
                200,
                json={"data": "private archive"},
                request=httpx.Request("POST", "http://existing"),
            )

    monkeypatch.setattr(b.httpx, "AsyncClient", Client)
    try:
        asyncio.run(b.checkpoint_container(n))
        path = core.DATA / "snapshots" / (tid + ".enc")
        assert (
            core.dec(path.read_text()) == "private archive"
            and "private archive" not in path.read_text()
        )
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_uid == core.DATA.stat().st_uid
    finally:
        b.forget(n)


def test_snapshot_preserves_executable_files(sc):
    import os

    script = sandbox.root / "run-project.sh"
    script.write_text("#!/bin/sh\necho ready\n")
    script.chmod(0o700)
    snapshot = sc.post("/snapshot", json={}).json()["data"]
    script.unlink()
    assert sc.post("/snapshot", json={"restore": snapshot}).status_code == 200
    assert os.access(script, os.X_OK)


def test_expired_browser_profile_cannot_be_resurrected_on_next_save(client):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    state = {
        "cookies": [
            {"domain": "example.com", "path": "/", "name": "old", "value": "expired"}
        ],
        "origins": [],
    }
    browser_state.save(owner, browser_state.EMPTY, state)
    with core.db() as c:
        c.execute("UPDATE browser_profiles SET updated=0 WHERE owner=%s", (owner,))
    assert browser_state.load(owner) == browser_state.EMPTY
    browser_state.save(owner, browser_state.EMPTY, browser_state.EMPTY)
    assert browser_state.load(owner) == browser_state.EMPTY


def test_successful_browser_action_is_not_reported_failed_when_cookie_save_fails(
    monkeypatch,
):
    from app import broker as b
    import httpx

    tid = str(uuid.uuid4())

    class Request:
        async def json(self):
            return {"kind": "click", "args": {"ref": 1}}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            return httpx.Response(
                200,
                json={"url": "https://shop.example/receipt", "text": "Paid"},
                request=httpx.Request("POST", "http://sandbox"),
            )

    async def endpoint(*a, **k):
        return "http://sandbox"

    async def failed_save(*a):
        raise ValueError("Storage full")

    monkeypatch.setattr(b, "endpoint", endpoint)
    monkeypatch.setattr(b, "save_session", failed_save)
    monkeypatch.setattr(b.httpx, "AsyncClient", Client)
    response = asyncio.run(b.dispatch(tid, "action", Request()))
    data = json.loads(response.body)
    assert (
        response.status_code == 200
        and data["text"] == "Paid"
        and data["session_warning"]
    )


def test_browser_pages_cannot_call_internal_session_api_without_container_credential(
    sc, monkeypatch
):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    monkeypatch.setenv("ASTER_SANDBOX_KEY", "container-only-secret")
    assert sc.post("/session", json={}).status_code == 401
    assert (
        sc.post("/session", json={}, headers={"X-Aster-Sandbox": "wrong"}).status_code
        == 401
    )
    assert (
        sc.post(
            "/session", json={}, headers={"X-Aster-Sandbox": "container-only-secret"}
        ).status_code
        == 200
    )


def test_container_capabilities_are_scoped_to_task_and_kind():
    from app import broker as b

    task = str(uuid.uuid4())
    other = str(uuid.uuid4())
    assert b.sandbox_headers(task, "code") != b.sandbox_headers(task, "browser")
    assert b.sandbox_headers(task) != b.sandbox_headers(other)
    assert b.sandbox_headers(task)["X-Aster-Sandbox"] != package_proxy.credential(task)


@pytest.mark.parametrize("operation", ["command", "service"])
def test_workspace_shell_preserves_runtime_path_and_project_home(
    sc, monkeypatch, tmp_path, operation
):
    import os, time

    runtime = tmp_path / "runtime tools"
    runtime.mkdir()
    for tool in ("go", "rustc", "pg_ctl"):
        executable = runtime / tool
        executable.write_text('#!/bin/sh\nprintf "' + tool + '_PATH_OK\\n"\n')
        executable.chmod(0o755)
    # Emulate Debian's login-profile PATH reset, independent of the test host's profile.
    profile = tmp_path / "login-profile.sh"
    profile.write_text("if shopt -q login_shell; then export PATH=/usr/bin:/bin; fi\n")
    monkeypatch.setenv("BASH_ENV", str(profile))
    monkeypatch.setenv("PATH", str(runtime) + os.pathsep + os.environ["PATH"])
    command = 'go && rustc && pg_ctl && printf "PROJECT_HOME=%s\\n" "$HOME"'
    if operation == "command":
        result = sc.post("/run", json={"command": command}).json()
        assert result["exit_code"] == 0, result
    else:
        result = sc.post(
            "/services",
            json={
                "op": "start",
                "name": "runtime-path-check",
                "command": command,
                "port": 3499,
            },
        )
        assert result.status_code == 200, result.text
        for _ in range(100):
            result = next(
                s
                for s in sc.post("/services", json={"op": "list"}).json()["services"]
                if s["name"] == "runtime-path-check"
            )
            if result["status"] == "stopped" and "PROJECT_HOME=" in result["output"]:
                break
            time.sleep(0.01)
        assert result["exit_code"] == 0, result
    output = result["output"]
    for tool in ("go", "rustc", "pg_ctl"):
        assert tool + "_PATH_OK" in output
    assert "PROJECT_HOME=" + str(sandbox.root) in output
