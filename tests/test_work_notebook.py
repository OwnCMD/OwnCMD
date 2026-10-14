from test_billing import pending_estimate
import asyncio, json, time, base64
import pytest
from app import (
    core,
    notebook,
    research,
    tools,
    artifacts,
    render,
    worker,
    main,
    providers,
)
from test_worker import owner
from test_sandbox import sc, sandbox
from conftest import login


def work():
    uid = owner()
    tid = core.create_task(
        uid, "Research company fundamentals and create a PDF", mode="work"
    )
    return uid, tid, core.owned(uid, tid)


def test_notebook_exists_without_sandbox_and_is_private():
    uid, tid, row = work()
    assert notebook.read(uid, tid, "overview")["text"].startswith("Research company")
    with pytest.raises(KeyError):
        notebook.listing(core.ident(), tid)
    chat = core.create_task(uid, "Chat", mode="chat")
    assert notebook.listing(uid, chat)["entries"][0]["key"] == "overview"
    with pytest.raises(KeyError):
        notebook.listing(core.ident(), chat)


def test_large_note_search_pagination_encryption_and_revision():
    uid, tid, row = work()
    text = (
        "Initial evidence. "
        + ("a " * 30000)
        + "UNIQUE_LIQUIDITY_MARKER cash assets 4500 "
        + ("z " * 30000)
    )
    note = notebook.write(
        uid, tid, {"key": "balance-sheet", "title": "Filed balance sheet", "text": text}
    )
    found = notebook.search(uid, tid, "UNIQUE_LIQUIDITY_MARKER")
    assert "4500" in found["matches"][0]["text"]
    rebuilt = ""
    offset = 0
    while True:
        part = notebook.read(uid, tid, "balance-sheet", offset)
        rebuilt += part["text"]
        if part["next_offset"] is None:
            break
        offset = part["next_offset"]
    assert rebuilt == text
    with core.db() as c:
        raw = c.execute(
            "SELECT body,terms FROM work_note_chunks WHERE task=%s AND key=%s",
            (tid, "balance-sheet"),
        ).fetchall()
    assert all(
        "evidence" not in r["body"] and "UNIQUE_LIQUIDITY_MARKER" not in str(r["terms"])
        for r in raw
    )
    notebook.write(
        uid,
        tid,
        {
            "key": "balance-sheet",
            "title": "Updated",
            "text": "New figure",
            "expected_revision": note["revision"],
        },
    )
    with pytest.raises(ValueError):
        notebook.write(
            uid,
            tid,
            {
                "key": "balance-sheet",
                "title": "Stale",
                "text": "Old figure",
                "expected_revision": note["revision"],
            },
        )
    assert not notebook.search(uid, tid, "UNIQUE_LIQUIDITY_MARKER")["matches"]


def test_checklist_and_summary_survive_model_context_pruning():
    uid, tid, row = work()
    notebook.write(
        uid,
        tid,
        {
            "key": "filing",
            "title": "Read official filing",
            "text": "Verified cash balance is 4500. Source: https://example.com/filing",
            "kind": "checklist",
            "status": "done",
        },
    )
    s = core.state(row)
    s["messages"] += [{"role": "assistant", "content": "x" * 20000} for _ in range(15)]
    assert len(providers.context_messages(s, {"context_length": 32000}, [])) < len(
        s["messages"]
    )
    prompt = notebook.prompt(core.owned(uid, tid))
    assert "4500" in prompt and "done" in prompt and "private task data" in prompt
    notebook.capture(
        row,
        "call-1",
        "run_code",
        {"purpose": "Run tests"},
        {"exit_code": 0, "output": "42 checks passed"},
    )
    assert notebook.search(uid, tid, "checks passed")["matches"]


def test_notebook_api_and_delete_cascade(client, monkeypatch):
    h = login(client)
    with core.db() as c:
        uid = c.execute(
            "SELECT id FROM users WHERE email=%s", ("a@example.com",)
        ).fetchone()["id"]
    tid = core.create_task(uid, "Plan", mode="work")
    assert (
        client.get("/api/tasks/" + tid + "/notebook").json()["entries"][0]["key"]
        == "overview"
    )
    with core.db() as c:
        c.execute("UPDATE tasks SET status='completed' WHERE id=%s", (tid,))

    async def broker(*a):
        return {}

    monkeypatch.setattr(main, "broker", broker)
    assert client.delete("/api/tasks/" + tid, headers=h).status_code == 200
    with core.db() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM work_notes WHERE task=%s", (tid,)
            ).fetchone()[0]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) FROM work_note_chunks WHERE task=%s", (tid,)
            ).fetchone()[0]
            == 0
        )


def test_identical_searches_reuse_without_provider_charge_but_refresh_is_allowed(
    monkeypatch,
):
    uid, tid, row = work()
    s = core.state(row)
    calls = []

    async def search(*a):
        calls.append(a[-1])
        return [
            {
                "url": "https://example.com/filing",
                "title": "Filing",
                "text": "Balance sheet cash 4500",
            }
        ]

    monkeypatch.setattr(tools, "search", search)
    one = asyncio.run(
        tools.execute(row, s, "search_web", {"query": "NVDA balance sheet"})
    )
    two = asyncio.run(
        tools.execute(row, s, "search_web", {"query": "  nvda   balance sheet  "})
    )
    assert len(calls) == 1 and two["reused"] and not one["reused"]
    asyncio.run(
        tools.execute(
            row, s, "search_web", {"query": "NVDA balance sheet", "refresh": True}
        )
    )
    assert len(calls) == 2
    asyncio.run(
        tools.execute(row, s, "search_web", {"query": "NVDA balance sheet 2027"})
    )
    assert len(calls) == 3
    research.state(s)["queries"][research.query_key("NVDA balance sheet")]["at"] -= 301
    asyncio.run(tools.execute(row, s, "search_web", {"query": "NVDA balance sheet"}))
    assert len(calls) == 4


def test_search_no_limit_and_no_false_equivalence(monkeypatch):
    uid, tid, row = work()
    s = core.state(row)
    calls = []

    async def search(*a):
        calls.append(a[-1])
        return [
            {
                "url": "https://example.com/filing",
                "title": "Filing",
                "text": "Unchanged",
            }
        ]

    monkeypatch.setattr(tools, "search", search)
    for i in range(22):
        result = asyncio.run(
            tools.execute(row, s, "search_web", {"query": f"financial gap {i}"})
        )
    assert (
        len(calls) == 22
        and result["new_evidence"] == 0
        and "read_web" in result["next_step"]
    )
    assert len(research.state(s)["queries"]) == 16
    assert "financial gap 21" in research.digest(s)


def test_read_source_finds_late_metric_and_reuses_sections():
    uid, tid, row = work()
    s = core.state(row)
    calls = []

    async def fetch(*a):
        calls.append(a)
        return {
            "title": "Long filing",
            "text": "Overview " * 4000 + "Current assets 12345. " + "Details " * 3000,
        }

    first = asyncio.run(
        research.read(
            row,
            s,
            {"url": "https://example.com/filing", "find": "Current assets"},
            fetch,
        )
    )
    assert "12345" in first["text"] and first["offset"] > 30000
    second = asyncio.run(
        research.read(
            row,
            s,
            {"url": "https://example.com/filing", "offset": first["next_offset"]},
            fetch,
        )
    )
    assert second["reused"] and len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/test",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "file:///etc/passwd",
        "https://a:b@example.com/",
        "http://app.internal",
    ],
)
def test_source_read_rejects_nonpublic_url(url):
    with pytest.raises(ValueError):
        research.public_url(url)


def test_research_json_is_not_cut_mid_result():
    value = {
        "results": [
            {
                "title": "Filing",
                "url": "https://example.com/" + str(i),
                "text": "数" * 4500,
            }
            for i in range(10)
        ]
    }
    encoded = research.serialize(value)
    assert len(encoded) < 40000 and len(json.loads(encoded)["results"]) == 10


@pytest.mark.parametrize(
    "name", ["report.pdf", "reports/Quarterly report.pdf", "reports/été & 20%.pdf"]
)
def test_artifact_links_and_files_are_valid(name):
    state = {"messages": [{"role": "user", "content": "Create report"}]}
    file = artifacts.record("task", state, name, {"size": 42})
    html = render.markdown(
        f'[Download](sandbox:/work/{name.replace(" ","%20")})', "task", [file]
    )
    assert "/api/tasks/task/download?path=" in html and "sandbox:" not in html
    assert artifacts.url("task", name) == file["url"]


def test_placeholder_download_is_verified_and_repaired():
    uid, tid, row = work()
    s = core.state(row)
    msg = {"content": "[Download PDF](#)"}
    calls = []

    async def broker(task, op, body):
        calls.append(body)
        return (
            {"files": ["reports/report.pdf"]}
            if body["op"] == "list"
            else {"size": 42, "name": "report.pdf"}
        )

    assert asyncio.run(artifacts.prepare(row, s, msg, broker)) == ""
    html = render.markdown(msg["content"], tid, artifacts.current(s))
    assert "/download?path=reports%2Freport.pdf" in html and 'href="#"' not in html
    assert calls[-1]["op"] == "info"


def test_missing_download_blocks_completion_and_html_stays_safe():
    uid, tid, row = work()
    s = core.state(row)

    async def broker(*a):
        raise ValueError("missing")

    assert "could not be verified" in asyncio.run(
        artifacts.prepare(
            row, s, {"content": "[PDF](sandbox:/work/missing.pdf)"}, broker
        )
    )
    html = render.markdown(
        "[x](javascript:alert(1)) <script>bad()</script>", "task", []
    )
    assert "<script>" not in html and 'href="javascript:' not in html
    for name in ("../secret", "/etc/passwd", "/work/../../secret", "a\\b"):
        with pytest.raises(ValueError):
            artifacts.path(name)


def test_real_binary_info_download_and_traversal(sc):
    raw = b"%PDF-1.7\n\x00test-binary"
    assert (
        sc.post(
            "/file",
            json={
                "op": "write",
                "path": "report.pdf",
                "data": base64.b64encode(raw).decode(),
            },
        ).status_code
        == 200
    )
    assert sc.post("/file", json={"op": "info", "path": "report.pdf"}).json()[
        "size"
    ] == len(raw)
    assert (
        base64.b64decode(
            sc.post("/file", json={"op": "download", "path": "report.pdf"}).json()[
                "data"
            ]
        )
        == raw
    )
    assert sc.post("/file", json={"op": "info", "path": "../secret"}).status_code == 400


def test_notebook_search_keeps_matching_mode_across_pages():
    uid, tid, row = work()
    notebook.write(
        uid, tid, {"key": "exact", "title": "Exact", "text": "revenue margin"}
    )
    for i in range(8):
        notebook.write(
            uid,
            tid,
            {"key": f"partial-{i}", "title": "Partial", "text": "revenue only"},
        )
    assert len(notebook.search(uid, tid, "revenue margin")["matches"]) == 1
    assert notebook.search(uid, tid, "revenue margin", 6)["matches"] == []
    assert len(notebook.search(uid, tid, "revenue unknown")["matches"]) == 6
    assert len(notebook.search(uid, tid, "revenue unknown", 6)["matches"]) == 3


def test_contents_provider_request_and_billing(monkeypatch):
    from app import billing

    uid, tid, row = work()
    s = core.state(row)
    requests = []

    async def response(url, body, *args):
        requests.append((url, body))
        return {
            "requestId": "contents-one",
            "results": [{"url": "https://example.com", "text": "Full filing"}],
            "costDollars": {"total": 0.001},
        }

    monkeypatch.setattr(providers, "request", response)
    assert (
        asyncio.run(providers.contents(row, s, "https://example.com", True))["text"]
        == "Full filing"
    )
    assert requests == [
        (
            "https://api.exa.ai/contents",
            {
                "urls": ["https://example.com"],
                "text": {"maxCharacters": 200000},
                "maxAgeHours": 0,
            },
        )
    ]
    assert abs(s["cost"] - 0.001) < 1e-8
    billed = billing.activity(uid)["rows"][0]
    assert billed["charge"] == 0.001 and billed["metadata"]["provisional"]
    with core.db() as c:
        meta = json.loads(
            c.execute(
                "SELECT metadata FROM usage_operations WHERE id=%s", (billed["id"],)
            ).fetchone()["metadata"]
        )
    assert meta["type"] == "contents"


@pytest.mark.parametrize("status,pending", [(400, False), (503, True)])
def test_contents_provider_failure_accounting(monkeypatch, status, pending):
    from app import billing

    uid, tid, row = work()
    s = core.state(row)

    async def fail(*args):
        raise providers.ProviderError("Test failure", status)

    monkeypatch.setattr(providers, "request", fail)
    with pytest.raises(providers.ProviderError):
        asyncio.run(providers.contents(row, s, "https://example.com"))
    assert (billing.activity(uid)["rows"][0]["status"] == "pending") == pending
    assert (pending_estimate(uid) > 0) == pending


def test_notebook_endpoint_rejects_other_owner(client):
    login(client)
    uid, tid, row = work()
    assert client.get("/api/tasks/" + tid + "/notebook").status_code == 404
    assert client.get("/api/tasks/" + tid + "/notebook?key=overview").status_code == 404
    assert (
        client.get("/api/tasks/" + tid + "/notebook?query=Research").status_code == 404
    )


def test_multiple_labels_for_same_download_remain_repaired():
    uid, tid, row = work()
    s = core.state(row)
    msg = {
        "content": "[Download PDF](#) or [open report](sandbox:/work/report.pdf) or [Download report.pdf](#)"
    }

    async def broker(task, op, body):
        return (
            {"files": ["report.pdf"]}
            if body["op"] == "list"
            else {"size": 42, "name": "report.pdf"}
        )

    assert asyncio.run(artifacts.prepare(row, s, msg, broker)) == ""
    html = render.markdown(msg["content"], tid, artifacts.current(s))
    assert html.count("/download?path=report.pdf") == 3 and 'href="#"' not in html
    assert len(artifacts.current(s)) == 1
