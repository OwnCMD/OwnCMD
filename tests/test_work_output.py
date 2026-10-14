from test_billing import pending_estimate

"""Real worker/ledger/state transitions with deterministic provider responses."""
import asyncio, copy, json, time
import pytest
from app import core, billing, providers, worker, work_output
from conftest import login


def task(owner=None):
    if owner is None:
        owner = core.ident()
        with core.db() as c:
            c.execute(
                "INSERT INTO users VALUES(%s,%s,%s,%s)",
                (owner, owner + "@test.com", "unused", time.time()),
            )
    tid = core.create_task(
        owner, "Implement and verify the requested program", mode="work"
    )
    return owner, tid


def call(key="call", arguments='{"command":"echo verified"}'):
    return {
        "id": key,
        "type": "function",
        "function": {"name": "run_code", "arguments": arguments},
    }


def response(reason="stop", content="Verified and complete.", calls=None, native=None):
    return {
        "id": core.ident(),
        "usage": {
            "cost": 0.001,
            "prompt_tokens": 100,
            "completion_tokens": 6000,
            "completion_tokens_details": {"reasoning_tokens": 5999},
        },
        "choices": [
            {
                "finish_reason": reason,
                "native_finish_reason": native,
                "message": {
                    "role": "assistant",
                    "content": content,
                    **({"tool_calls": calls} if calls else {}),
                },
            }
        ],
    }


def fake_provider(monkeypatch, replies, metadata=None, hook=None):
    bodies = []

    async def catalog():
        return {
            providers.WORK_MODEL_DEFAULT: {
                "context_length": 128000,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "supported_parameters": ["tools"],
                **(metadata or {}),
            }
        }

    async def request(url, body, key):
        bodies.append(copy.deepcopy(body))
        if hook:
            hook(body)
        assert replies, "Unexpected extra paid provider call"
        return replies.pop(0)

    async def broker(*args):
        return {}

    async def restore(*args):
        return None

    monkeypatch.setattr(providers, "catalog", catalog)
    monkeypatch.setattr(providers, "request", request)
    monkeypatch.setattr(worker, "broker", broker)
    monkeypatch.setattr(worker, "restore", restore)
    return bodies


def step():
    row = core.acquire()
    assert row is not None
    asyncio.run(worker.step(row))


@pytest.mark.parametrize(
    "reason,native",
    [
        ("length", None),
        (None, "MAX_TOKENS"),
        ("max_output_tokens", None),
        ("max_completion_tokens", None),
    ],
)
def test_cutoff_recovers_with_larger_budget_and_preserved_work(
    monkeypatch, reason, native
):
    uid, tid = task()
    executed = []
    replies = [
        response("tool_calls", None, [call("before")]),
        response(
            reason,
            "PARTIAL DO NOT DISPLAY",
            [call("unfinished", '{"command":"bad')],
            native,
        ),
        response("tool_calls", None, [call("after")]),
        response(),
    ]
    bodies = fake_provider(monkeypatch, replies)

    async def execute(row, state, name, args):
        executed.append(args)
        return {"exit_code": 0, "output": "verified"}

    monkeypatch.setattr(worker, "execute", execute)
    step()
    step()
    step()
    saved = core.state(core.owned(uid, tid))
    assert saved["pending"] is None and saved["output_recovery"]["consecutive"] == 1
    assert saved["messages"][-1]["tool_call_id"] == "before"
    assert "PARTIAL DO NOT DISPLAY" not in json.dumps(saved)
    # Each acquire reconstructs the persisted state, including after a restart.
    step()
    step()
    step()
    row = core.owned(uid, tid)
    state = core.state(row)
    assert row["status"] == "completed" and state["result"] == "Verified and complete."
    assert [b["max_completion_tokens"] for b in bodies] == [6000, 6000, 12000, 12000]
    assert all("max_tokens" not in b for b in bodies)
    assert len(executed) == 2 and state["output_recovery"]["consecutive"] == 0
    assert "OUTPUT RECOVERY" in bodies[2]["messages"][0]["content"]
    assert "OUTPUT RECOVERY" not in bodies[3]["messages"][0]["content"]
    with core.db() as c:
        rows = c.execute(
            "SELECT * FROM usage_operations WHERE task=%s AND service='model'", (tid,)
        ).fetchall()
    assert len(rows) == 4 and all(r["status"] == "settled" for r in rows)
    assert state["cost"] == pytest.approx(0.004) and pending_estimate(uid) == 0


def test_repeated_cutoff_pauses_without_infinite_retries(monkeypatch):
    uid, tid = task()
    bodies = fake_provider(monkeypatch, [response("length", None) for _ in range(4)])
    for _ in range(4):
        step()
    row = core.owned(uid, tid)
    state = core.state(row)
    assert row["status"] == "paused" and state["output_recovery"]["blocked"]
    assert (
        not state["result"] and len(state["messages"]) == 1 and core.acquire() is None
    )
    assert [b["max_completion_tokens"] for b in bodies] == [6000, 12000, 24000, 48000]
    # Even an old client/external resume cannot restart the automatic paid loop.
    with core.db() as c:
        c.execute("UPDATE tasks SET status='queued' WHERE id=%s", (tid,))
    step()
    assert core.owned(uid, tid)["status"] == "paused" and len(bodies) == 4


@pytest.mark.parametrize(
    "bad",
    [
        call("bad", '{"command":'),
        call("bad", "[]"),
        call("bad", "null"),
        {"id": "bad", "function": None},
        {"function": {"name": "run_code", "arguments": "{}"}},
        "not-a-call",
    ],
)
def test_bad_batch_discarded_before_any_valid_sibling_executes(monkeypatch, bad):
    uid, tid = task()
    bodies = fake_provider(
        monkeypatch, [response("tool_calls", "", [call("valid"), bad]), response()]
    )

    async def never(*args):
        pytest.fail("Incomplete batch executed")

    monkeypatch.setattr(worker, "execute", never)
    step()
    s = core.state(core.owned(uid, tid))
    assert s["pending"] is None and len(s["messages"]) == 1
    step()
    assert core.owned(uid, tid)["status"] == "completed"
    assert [b["max_completion_tokens"] for b in bodies] == [6000, 6000]


def test_duplicate_call_ids_rejected():
    with pytest.raises(work_output.IncompleteOutput):
        work_output.validate_message({"tool_calls": [call(), call()]}, "model", 6000)


def test_structured_arguments_normalized_without_losing_notebook_compatibility():
    message = {"tool_calls": [call(arguments={"command": "echo ok"})]}
    work_output.validate_message(message, "model", 6000)
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "command": "echo ok"
    }
    message = {
        "tool_calls": [
            {
                "id": "note",
                "function": {
                    "name": "work_notebook",
                    "arguments": [{"title": "Plan", "text": "Do the task"}],
                },
            }
        ]
    }
    work_output.validate_message(message, "model", 6000)
    assert isinstance(message["tool_calls"][0]["function"]["arguments"], str)


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"top_provider": {"max_completion_tokens": 8192}}, 8192),
        ({"context_length": 16000}, 8000),
        (
            {"top_provider": {"context_length": 12000, "max_completion_tokens": 10000}},
            6000,
        ),
        ({"top_provider": {"max_completion_tokens": None}}, 48000),
        ({"top_provider": {"max_completion_tokens": "invalid"}}, 48000),
    ],
)
def test_output_budget_respects_model_cap_and_context(metadata, expected):
    state = {"output_recovery": {"model": "model", "limit": 48000}}
    assert (
        work_output.output_limit(
            state, "model", {"context_length": 128000, **metadata}, 6000
        )
        == expected
    )
    assert (
        work_output.output_limit(state, "other", {"context_length": 128000}, 6000)
        == 6000
    )


@pytest.mark.parametrize("status", ["paused", "cancelled"])
def test_user_control_wins_over_inflight_recovery(monkeypatch, status):
    uid, tid = task()

    def control(body):
        with core.db() as c:
            c.execute("UPDATE tasks SET status=%s WHERE id=%s", (status, tid))

    fake_provider(monkeypatch, [response("length")], hook=control)
    step()
    assert core.owned(uid, tid)["status"] == status and core.acquire() is None


def test_total_budget_cannot_be_reset_by_intermittent_valid_output():
    state = {}
    for i in range(work_output.MAX_RECOVERIES):
        assert work_output.recover(state, work_output.IncompleteOutput("model", 6000))
        work_output.accepted(state)
    assert not work_output.recover(
        state, work_output.IncompleteOutput("other-model", 6000)
    )


def test_content_filter_does_not_run_tools_or_trigger_output_retry(monkeypatch):
    uid, tid = task()
    fake_provider(monkeypatch, [response("content_filter", "", [call()])])
    step()
    row = core.owned(uid, tid)
    assert row["status"] == "failed" and not core.state(row).get("output_recovery")
    assert core.state(row)["pending"] is None


def test_followup_resets_recovery_but_resume_cannot_bypass_guard(client, monkeypatch):
    headers = login(client)
    with core.db() as c:
        uid = c.execute("SELECT id FROM users").fetchone()["id"]
    _, tid = task(uid)
    fake_provider(monkeypatch, [response("length") for _ in range(4)])
    for _ in range(4):
        step()
    assert (
        client.post(
            f"/api/tasks/{tid}/command", headers=headers, json={"action": "resume"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/tasks/{tid}/command",
            headers=headers,
            json={"action": "followup", "text": "Continue from saved progress"},
        ).status_code
        == 200
    )
    s = core.state(core.owned(uid, tid))
    assert (
        "output_recovery" not in s
        and s["messages"][-1]["content"] == "Continue from saved progress"
    )
