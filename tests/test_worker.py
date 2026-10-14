import asyncio, json, time
from app import core, worker, providers


def owner():
    id = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (id, "worker@test.com", "not-a-real-password", time.time()),
        )
    return id


def test_worker_model_tool_result_cycle(monkeypatch):
    uid = owner()
    id = core.create_task(uid, "Write and test a Python program")
    responses = [
        {
            "role": "assistant",
            "content": "Running a test",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "run_code",
                        "arguments": '{"command":"python -c \\"print(2+2)\\""}',
                    },
                }
            ],
        },
        {"role": "assistant", "content": "The test printed 4."},
    ]

    async def model(*args):
        return responses.pop(0)

    async def execute(*args):
        return {"exit_code": 0, "output": "4\n"}

    async def restore(*args):
        pass

    monkeypatch.setattr(worker, "model_call", model)
    monkeypatch.setattr(worker, "execute", execute)
    monkeypatch.setattr(worker, "restore", restore)
    for _ in range(3):
        asyncio.run(worker.step(core.acquire()))
    t = core.owned(uid, id)
    assert t["status"] == "completed"
    assert core.state(t)["messages"][2]["role"] == "tool"


def test_interrupted_tool_not_replayed(monkeypatch):
    uid = owner()
    id = core.create_task(uid, "Submit a form")
    r = core.acquire()
    s = core.state(r)
    s["inflight"] = {"name": "browse"}
    worker.persist(r, s)
    core.save(r, s)
    asyncio.run(worker.step(core.acquire()))
    assert core.owned(uid, id)["status"] == "failed"


def test_work_model_does_not_cross_model_fallback_on_404(monkeypatch):
    uid = owner()
    id = core.create_task(uid, "Check something")
    r = core.acquire()
    s = core.state(r)
    primary = s["model"]
    assert primary == "openai/gpt-5.6-luna"
    models = {
        primary: {
            "pricing": {"prompt": "0.000001", "completion": "0.000008"},
            "supported_parameters": ["tools"],
        }
    }

    async def catalog():
        return models

    async def request(*args, **kwargs):
        raise providers.ProviderError("No endpoint", 404)

    monkeypatch.setattr(providers, "catalog", catalog)
    monkeypatch.setattr(providers, "request", request)
    import pytest

    with pytest.raises(providers.ProviderError):
        asyncio.run(providers.model_call(r, s, [], "system"))
    assert s["model"] == primary
    with core.db() as c:
        assert (
            c.execute("SELECT coalesce(sum(amount),0) FROM ledger").fetchone()[0] == 0
        )


def test_no_fabricated_success_after_provider_failure(monkeypatch):
    uid = owner()
    id = core.create_task(uid, "Write a report")

    async def fail(*args):
        raise providers.ProviderError("Invalid key", 401)

    monkeypatch.setattr(worker, "model_call", fail)
    asyncio.run(worker.step(core.acquire()))
    r = core.owned(uid, id)
    assert r["status"] == "failed"
    assert not core.state(r)["result"]


def test_scheduler_enqueues_once_atomically():
    uid = owner()
    with core.db() as c:
        c.execute(
            "INSERT INTO schedules(id,owner,prompt,next,interval) VALUES(%s,%s,%s,%s,%s)",
            (core.ident(), uid, core.enc("Run a scheduled task"), time.time() - 1, 0),
        )
    asyncio.run(worker.scheduler())
    asyncio.run(worker.scheduler())
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert c.execute("SELECT enabled FROM schedules").fetchone()[0] == 0


def test_browser_completion_guard_rejects_intermediate_type_and_enter():
    s = core.initial_state(
        "Browse screener.in, search for msafe and get me the company details", "work"
    )
    s["browser_used"] = True
    s["messages"].append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "b1",
                    "type": "function",
                    "function": {
                        "name": "browse",
                        "arguments": json.dumps(
                            {"action": "navigate", "url": "https://screener.in"}
                        ),
                    },
                }
            ],
        }
    )
    s["messages"].append({"role": "tool", "tool_call_id": "b1", "content": "{}"})
    s["messages"].append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "b2",
                    "type": "function",
                    "function": {
                        "name": "browse",
                        "arguments": json.dumps(
                            {"action": "type", "ref": 3, "text": "msafe"}
                        ),
                    },
                }
            ],
        }
    )
    s["messages"].append({"role": "tool", "tool_call_id": "b2", "content": "{}"})
    assert "only entered" in worker.completion_reason(
        s, {"role": "assistant", "content": "I searched for msafe."}
    )
    s["messages"].append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "b3",
                    "type": "function",
                    "function": {
                        "name": "browse",
                        "arguments": json.dumps({"action": "key", "key": "Enter"}),
                    },
                }
            ],
        }
    )
    s["messages"].append({"role": "tool", "tool_call_id": "b3", "content": "{}"})
    assert "intermediate page" in worker.completion_reason(
        s, {"role": "assistant", "content": "Search submitted."}
    )
    s["messages"].append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "b4",
                    "type": "function",
                    "function": {
                        "name": "browse",
                        "arguments": json.dumps({"action": "observe"}),
                    },
                }
            ],
        }
    )
    s["messages"].append({"role": "tool", "tool_call_id": "b4", "content": "{}"})
    assert "no matching result has been opened" in worker.completion_reason(
        s, {"role": "assistant", "content": "I can see the search results."}
    )


def test_empty_work_completion_is_automatically_requeued(monkeypatch):
    uid = owner()
    tid = core.create_task(uid, "Build a small script and verify it")

    async def model(*args):
        return {"role": "assistant", "content": ""}

    monkeypatch.setattr(worker, "model_call", model)
    asyncio.run(worker.step(core.acquire()))
    row = core.owned(uid, tid)
    state = core.state(row)
    assert row["status"] == "queued"
    assert state["completion_retries"] == 1
    assert state["completion_guard"]
    assert not state["result"]


def test_screener_domain_request_routes_to_interactive_browser():
    hint = worker.routing_hint(
        {
            "messages": [
                {"role": "user", "content": "Browse screener.in and search for MSAFE"}
            ]
        }
    )
    assert "interactive web work" in hint


def test_browser_task_recovers_from_premature_stops_without_user_resend(monkeypatch):
    uid = owner()
    tid = core.create_task(
        uid, "Browse screener.in, search for msafe and get me details", mode="work"
    )

    def call(cid, action, **kwargs):
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": cid,
                    "type": "function",
                    "function": {
                        "name": "browse",
                        "arguments": json.dumps({"action": action, **kwargs}),
                    },
                }
            ],
        }

    responses = [
        call("n1", "navigate", url="https://screener.in"),
        call("t1", "type", ref=4, text="msafe"),
        {"role": "assistant", "content": "I searched for msafe."},
        call("k1", "key", key="Enter"),
        {"role": "assistant", "content": "The search is submitted."},
        call("c1", "click", ref=7),
        {
            "role": "assistant",
            "content": "MSAFE details: verified company detail page content.",
        },
    ]

    async def model(*args):
        return responses.pop(0)

    async def execute(*args):
        return {
            "url": "https://screener.in/company/MSAFE/",
            "title": "MSAFE",
            "body": "company details",
        }

    async def restore(*args):
        pass

    monkeypatch.setattr(worker, "model_call", model)
    monkeypatch.setattr(worker, "execute", execute)
    monkeypatch.setattr(worker, "restore", restore)
    for _ in range(20):
        row = core.acquire()
        if not row:
            break
        asyncio.run(worker.step(row))
    task = core.owned(uid, tid)
    state = core.state(task)
    assert task["status"] == "completed"
    assert state["result"].startswith("MSAFE details:")
    assert sum(1 for m in state["messages"] if m.get("role") == "user") == 1
    assert all(m.get("content") != "I searched for msafe." for m in state["messages"])
    assert not responses
