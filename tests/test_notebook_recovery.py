import asyncio, json
import pytest
from app import core, notebook, worker, tools
from test_work_notebook import work


def test_partial_update_preserves_entire_large_entry_and_revision():
    uid, tid, row = work()
    body = "Evidence " * 22000
    created = notebook.write(
        uid,
        tid,
        {"key": "plan", "title": "Verified plan", "text": body, "kind": "checklist"},
    )
    updated = notebook.tool(
        row,
        {},
        {
            "action": "write",
            "key": "plan",
            "status": "done",
            "title": None,
            "text": None,
            "expected_revision": created["revision"],
        },
    )
    assert (
        updated["revision"] == created["revision"] + 1
        and updated["kind"] == "checklist"
    )
    chunks = []
    offset = 0
    while True:
        part = notebook.read(uid, tid, "plan", offset)
        chunks.append(part["text"])
        offset = part["next_offset"]
        if offset is None:
            break
    assert (
        "".join(chunks) == body
        and part["title"] == "Verified plan"
        and part["status"] == "done"
    )
    assert (
        notebook.tool(row, {}, {"action": "write", "key": "plan", "status": "done"})[
            "revision"
        ]
        == updated["revision"]
    )
    with pytest.raises(ValueError, match="changed"):
        notebook.tool(
            row,
            {},
            {
                "action": "write",
                "key": "plan",
                "status": "open",
                "expected_revision": created["revision"],
            },
        )


@pytest.mark.parametrize(
    "args",
    [
        {"action": "write", "title": "Plan", "content": "Run and verify Python"},
        {"action": "write", "key": "plan", "body": "Run and verify Python"},
        {"action": "write", "text": "Run and verify Python"},
        {"action": "write", "title": "Plan", "text": ["Write program", "Run program"]},
        {"action": "write", "title": "Plan", "text": {"next": "Run Python"}},
        {
            "action": "write",
            "title": "Plan",
            "text": "Run Python",
            "kind": None,
            "status": None,
            "expected_revision": None,
        },
    ],
)
def test_common_model_write_shapes_are_saved_without_invented_content(args):
    uid, tid, row = work()
    s = {}
    first = notebook.guarded_tool(row, s, args)
    second = notebook.guarded_tool(row, s, args)
    assert (
        "error" not in first
        and first["key"] == second["key"]
        and first["revision"] == second["revision"]
    )
    assert notebook.read(uid, tid, first["key"])["text"]


@pytest.mark.parametrize(
    "args",
    [
        {},
        [],
        {"action": "write", "key": "missing", "status": "done"},
        {"action": "write", "title": "", "text": "Evidence"},
        {"action": "write", "title": "x" * 201, "text": "Evidence"},
        {"action": "write", "title": "Plan", "text": "x" * 200001},
        {"action": "write", "title": "Plan", "text": "bad\x00text"},
        {"action": "write", "key": ["bad"], "title": "Plan", "text": "Evidence"},
        {"action": "write", "title": "Plan", "text": True},
        {
            "action": "write",
            "title": "Plan",
            "text": "Evidence",
            "expected_revision": True,
        },
        {"action": "read", "key": {}},
        {"action": "read", "key": "overview", "offset": -1},
        {"action": "search", "query": {}},
        {"action": "list", "offset": True},
    ],
)
def test_malformed_notebook_calls_return_actionable_errors_without_mutation(args):
    uid, tid, row = work()
    s = {}
    before = notebook.listing(uid, tid)
    result = notebook.guarded_tool(row, s, args)
    assert result["code"] == "notebook_validation" and result["attempts_remaining"] == 2
    assert (
        "New entry example" in result["recovery"]
        and notebook.listing(uid, tid) == before
    )


def test_repaired_write_resets_failures_but_read_does_not_mask_a_loop():
    uid, tid, row = work()
    s = {}
    notebook.guarded_tool(row, s, {})
    notebook.guarded_tool(row, s, {"action": "read", "key": "overview"})
    assert s["notebook_recovery"]["failures"] == 1
    notebook.guarded_tool(
        row, s, {"action": "write", "key": "overview", "status": "in_progress"}
    )
    assert s["notebook_recovery"]["failures"] == 0


def install_stubs(monkeypatch, model):
    execute = worker.execute

    async def run(row, s, name, args):
        if name == "run_code":
            return {"exit_code": 0, "output": "Hello world\n"}
        return await execute(row, s, name, args)

    async def no_sandbox(*args):
        return {}

    monkeypatch.setattr(worker, "model_call", model)
    monkeypatch.setattr(worker, "execute", run)
    monkeypatch.setattr(worker, "restore", no_sandbox)
    monkeypatch.setattr(worker, "broker", no_sandbox)


def call(id, args):
    return {
        "id": id,
        "type": "function",
        "function": {"name": "work_notebook", "arguments": args},
    }


def test_worker_recovers_from_provider_payload_errors_and_completes_primary_task(
    monkeypatch,
):
    uid, tid, row = work()
    requests = []

    async def model(row, s, available, system):
        requests.append(available)
        if len(requests) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    call("a", "{"),
                    call("b", "[]"),
                    call("c", '{"action":"write","key":"missing"}'),
                ],
            }
        assert (
            "work_notebook" not in [t["function"]["name"] for t in available]
            and notebook.DISABLED in system
        )
        if len(requests) == 2:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "run",
                        "type": "function",
                        "function": {
                            "name": "run_code",
                            "arguments": json.dumps({"command": "python hello.py"}),
                        },
                    }
                ],
            }
        return {
            "role": "assistant",
            "content": "The verified program printed Hello world.",
        }

    install_stubs(monkeypatch, model)
    for _ in range(10):
        row = core.acquire()
        if not row:
            break
        asyncio.run(worker.step(row))
    result = core.owned(uid, tid)
    assert result["status"] == "completed", core.state(result).get("error")
    state = core.state(result)
    assert state["notebook_recovery"]["disabled"] and len(requests) == 3
    assert notebook.search(uid, tid, "Hello world")["matches"]


def test_model_ignoring_disabled_tool_is_paused_after_bounded_attempts(monkeypatch):
    uid, tid, row = work()
    requests = []

    async def model(*args):
        requests.append(True)
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                call(str(len(requests)), '{"action":"write","key":"missing"}')
            ],
        }

    install_stubs(monkeypatch, model)
    for _ in range(15):
        row = core.acquire()
        if not row:
            break
        asyncio.run(worker.step(row))
    result = core.owned(uid, tid)
    assert (
        result["status"] == "paused" and len(requests) == 5 and core.acquire() is None
    )
    assert "prevent repeated charges" in core.state(result)["error"]
    assert notebook.read(uid, tid, "overview")["text"]


def test_followup_resets_recovery_without_discarding_notes(client):
    from conftest import login

    h = login(client)
    with core.db() as c:
        uid = c.execute(
            "SELECT id FROM users WHERE email=%s", ("a@example.com",)
        ).fetchone()[0]
    tid = core.create_task(uid, "Original goal", mode="work")
    row = core.owned(uid, tid)
    s = core.state(row)
    s["notebook_recovery"] = {"failures": 3, "disabled": True, "blocked_calls": 2}
    core.save(row, s, "paused")
    response = client.post(
        "/api/tasks/" + tid + "/command",
        headers=h,
        json={"action": "followup", "text": "Continue with the corrected approach"},
    )
    assert response.status_code == 200, response.text
    assert "notebook_recovery" not in core.state(core.owned(uid, tid))
    assert notebook.read(uid, tid, "overview")["text"] == "Original goal"
