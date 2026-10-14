"""Real API/storage regressions; only paid model/search calls are substituted."""

import asyncio, json, time
import pytest
from app import core, chat, main, temporary, billing
from app.render import markdown
from conftest import login


@pytest.fixture
def model(monkeypatch):
    async def respond(row, state, tools, system, on_delta):
        text = 'A **steady** reply.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint("ok")\n```'
        await on_delta(text[:15])
        await on_delta(text[15:])
        return {"role": "assistant", "content": text}

    monkeypatch.setattr(chat, "model_call_stream", respond)

    async def title(*args):
        return "Saved title"

    monkeypatch.setattr(main, "generate_title", title)
    return respond


def make(client, h, temporary_chat=False, prompt="Private message", images=None):
    response = client.post(
        "/api/tasks",
        headers=h,
        json={
            "mode": "chat",
            "prompt": prompt,
            "temporary": temporary_chat,
            "images": images or [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def finish(client, h, tid):
    response = client.post(f"/api/tasks/{tid}/chat", headers=h, json={"initial": True})
    assert response.status_code == 200, response.text
    return client.get("/api/tasks/" + tid).json()


@pytest.mark.parametrize("ephemeral", [False, True])
def test_stream_completion_saves_first_and_uses_identical_markdown(
    client, monkeypatch, model, ephemeral
):
    h = login(client)
    tid = make(client, h, ephemeral)
    observed = []
    event = core.event

    def checked(tid, kind, body):
        if kind == "chat_completed":
            if ephemeral:
                row = temporary.ROWS[tid]["row"]
            else:
                with core.db() as c:
                    row = c.execute(
                        "SELECT * FROM tasks WHERE id=%s", (tid,)
                    ).fetchone()
            assert row["status"] == "completed" and row["busy"] == 0
            message = core.state(row)["messages"][-1]
            assert message["id"] == body["turn_id"]
            observed.append(message)
        return event(tid, kind, body)

    monkeypatch.setattr(core, "event", checked)
    d = finish(client, h, tid)
    delta = [e for e in d["events"] if e["kind"] == "chat_delta"][-1]
    assert observed and delta["body"]["html"] == d["messages"][-1]["html"]
    assert delta["body"]["turn_id"] == d["messages"][-1]["id"]
    assert "<table>" in delta["body"]["html"] and "<span" in delta["body"]["html"]


def test_temporary_never_persists_content_or_reads_memory(client, monkeypatch, model):
    h = login(client)
    tid = make(client, h, True)
    monkeypatch.setattr(
        core, "memories", lambda *a: pytest.fail("Temporary chat read saved memory")
    )

    async def no_title(*a):
        pytest.fail("Temporary chat generated a saved title")

    monkeypatch.setattr(main, "generate_title", no_title)
    d = finish(client, h, tid)
    assert (
        d["temporary"]
        and d["title"] == "Temporary chat"
        and client.get("/api/tasks").json() == []
    )
    assert (
        client.post(
            f"/api/tasks/{tid}/chat", headers=h, json={"text": "A follow-up"}
        ).status_code
        == 200
    )
    assert len(client.get("/api/tasks/" + tid).json()["messages"]) == 4
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert core.acquire() is None
    assert client.get(f"/api/tasks/{tid}/files").status_code == 400
    assert (
        client.post(
            "/api/tasks",
            headers=h,
            json={"prompt": "Work", "mode": "work", "temporary": True},
        ).status_code
        == 400
    )
    assert client.delete("/api/tasks/" + tid, headers=h).status_code == 200
    assert client.get("/api/tasks/" + tid).status_code == 404
    assert client.delete("/api/tasks/" + tid, headers=h).status_code == 200


def test_temporary_ownership_csrf_logout_and_expiry(client, model, monkeypatch):
    h = login(client)
    tid = make(client, h, True)
    owner = temporary.ROWS[tid]["row"]["owner"]
    with pytest.raises(KeyError):
        temporary.owned("other", tid)
    with pytest.raises(KeyError):
        temporary.discard("other", tid)
    assert (
        client.delete(
            "/api/tasks/" + tid, headers={"Origin": "https://testserver"}
        ).status_code
        == 403
    )
    assert client.post("/api/logout", headers=h).status_code == 200
    assert tid not in temporary.ROWS
    h = login(client, "other@example.com")
    tid = make(client, h, True)
    temporary.ROWS[tid]["touched"] = time.time() - temporary.IDLE_SECONDS - 1
    temporary.sweep()
    assert client.get("/api/tasks/" + tid).status_code == 404


def test_temporary_billing_survives_discard_without_transcript(client, model):
    h = login(client)
    tid = make(client, h, True)
    owner = temporary.ROWS[tid]["row"]["owner"]
    rid = billing.reserve(
        owner,
        tid,
        0.01,
        service="model",
        metadata={"mode": "chat", "prompt_tokens": 20},
    )
    billing.settle(rid, 0.003)
    finish(client, h, tid)
    client.delete("/api/tasks/" + tid, headers=h)
    with core.db() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM usage_operations WHERE task=%s", (tid,)
            ).fetchone()[0]
            == 1
        )
        assert (
            c.execute("SELECT count(*) FROM tasks WHERE id=%s", (tid,)).fetchone()[0]
            == 0
        )


def test_discard_in_flight_never_recreates_temporary_history(client, monkeypatch):
    h = login(client)
    tid = make(client, h, True)

    async def gone(row, state, tools, system, on_delta):
        temporary.discard(row["owner"], tid)
        await on_delta("This must not be saved")
        return {"role": "assistant", "content": "Discarded"}

    monkeypatch.setattr(chat, "model_call_stream", gone)
    assert (
        client.post(
            f"/api/tasks/{tid}/chat", headers=h, json={"initial": True}
        ).status_code
        == 502
    )
    assert tid not in temporary.ROWS
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def offer_model(monkeypatch, capability="code"):
    async def respond(row, state, tools, system, on_delta):
        if state["messages"][-1]["role"] != "tool":
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "proposal",
                        "type": "function",
                        "function": {
                            "name": "suggest_work_mode",
                            "arguments": json.dumps(
                                {
                                    "reason": "Running and testing your program needs the Work code workspace.",
                                    "capability": capability,
                                }
                            ),
                        },
                    }
                ],
            }
        return {
            "role": "assistant",
            "content": "I can continue in Work if you choose to switch.",
        }

    monkeypatch.setattr(chat, "model_call_stream", respond)


@pytest.mark.parametrize("ephemeral", [False, True])
def test_handoff_requires_explicit_confirmation_and_preserves_context(
    client, monkeypatch, model, ephemeral
):
    h = login(client)
    offer_model(monkeypatch)
    images = [{"data_url": "data:image/png;base64,YWJj"}]
    tid = make(client, h, ephemeral, prompt="Run the attached example", images=images)
    d = finish(client, h, tid)
    proposal = d["work_suggestion"]
    with core.db() as c:
        assert (
            c.execute("SELECT count(*) FROM tasks WHERE mode='work'").fetchone()[0] == 0
        )
    path = f"/api/tasks/{tid}/work-handoff"
    assert (
        client.post(
            path, headers=h, json={"action": "accept", "proposal_id": core.ident()}
        ).status_code
        == 400
    )
    assert (
        client.post(
            path,
            headers={"Origin": "https://testserver"},
            json={"action": "accept", "proposal_id": proposal["id"]},
        ).status_code
        == 403
    )
    body = {"action": "accept", "proposal_id": proposal["id"]}
    r = client.post(path, headers=h, json=body)
    assert r.status_code == 200, r.text
    work = r.json()["id"]
    assert client.post(path, headers=h, json=body).json()["id"] == work
    d = client.get("/api/tasks/" + work).json()
    assert d["mode"] == "work" and not d["temporary"] and d["status"] == "queued"
    assert (
        d["messages"][0]["text"] == "Run the attached example"
        and d["messages"][0]["images"]
    )
    with core.db() as c:
        assert (
            c.execute("SELECT count(*) FROM tasks WHERE mode='work'").fetchone()[0] == 1
        )
        row = c.execute("SELECT * FROM tasks WHERE id=%s", (work,)).fetchone()
        assert core.state(row)["model"] == __import__("os").getenv(
            "ASTER_WORK_MODEL", "openai/gpt-5.6-luna"
        )
    assert client.get("/api/tasks/" + tid).json()["mode"] == "chat"


def test_dismissed_and_stale_work_offers_cannot_start_work(client, monkeypatch, model):
    h = login(client)
    tid = make(client, h)
    offer_model(monkeypatch)
    d = finish(client, h, tid)
    pid = d["work_suggestion"]["id"]
    path = f"/api/tasks/{tid}/work-handoff"
    assert (
        client.post(
            path, headers=h, json={"action": "dismiss", "proposal_id": pid}
        ).status_code
        == 200
    )
    assert client.get("/api/tasks/" + tid).json()["work_suggestion"]["dismissed"]
    assert (
        client.post(
            path, headers=h, json={"action": "accept", "proposal_id": pid}
        ).status_code
        == 400
    )
    monkeypatch.setattr(chat, "model_call_stream", model)
    assert (
        client.post(
            f"/api/tasks/{tid}/chat",
            headers=h,
            json={"text": "Just explain it instead"},
        ).status_code
        == 200
    )
    assert client.get("/api/tasks/" + tid).json()["work_suggestion"] is None
    assert (
        client.post(
            path, headers=h, json={"action": "accept", "proposal_id": pid}
        ).status_code
        == 400
    )


def test_invalid_work_capability_is_not_offered(client, monkeypatch, model):
    h = login(client)
    tid = make(client, h)
    offer_model(monkeypatch, "physical-world")
    assert finish(client, h, tid)["work_suggestion"] is None


def test_temporary_claim_prevents_overlapping_turns_and_bounds_capacity(
    client, model, monkeypatch
):
    h = login(client)
    tid = make(client, h, True)
    row = temporary.ROWS[tid]["row"]
    owner = row["owner"]
    temporary.claim(owner, tid)
    with pytest.raises(ValueError, match="still answering"):
        asyncio.run(chat.turn(dict(row), text="duplicate"))
    assert (
        client.post(
            f"/api/tasks/{tid}/chat", headers=h, json={"text": "duplicate"}
        ).status_code
        == 409
    )
    monkeypatch.setattr(temporary, "MAX_BYTES", 10)
    assert (
        client.post(
            "/api/tasks",
            headers=h,
            json={"mode": "chat", "prompt": "Too large", "temporary": True},
        ).status_code
        == 400
    )


def test_handoff_enforces_owner_and_work_capacity(client, monkeypatch, model):
    h = login(client)
    tid = make(client, h)
    offer_model(monkeypatch)
    d = finish(client, h, tid)
    proposal = d["work_suggestion"]["id"]
    with core.db() as c:
        owner = c.execute("SELECT owner FROM tasks WHERE id=%s", (tid,)).fetchone()[0]
    for i in range(5):
        core.create_task(owner, f"Work {i}", mode="work")
    response = client.post(
        f"/api/tasks/{tid}/work-handoff",
        headers=h,
        json={"action": "accept", "proposal_id": proposal},
    )
    assert response.status_code == 400 and "5 active" in response.text
    assert client.post("/api/logout", headers=h).status_code == 200
    other = login(client, "other@example.com")
    assert (
        client.post(
            f"/api/tasks/{tid}/work-handoff",
            headers=other,
            json={"action": "accept", "proposal_id": proposal},
        ).status_code
        == 404
    )


def test_temporary_usage_label_contains_no_prompt(client, model):
    h = login(client)
    tid = make(client, h, True, prompt="Secret finance plan")
    owner = temporary.ROWS[tid]["row"]["owner"]
    rid = billing.reserve(owner, tid, 0.01, service="model", metadata={"mode": "chat"})
    billing.settle(rid, 0.005)
    data = billing.activity(owner)
    assert data["rows"][0]["conversation"] == "Temporary chat"
    assert "Secret finance plan" not in json.dumps(data)
