import asyncio, json, time
import pytest
from app import core, chat, notebook, temporary, billing, accounts, providers, audit_log
from conftest import login
from test_admin_documents import make_owner


def test_chat_archives_search_and_turn_then_retrieves_old_context(monkeypatch):
    uid = make_owner()
    tid = core.create_task(uid, "Remember the blue project", mode="chat")
    row = core.owned(uid, tid)
    calls = []

    async def model(row, s, tools, system, on_delta=None):
        calls.append(tools)
        assert "work_notebook" in [t["function"]["name"] for t in tools]
        assert "browser" not in [t["function"]["name"] for t in tools]
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "function": {
                            "name": "search_web",
                            "arguments": {"query": "project fact"},
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "Verified blue project fact."}

    async def search(*a):
        return [
            {
                "title": "Evidence",
                "url": "https://example.com",
                "text": "UNIQUE_VERIFIED_FACT",
            }
        ]

    monkeypatch.setattr(chat, "model_call_stream", model)
    monkeypatch.setattr(chat, "search", search)
    asyncio.run(chat.turn(row, initial=True))
    s = core.state(core.owned(uid, tid))
    assert notebook.search(uid, tid, "UNIQUE_VERIFIED_FACT")["matches"]
    assert notebook.search(uid, tid, "Verified blue")["matches"]
    s["messages"] += [
        {"role": "user", "content": "filler " * 3000},
        {"role": "assistant", "content": "filler " * 3000},
    ] * 5
    view = providers.context_messages(s, {"context_length": 16000}, chat.CHAT_TOOLS)
    assert len(view) < len(s["messages"])
    assert "recall_work" in json.dumps(view)
    assert notebook.read(uid, tid, "overview")["text"] == "Remember the blue project"
    other = make_owner("other@test.com")
    with pytest.raises(KeyError):
        notebook.read(other, tid, "overview")
    with core.db() as c:
        c.execute("DELETE FROM events WHERE task=%s", (tid,))
        c.execute("DELETE FROM tasks WHERE id=%s", (tid,))
    with core.db() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM work_notes WHERE task=%s", (tid,)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("temp", [False, True])
def test_chat_notebook_invalid_calls_recover_without_error_loop(monkeypatch, temp):
    uid = make_owner()
    if temp:
        tid = "tmp-" + core.ident()
        temporary.create(
            uid, tid, core.enc(json.dumps(core.initial_state("Hello", "chat")))
        )
        row = temporary.owned(uid, tid)
    else:
        tid = core.create_task(uid, "Hello", mode="chat")
        row = core.owned(uid, tid)
    count = 0

    async def model(row, s, tools, system, on_delta=None):
        nonlocal count
        count += 1
        if count <= 3:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": str(count),
                        "function": {
                            "name": "work_notebook",
                            "arguments": '{"action":"write"}',
                        },
                    }
                ],
            }
        assert "work_notebook" not in [t["function"]["name"] for t in tools]
        return {"role": "assistant", "content": "Here is your answer."}

    monkeypatch.setattr(chat, "model_call_stream", model)
    asyncio.run(chat.turn(row, initial=True))
    saved = temporary.owned(uid, tid) if temp else core.owned(uid, tid)
    assert saved["status"] == "completed" and count == 4
    assert core.state(saved)["notebook_recovery"]["disabled"]
    if temp:
        with core.db() as c:
            assert (
                c.execute(
                    "SELECT count(*) FROM work_notes WHERE task=%s", (tid,)
                ).fetchone()[0]
                == 0
            )
        assert core.state(saved)["_notebook"]
        temporary.discard(uid, tid)
        with pytest.raises(KeyError):
            temporary.owned(uid, tid)


@pytest.mark.parametrize("temp", [False, True])
def test_chat_notebook_partial_write_alias_revision_and_search(temp):
    uid = make_owner()
    tid = core.create_task(uid, "Hello", mode="chat")
    row = core.owned(uid, tid)
    s = core.state(row)
    if temp:
        row = {**row, "id": "tmp-" + core.ident(), "temporary": True}
        temporary.create(uid, row["id"], row["state"])
    result = notebook.guarded_tool(
        row,
        s,
        {
            "action": "write",
            "key": "plan",
            "content": "UNICORN " + ("filler " * 2000) + "TAIL_MARKER",
        },
    )
    assert result["revision"] == 1
    result = notebook.guarded_tool(
        row, s, {"action": "write", "key": "plan", "status": "done"}
    )
    assert result["revision"] == 2
    assert notebook.tool(row, s, {"action": "search", "query": "TAIL_MARKER"})[
        "matches"
    ]
    result = notebook.guarded_tool(
        row,
        s,
        {"action": "write", "key": "plan", "text": "overwrite", "expected_revision": 0},
    )
    assert result["code"] == "notebook_validation"
    page = notebook.tool(row, s, {"action": "read", "key": "plan"})
    assert (
        page["status"] == "done"
        and page["text"].startswith("UNICORN")
        and page["next_offset"]
    )


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_cost_breakdown_includes_search_and_all_services(mode):
    from app.conversation_usage import summary

    uid = make_owner()
    tid = core.create_task(uid, "Costs", mode=mode)
    for service, model in [
        ("model", "fixture/a"),
        ("search", ""),
        ("skill_embedding", "fixture/b"),
        ("code", ""),
    ]:
        rid = billing.reserve(
            uid,
            tid,
            0.1,
            service,
            model,
            metadata={
                "prompt_tokens": 30,
                "completion_tokens": 10,
                "seconds": 12 if service == "code" else 0,
            },
        )
        billing.settle(rid, 0.01)
    billing.reserve(uid, tid, 0.1, "search")
    d = summary(uid, tid)
    assert {x["service"] for x in d["services"]} == {
        "model",
        "search",
        "skill_embedding",
        "code",
    }
    assert d["totals"]["charge"] == pytest.approx(
        sum(x["charge"] for x in d["services"])
    )
    search = next(x for x in d["services"] if x["service"] == "search")
    assert search["requests"] == 2 and search["reserved"] > 0 and search["charge"] > 0
    assert d["totals"]["seconds"] == 12
    assert any(x["status"] == "reserved" for x in d["details"])


def test_audit_filters_pagination_snapshot_and_export(client):
    h = login(client)
    assert client.get("/api/admin/audit").status_code == 403
    assert client.get("/api/admin/audit/export.csv").status_code == 403
    accounts.bootstrap("a@example.com")
    with core.db() as c:
        uid = c.execute("SELECT id FROM users WHERE email='a@example.com'").fetchone()[
            0
        ]
    other = make_owner("target@example.com")
    with core.db() as c:
        for i in range(27):
            accounts.audit(
                c,
                uid,
                other,
                "credit_adjusted",
                {"amount": i, "reason": "=unsafe formula"},
            )
        accounts.audit(
            c,
            uid,
            "global",
            "code_network_updated",
            {
                "before": {"rules": []},
                "after": {"rules": [{"destination": "example.com", "ports": [443]}]},
            },
        )
    r = client.get(
        "/api/admin/audit?q=target@example.com&category=billing&limit=10"
    ).json()
    assert (
        r["total"] == 27
        and len(r["events"]) == 10
        and r["events"][0]["actor_email"] == "a@example.com"
    )
    with core.db() as c:
        accounts.audit(c, uid, other, "credit_adjusted", {"amount": 100})
    r2 = client.get(
        "/api/admin/audit",
        params={
            "q": "target@example.com",
            "category": "billing",
            "snapshot": r["snapshot"],
            "limit": 10,
            "offset": 10,
        },
    ).json()
    assert r2["total"] == 27 and not set(x["id"] for x in r["events"]) & set(
        x["id"] for x in r2["events"]
    )
    assert (
        client.get(
            "/api/admin/audit",
            params={"actor": uid, "target": "global", "action": "code_network_updated"},
        ).json()["total"]
        == 1
    )
    assert (
        client.get("/api/admin/audit", params={"from": time.time() + 10}).status_code
        == 400
    )
    assert client.get("/api/admin/audit?category=invalid").status_code == 400
    assert client.get("/api/admin/audit?from=nan").status_code == 400
    assert client.get("/api/admin/audit?sort=invalid").status_code == 400
    assert client.get("/api/admin/audit?offset=1e99").status_code == 400
    assert client.get("/api/admin/audit?limit=nan").status_code == 400
    csv = client.get("/api/admin/audit/export.csv?category=policy")
    assert (
        csv.status_code == 200
        and "code_network_updated" in csv.text
        and "credit_adjusted" not in csv.text
    )
    assert (
        audit_log.export_csv(
            {
                "events": [
                    {
                        "id": "x",
                        "created": 0,
                        "action": "x",
                        "category": "x",
                        "actor_email": "=1+2",
                        "actor": "a",
                        "target_email": None,
                        "target": "b",
                        "body": {},
                    }
                ]
            }
        )
        .splitlines()[1]
        .find("'=1+2")
        >= 0
    )
    client.post("/api/logout", headers=h)
    assert client.get("/api/admin/audit").status_code == 401


def test_broker_start_status_is_passive(monkeypatch):
    from app import broker
    from fastapi import HTTPException

    tid = core.ident()
    n = broker.name(tid, "browser")
    broker.starting[n] = 1
    try:
        with pytest.raises(HTTPException) as e:
            broker.existing_endpoint(tid, "browser")
        assert e.value.status_code == 503 and "starting" in e.value.detail
        assert n not in broker.urls and n not in broker.touch
    finally:
        broker.starting.pop(n, None)
    with pytest.raises(HTTPException) as e:
        broker.existing_endpoint(tid, "browser")
    assert e.value.status_code == 410


def test_older_long_chat_records_are_readable_after_context_trimming():
    from app import tools

    uid = make_owner()
    tid = core.create_task(uid, "Old chat", mode="chat")
    row = core.owned(uid, tid)
    message = {"role": "assistant", "content": "x" * 26000 + "LAST_DETAIL"}
    s = {"messages": [message]}
    rebuilt = ""
    start = 0
    while True:
        result = asyncio.run(
            tools.execute(row, s, "recall_work", {"offset": 0, "content_offset": start})
        )["records"][0]
        rebuilt += result["message"]
        if result["next_content_offset"] is None:
            break
        start = result["next_content_offset"]
    assert json.loads(rebuilt) == message and "LAST_DETAIL" in rebuilt
