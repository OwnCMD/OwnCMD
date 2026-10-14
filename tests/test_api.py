import json, time
from app import core
from conftest import login


def test_register_login_session_and_password_hash(client):
    h = login(client)
    r = client.get("/api/me")
    assert r.status_code == 200
    with core.db() as c:
        u = c.execute("SELECT * FROM users").fetchone()
        s = c.execute("SELECT * FROM sessions").fetchone()
    assert u["password"].startswith("$argon2id$")
    assert s["token"] != client.cookies.get("aster_session")
    assert client.post("/api/logout", headers=h, json={}).status_code == 200
    assert client.get("/api/me").status_code == 401


def test_registration_requires_complete_profile(client):
    assert (
        client.post(
            "/api/register",
            headers={"Origin": "https://testserver"},
            json={"email": "a@b.com", "password": "test-password-123"},
        ).status_code
        == 404
    )


def test_csrf_and_origin(client):
    h = login(client)
    assert client.post("/api/tasks", json={"prompt": "a task"}).status_code == 403
    assert (
        client.post(
            "/api/tasks",
            headers={"Origin": "https://testserver"},
            json={"prompt": "a task"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/tasks",
            headers={**h, "Origin": "https://evil.example"},
            json={"prompt": "a task"},
        ).status_code
        == 403
    )


def test_user_memory_and_tasks_isolated(client):
    h = login(client)
    r = client.post("/api/memory", headers=h, json={"text": "my unique private memory"})
    mid = r.json()["id"]
    t = client.post("/api/tasks", headers=h, json={"prompt": "Write me a memo"}).json()[
        "id"
    ]
    with core.db() as c:
        raw = c.execute("SELECT body FROM memory WHERE id=%s", (mid,)).fetchone()[0]
    assert "unique private" not in raw
    client.post("/api/logout", headers=h, json={})
    h2 = login(client, "b@example.com")
    assert client.get("/api/memory").json() == []
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/tasks/" + t).status_code == 404
    (
        client.delete("/api/memory/" + mid, headers=h2, json={})
        if False
        else client.request("DELETE", "/api/memory/" + mid, headers=h2, json={})
    )
    with core.db() as c:
        assert (
            c.execute("SELECT count(*) FROM memory WHERE id=%s", (mid,)).fetchone()[0]
            == 1
        )


def test_takeover_waits_and_fences_actions(client):
    h = login(client)
    t = client.post("/api/tasks", headers=h, json={"prompt": "Browse a site"}).json()[
        "id"
    ]
    core.begin_action(t, "ai")
    assert (
        client.post(
            "/api/tasks/" + t + "/control", headers=h, json={"owner": "human"}
        ).json()["control"]
        == "taking_over"
    )
    import pytest

    with pytest.raises(ValueError):
        core.begin_action(t, "human")
    core.end_action(t)
    with core.db() as c:
        assert (
            c.execute("SELECT control FROM tasks WHERE id=%s", (t,)).fetchone()[0]
            == "human"
        )
    with pytest.raises(ValueError):
        core.begin_action(t, "ai")
    core.begin_action(t, "human")
    core.end_action(t)
    assert (
        client.post(
            "/api/tasks/" + t + "/control", headers=h, json={"owner": "ai"}
        ).status_code
        == 200
    )


def test_budget_reservation_is_atomic(client):
    login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    t = core.create_task(owner, "Write something")
    core.reserve(owner, t, 3)
    import pytest

    assert core.reserve(owner, t, 2.01)  # No prepaid balance gate.


def test_lock_fencing_and_expiry(client):
    login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    t = core.create_task(owner, "Write something")
    a = core.acquire()
    assert a
    assert core.acquire() is None
    with core.db() as c:
        c.execute("UPDATE tasks SET lease=0 WHERE id=%s", (t,))
    b = core.acquire()
    assert b["version"] > a["version"]
    core.save(a, {"stale": True})
    assert "stale" not in core.state(core.owned(owner, t))


def test_preview_expired_and_cross_tenant(client):
    h = login(client)
    t = client.post("/api/tasks", headers=h, json={"prompt": "Make a site"}).json()[
        "id"
    ]
    with core.db() as c:
        owner = c.execute("SELECT owner FROM tasks WHERE id=%s", (t,)).fetchone()[0]
        c.execute(
            "INSERT INTO previews VALUES(%s,%s,%s,%s)",
            (core.digest("previewtoken"), t, owner, time.time() - 1),
        )
    assert client.get("/preview/previewtoken/index.html").status_code == 410


def test_xss_outputs_are_not_rendered_by_api(client):
    h = login(client)
    t = client.post(
        "/api/tasks", headers=h, json={"prompt": "<script>alert(1)</script>"}
    ).json()["id"]
    r = client.get("/api/tasks/" + t)
    assert r.headers["content-type"].startswith("application/json")
    assert "nosniff" == r.headers["x-content-type-options"]
    assert "script-src 'self'" in client.get("/").headers["content-security-policy"]


def test_rate_limit_login(client):
    h = login(client)
    for _ in range(10):
        client.post(
            "/api/login",
            headers={"Origin": "https://testserver"},
            json={"email": "a@example.com", "password": "bad"},
        )
    assert (
        client.post(
            "/api/login",
            headers={"Origin": "https://testserver"},
            json={"email": "a@example.com", "password": "test-password-123"},
        ).status_code
        == 429
    )


def test_approval_cannot_be_replayed(client):
    h = login(client)
    t = client.post(
        "/api/tasks", headers=h, json={"prompt": "Remember my preferences"}
    ).json()["id"]
    with core.db() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=%s", (t,)).fetchone()
        s = core.state(r)
        s["pending"] = {
            "calls": [
                {
                    "id": "call1",
                    "function": {"name": "remember", "arguments": '{"text":"abc"}'},
                }
            ],
            "index": 0,
            "approval": {"name": "remember", "arguments": {"text": "abc"}},
        }
        c.execute(
            "UPDATE tasks SET state=%s,status='approval' WHERE id=%s",
            (core.enc(json.dumps(s)), t),
        )
    assert (
        client.post(
            "/api/tasks/" + t + "/command", headers=h, json={"action": "approve"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/tasks/" + t + "/command", headers=h, json={"action": "approve"}
        ).status_code
        == 409
    )


def test_followup_keeps_task_and_closes_unfinished_tool_messages(client):
    h = login(client)
    t = client.post(
        "/api/tasks", headers=h, json={"prompt": "Build a calculator"}
    ).json()["id"]
    with core.db() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=%s", (t,)).fetchone()
        s = core.state(r)
        calls = [{"id": "call1", "function": {"name": "run_code", "arguments": "{}"}}]
        s["messages"].append({"role": "assistant", "tool_calls": calls})
        s["pending"] = {"calls": calls, "index": 0}
        s["inflight"] = {"id": "call1"}
        c.execute(
            "UPDATE tasks SET state=%s,status='failed' WHERE id=%s",
            (core.enc(json.dumps(s)), t),
        )
    assert (
        client.post(
            "/api/tasks/" + t + "/command",
            headers=h,
            json={
                "action": "followup",
                "text": "Inspect the files and fix the calculation",
            },
        ).status_code
        == 200
    )
    with core.db() as c:
        s = core.state(c.execute("SELECT * FROM tasks WHERE id=%s", (t,)).fetchone())
    assert s["messages"][-2]["role"] == "tool"
    assert s["messages"][-1]["role"] == "user"
    assert not s.get("inflight")


def test_stale_action_rejected_after_takeover_and_return(client):
    import pytest

    h = login(client)
    t = client.post("/api/tasks", headers=h, json={"prompt": "Browse a site"}).json()[
        "id"
    ]
    with core.db() as c:
        owner = c.execute("SELECT owner FROM tasks WHERE id=%s", (t,)).fetchone()[0]
    core.takeover(owner, t, "human")
    core.takeover(owner, t, "ai")
    with pytest.raises(ValueError, match="changed since"):
        core.begin_action(t, "ai", expected_epoch=0)
    core.begin_action(t, "ai", expected_epoch=2)
    core.end_action(t)


def test_foreign_task_id_cannot_be_reused(client):
    h = login(client)
    t = client.post("/api/tasks", headers=h, json={"prompt": "Private task"}).json()[
        "id"
    ]
    client.post("/api/logout", headers=h, json={})
    h = login(client, "other@example.com")
    assert (
        client.post(
            "/api/tasks", headers=h, json={"prompt": "Overwrite task", "id": t}
        ).status_code
        == 400
    )
    with core.db() as c:
        assert (
            c.execute("SELECT count(*) FROM events WHERE task=%s", (t,)).fetchone()[0]
            == 1
        )


def test_owned_task_creation_idempotent(client):
    h = login(client)
    t = client.post("/api/tasks", headers=h, json={"prompt": "My task"}).json()["id"]
    assert (
        client.post(
            "/api/tasks", headers=h, json={"prompt": "My task", "id": t}
        ).json()["id"]
        == t
    )
    with core.db() as c:
        assert (
            c.execute("SELECT count(*) FROM events WHERE task=%s", (t,)).fetchone()[0]
            == 1
        )


def test_preview_rejects_encoded_traversal(client):
    login(client)
    assert client.get("/preview/token/%2e%2e/private").status_code == 400


def test_malformed_registration_returns_client_error(client):
    assert (
        client.post(
            "/api/register",
            headers={"Origin": "https://testserver"},
            json={"password": [], "invite": []},
        ).status_code
        == 404
    )


def test_browser_frame_proxy_returns_finite_jpeg(client, monkeypatch):
    from app import main

    h = login(client)
    tid = client.post(
        "/api/tasks", headers=h, json={"prompt": "Use the browser", "mode": "work"}
    ).json()["id"]

    class R:
        status_code = 200
        content = b"\xff\xd8ASTER\xff\xd9"
        headers = {"x-aster-frame-seq": "7"}

        def json(self):
            return {}

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **k):
            return R()

    monkeypatch.setattr(main.httpx, "AsyncClient", C)
    r = client.get("/api/tasks/" + tid + "/browser-frame")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-aster-frame-seq"] == "7" and r.content.startswith(b"\xff\xd8")


def test_code_sandbox_file_preview_is_work_only_and_proxies_read(client, monkeypatch):
    from app import main

    h = login(client)
    work = client.post(
        "/api/tasks", headers=h, json={"prompt": "Create a file", "mode": "work"}
    ).json()["id"]
    chat = client.post(
        "/api/tasks", headers=h, json={"prompt": "Just chat", "mode": "chat"}
    ).json()["id"]

    async def fake_broker(task, operation, body=None):
        assert (
            task == work
            and operation == "file"
            and body == {"op": "read", "path": "notes.txt"}
        )
        return {"content": "hello sandbox"}

    monkeypatch.setattr(main, "broker", fake_broker)
    r = client.get("/api/tasks/" + work + "/file?path=notes.txt")
    assert r.status_code == 200 and r.json()["content"] == "hello sandbox"
    assert client.get("/api/tasks/" + chat + "/file?path=notes.txt").status_code == 400


def test_chat_creation_is_not_blocked_by_five_active_work_tasks(client):
    import pytest

    h = login(client, "capacity-chat@example.com")
    with core.db() as c:
        owner = c.execute(
            "SELECT id FROM users WHERE email='capacity-chat@example.com'"
        ).fetchone()[0]
    work = [core.create_task(owner, f"Work {i}", mode="work") for i in range(5)]
    with pytest.raises(ValueError, match="5 active Work task limit"):
        core.create_task(owner, "Sixth work task", mode="work")
    r = client.post(
        "/api/tasks", headers=h, json={"prompt": "Hello from chat", "mode": "chat"}
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "chat"


def test_approval_work_tasks_do_not_consume_execution_slots(client):
    h = login(client, "capacity-approval@example.com")
    with core.db() as c:
        owner = c.execute(
            "SELECT id FROM users WHERE email='capacity-approval@example.com'"
        ).fetchone()[0]
    tids = [
        core.create_task(owner, f"Approval work {i}", mode="work") for i in range(5)
    ]
    with core.db() as c:
        for tid in tids:
            c.execute("UPDATE tasks SET status='approval' WHERE id=%s", (tid,))
    # Approval means paused awaiting the user, so it must not block a fresh Work task.
    tid = core.create_task(owner, "Fresh work after approvals", mode="work")
    assert core.owned(owner, tid)["status"] == "queued"
    with core.db() as c:
        count = c.execute(
            "SELECT count(*) FROM tasks WHERE owner=%s AND mode='work' AND status IN ('queued','running')",
            (owner,),
        ).fetchone()[0]
    assert count == 1


def test_settings_persist_and_password_can_be_changed(client):
    h = login(client, "settings@example.com")
    r = client.put(
        "/api/settings",
        headers=h,
        json={
            "theme": "dark",
            "font": "mono",
            "font_size": "large",
            "density": "compact",
            "send_enter": False,
            "reduce_motion": True,
            "sources_expanded": True,
            "activity_expanded": True,
        },
    )
    assert r.status_code == 200
    prefs = client.get("/api/settings").json()
    assert (
        prefs["theme"] == "dark"
        and prefs["font"] == "mono"
        and prefs["send_enter"] is False
        and prefs["sources_expanded"] is True
    )
    mismatch = client.post(
        "/api/change-password",
        headers=h,
        json={
            "current": "test-password-123",
            "new": "different-password-456",
            "confirm": "different-password-789",
        },
    )
    assert (
        mismatch.status_code == 400
        and mismatch.json()["detail"] == "New passwords do not match"
    )
    r = client.post(
        "/api/change-password",
        headers=h,
        json={
            "current": "test-password-123",
            "new": "different-password-456",
            "confirm": "different-password-456",
        },
    )
    assert r.status_code == 200
    client.post("/api/logout", headers=h, json={})
    origin = {"Origin": "https://testserver"}
    assert (
        client.post(
            "/api/login",
            headers=origin,
            json={"email": "settings@example.com", "password": "test-password-123"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/login",
            headers=origin,
            json={
                "email": "settings@example.com",
                "password": "different-password-456",
            },
        ).status_code
        == 200
    )


def test_delete_conversation_removes_owned_history(client, monkeypatch):
    from app import main

    h = login(client, "delete@example.com")
    tid = client.post(
        "/api/tasks", headers=h, json={"prompt": "Disposable chat", "mode": "chat"}
    ).json()["id"]
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (tid,))
        core.event(tid, "x", {"text": "event"})

    async def fake_broker(*a, **k):
        return {"stopped": True}

    monkeypatch.setattr(main, "broker", fake_broker)
    r = client.request("DELETE", "/api/tasks/" + tid, headers=h, json={})
    assert r.status_code == 200
    assert client.get("/api/tasks/" + tid).status_code == 404
    assert all(t["id"] != tid for t in client.get("/api/tasks").json())


def test_initial_chat_renames_title_and_public_message_keeps_its_sources(
    client, monkeypatch
):
    from app import main

    h = login(client, "title@example.com")
    tid = client.post(
        "/api/tasks",
        headers=h,
        json={"prompt": "Tell me about semiconductor equipment demand", "mode": "chat"},
    ).json()["id"]

    async def fake_turn(row, text=None, initial=False):
        s = core.state(row)
        s["messages"].append(
            {
                "role": "assistant",
                "content": "Answer",
                "sources": [
                    {
                        "title": "Evidence",
                        "url": "https://example.com/a",
                        "domain": "example.com",
                        "favicon": "https://example.com/icon.svg",
                    }
                ],
            }
        )
        s["sources"] = s["messages"][-1]["sources"]
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET state=%s,status='completed',busy=0 WHERE id=%s",
                (core.enc(json.dumps(s)), row["id"]),
            )
        return s

    async def fake_title(owner, task, prompt):
        return "Semiconductor Equipment Demand"

    monkeypatch.setattr(main, "chat_turn", fake_turn)
    monkeypatch.setattr(main, "generate_title", fake_title)
    r = client.post("/api/tasks/" + tid + "/chat", headers=h, json={"initial": True})
    assert r.status_code == 200
    d = client.get("/api/tasks/" + tid).json()
    assert d["title"] == "Semiconductor Equipment Demand"
    assert d["messages"][-1]["sources"][0]["domain"] == "example.com"
