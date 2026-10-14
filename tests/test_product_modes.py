import asyncio, json, time
from app import core, worker, tools, chat
from app.render import markdown
from conftest import login


def owner(email="mode@test.com"):
    uid = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (uid, email, "not-a-password", time.time()),
        )
    return uid


def test_chat_is_never_acquired_by_work_worker():
    uid = owner()
    tid = core.create_task(uid, "Hello there", mode="chat")
    assert core.acquire() is None
    task = core.owned(uid, tid)
    assert task["mode"] == "chat" and task["status"] == "ready"


def test_chat_direct_turn_has_only_exa_search_tool(monkeypatch):
    uid = owner("chat-search@test.com")
    tid = core.create_task(uid, "What happened today?", mode="chat")
    row = core.owned(uid, tid)
    seen = []

    async def model(row, state, tool_defs, system, on_delta=None):
        seen.append((tool_defs, system))
        if len(seen) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "type": "function",
                        "function": {
                            "name": "search_web",
                            "arguments": json.dumps({"query": "latest US news today"}),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "Here are the **latest** developments."}

    async def exa(row, state, query):
        return [
            {
                "title": "Reuters story",
                "url": "https://www.reuters.com/world/test",
                "text": "Current evidence",
            }
        ]

    monkeypatch.setattr(chat, "model_call_stream", model)
    monkeypatch.setattr(chat, "search", exa)
    asyncio.run(chat.turn(row, initial=True))
    task = core.owned(uid, tid)
    state = core.state(task)
    assert task["status"] == "completed"
    assert {t["function"]["name"] for t in seen[0][0]} == {
        "search_web",
        "suggest_work_mode",
        "work_notebook",
        "read_attachment",
        "recall_work",
    }
    assert "MUST use search_web" in seen[0][1]
    assert (
        state["result"].startswith("Here are")
        and state["sources"][0]["domain"] == "reuters.com"
    )
    assert state["messages"][-1]["sources"][0]["domain"] == "reuters.com"


def test_work_mode_has_full_tools_and_can_create_accounts_without_blanket_approval(
    monkeypatch,
):
    assert (
        tools.requires_approval("browse", {"action": "click", "confirm": False})
        is False
    )
    assert tools.requires_approval("browse", {"action": "type"}) is False
    assert (
        tools.requires_approval("browse", {"action": "click", "confirm": True}) is True
    )
    uid = owner("work@test.com")
    tid = core.create_task(uid, "Create an account for me", mode="work")
    row = core.acquire()
    seen = {}

    async def model(row, state, tool_defs, system):
        seen["tools"] = tool_defs
        seen["system"] = system
        return {
            "role": "assistant",
            "content": "I need your preferred username.",
            "tool_calls": [
                {
                    "id": "q1",
                    "type": "function",
                    "function": {
                        "name": "ask_user",
                        "arguments": json.dumps(
                            {
                                "question": "Preferred username?",
                                "input_type": "text",
                                "browser_takeover": False,
                            }
                        ),
                    },
                }
            ],
        }

    monkeypatch.setattr(worker, "model_call", model)
    asyncio.run(worker.step(row))
    assert any(t["function"]["name"] == "browse" for t in seen["tools"])
    assert "create ordinary online accounts" in seen["system"]


def test_markdown_renderer_handles_rich_markdown_and_blocks_raw_html():
    out = markdown(
        "## Heading\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))"
    )
    assert "<h2>Heading</h2>" in out
    assert "<ul>" in out and "<table>" in out and "<pre>" in out
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert 'href="javascript:' not in out


def test_task_api_records_work_mode_and_returns_rendered_messages(client):
    h = login(client)
    r = client.post("/api/tasks", headers=h, json={"prompt": "# Hello", "mode": "work"})
    assert r.status_code == 200
    tid = r.json()["id"]
    d = client.get("/api/tasks/" + tid).json()
    assert d["mode"] == "work"
    assert d["messages"][0]["role"] == "user"
    assert "<h1>Hello</h1>" in d["messages"][0]["html"]


def test_chat_rejects_browser_and_sandbox_endpoints(client, monkeypatch):
    from app import main

    h = login(client)
    uid = None

    async def fake_turn(row, text=None, initial=False):
        s = core.state(row)
        s["messages"].append({"role": "assistant", "content": "Hi"})
        with core.db() as c:
            c.execute(
                "UPDATE tasks SET state=%s,status='completed' WHERE id=%s",
                (core.enc(json.dumps(s)), row["id"]),
            )
        return s

    monkeypatch.setattr(main, "chat_turn", fake_turn)
    tid = client.post(
        "/api/tasks", headers=h, json={"prompt": "Hello", "mode": "chat"}
    ).json()["id"]
    assert client.get("/api/tasks/" + tid + "/files").status_code == 400
    assert client.get("/api/tasks/" + tid + "/browser-frame").status_code == 400
    assert (
        client.post(
            "/api/tasks/" + tid + "/control", headers=h, json={"owner": "human"}
        ).status_code
        == 400
    )


def test_search_sources_are_deduplicated():
    s = {"sources": []}
    tools.add_sources(
        s,
        [
            {"title": "Example", "url": "https://www.example.com/a"},
            {"title": "Duplicate", "url": "https://www.example.com/a"},
            {"title": "Other", "url": "https://docs.example.org/x"},
        ],
    )
    assert len(s["sources"]) == 2
    assert s["sources"][0]["domain"] == "example.com"


def test_broker_error_parser_accepts_plain_text(monkeypatch):
    class R:
        is_success = False
        status_code = 500
        text = "Internal Server Error"

        def json(self):
            raise ValueError("not json")

    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **k):
            return R()

    monkeypatch.setattr(tools.httpx, "AsyncClient", lambda *a, **k: C())
    import pytest

    with pytest.raises(RuntimeError, match="Internal Server Error"):
        asyncio.run(tools.broker(core.ident(), "run", {}))


def test_openrouter_uses_fixed_model_per_mode_without_cross_model_fallback(monkeypatch):
    from app import providers

    seen = []

    async def models():
        return {
            "google/gemini-3.5-flash-lite": {
                "supported_parameters": ["tools"],
                "pricing": {
                    "prompt": "0.0000003",
                    "completion": "0.0000025",
                    "request": "0",
                },
            },
            "openai/gpt-5.6-luna": {
                "supported_parameters": ["tools"],
                "pricing": {
                    "prompt": "0.000001",
                    "completion": "0.000008",
                    "request": "0",
                },
            },
        }

    async def request(url, body, key, exa=False):
        seen.append(dict(body))
        return {
            "usage": {"cost": 0.001},
            "model": body["model"],
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }

    monkeypatch.setattr(providers, "catalog", models)
    monkeypatch.setattr(providers, "request", request)
    monkeypatch.setattr(providers, "reserve", lambda *a, **k: "r1")
    monkeypatch.setattr(providers, "settle", lambda *a, **k: None)
    monkeypatch.setenv("ASTER_CHAT_MODEL", "google/gemini-3.5-flash-lite")
    monkeypatch.setenv("ASTER_WORK_MODEL", "openai/gpt-5.6-luna")
    chat_state = {
        "mode": "chat",
        "messages": [{"role": "user", "content": "latest news"}],
        "model": "stale/model",
        "cost": 0,
        "budget": 1,
    }
    asyncio.run(
        providers.model_call(
            {"owner": "u", "id": "c", "mode": "chat"},
            chat_state,
            chat.CHAT_TOOLS,
            "system",
        )
    )
    work_state = {
        "mode": "work",
        "messages": [{"role": "user", "content": "browse a site"}],
        "model": "stale/model",
        "cost": 0,
        "budget": 1,
    }
    asyncio.run(
        providers.model_call(
            {"owner": "u", "id": "w", "mode": "work"}, work_state, tools.TOOLS, "system"
        )
    )
    assert seen[0]["model"] == "google/gemini-3.5-flash-lite"
    assert seen[1]["model"] == "openai/gpt-5.6-luna"
    assert "models" not in seen[0] and "models" not in seen[1]
    assert (
        seen[0]["provider"]["allow_fallbacks"]
        and seen[0]["provider"]["require_parameters"]
    )
    assert seen[0]["provider"]["max_price"]["prompt"] == 0.3
    assert (
        seen[1]["provider"]["allow_fallbacks"]
        and seen[1]["provider"]["require_parameters"]
    )
    assert seen[1]["provider"]["max_price"]["completion"] == 8
    assert seen[0]["tools"][0]["function"]["name"] == "search_web"
    assert all(t["function"]["name"] != "switch_model" for t in tools.TOOLS)


def test_work_tools_expose_user_visible_purpose_and_transactional_autonomy(monkeypatch):
    browse = next(t for t in tools.TOOLS if t["function"]["name"] == "browse")[
        "function"
    ]
    code = next(t for t in tools.TOOLS if t["function"]["name"] == "run_code")[
        "function"
    ]
    assert "purpose" in browse["parameters"]["properties"]
    assert "purpose" in code["parameters"]["properties"]
    uid = owner("autonomy@test.com")
    tid = core.create_task(uid, "Book a flight for me", mode="work")
    row = core.acquire()
    seen = {}

    async def model(row, state, tool_defs, system):
        seen["system"] = system
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(worker, "model_call", model)
    asyncio.run(worker.step(row))
    assert 'Do NOT hand the user the website at "checkout"' in seen["system"]
    assert "final action that commits the purchase/charge" in seen["system"]
    assert "call the right tool immediately on the first turn" in seen["system"]


def test_work_followup_resets_turn_sources_and_records_boundary_before_worker_activity(
    client,
):
    h = login(client)
    tid = client.post(
        "/api/tasks", headers=h, json={"prompt": "Research laptops", "mode": "work"}
    ).json()["id"]
    with core.db() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=%s", (tid,)).fetchone()
        s = core.state(r)
        s["sources"] = [
            {"title": "old", "url": "https://old.example", "domain": "old.example"}
        ]
        c.execute(
            "UPDATE tasks SET state=%s,status='completed',lease=0 WHERE id=%s",
            (core.enc(json.dumps(s)), tid),
        )
    r = client.post(
        "/api/tasks/" + tid + "/command",
        headers=h,
        json={"action": "followup", "text": "Now compare tablets"},
    )
    assert r.status_code == 200
    with core.db() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=%s", (tid,)).fetchone()
        state = core.state(row)
        events = c.execute(
            "SELECT kind,body FROM events WHERE task=%s ORDER BY id", (tid,)
        ).fetchall()
    assert state["sources"] == [] and state["searches"] == 0
    assert events[-1]["kind"] == "followup"


def test_routing_hint_prioritizes_interactive_browser_and_current_research():
    assert "interactive web work" in worker.routing_hint(
        {"messages": [{"role": "user", "content": "Book me a flight to New York"}]}
    )
    assert "search_web" in worker.routing_hint(
        {"messages": [{"role": "user", "content": "What is the latest AI news today?"}]}
    )
    assert "code sandbox" in worker.routing_hint(
        {
            "messages": [
                {"role": "user", "content": "Build a Python script and save the file"}
            ]
        }
    )


def test_exa_favicon_is_preserved_as_safe_source_metadata():
    s = {"sources": []}
    tools.add_sources(
        s,
        [
            {
                "title": "Example",
                "url": "https://example.com/story",
                "favicon": "https://example.com/icon.svg",
            }
        ],
    )
    assert s["sources"][0]["favicon"] == "https://example.com/icon.svg"
    bad = {"sources": []}
    tools.add_sources(
        bad,
        [
            {
                "title": "Bad",
                "url": "https://example.com/story",
                "favicon": "javascript:alert(1)",
            }
        ],
    )
    assert "favicon" not in bad["sources"][0]


def test_file_preview_endpoint_returns_read_only_highlighted_html(client, monkeypatch):
    from app import main

    h = login(client)
    tid = client.post(
        "/api/tasks", headers=h, json={"prompt": "Create a Python file", "mode": "work"}
    ).json()["id"]

    async def fake_broker(task, operation, body=None):
        assert operation == "file" and body["op"] == "read"
        return {
            "content": 'print("<safe>")\n',
            "size": 16,
            "lines": 1,
            "truncated": False,
        }

    monkeypatch.setattr(main, "broker", fake_broker)
    r = client.get("/api/tasks/" + tid + "/file?path=demo.py")
    assert r.status_code == 200
    data = r.json()
    assert data["read_only"] is True and data["language"] == "Python"
    assert (
        "<table" in data["html"]
        and "&lt;safe&gt;" in data["html"]
        and "<safe>" not in data["html"]
    )
