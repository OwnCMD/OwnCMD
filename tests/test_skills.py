import asyncio, base64, io, json, stat, time, zipfile
import pytest
from app import (
    core,
    skills,
    skill_packages as pkg,
    skill_providers as provider,
    skill_routes,
    billing,
)
from conftest import login


def package(**kw):
    return {
        "name": "Research brief",
        "description": "Research current public information and verify sources.",
        "tags": ["research", "evidence"],
        "when_to_use": ["Compare current public sources"],
        "when_not_to_use": ["private account changes"],
        "capabilities": ["search_web"],
        "version": 1,
        "instructions": "Search primary sources. Compare dates and evidence. Cite sources.",
        "resources": [
            {
                "path": "references/checklist.md",
                "text": "Check dates and primary evidence.",
            }
        ],
        **kw,
    }


def user():
    id = core.ident()
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (id, id + "@example.com", "hash", time.time()),
        )
    return id


@pytest.fixture
def embed(monkeypatch):
    calls = []

    async def fake(owner, texts, task=None, state=None, **kw):
        calls.append(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]

    async def decide(owner, query, candidates, *a, **kw):
        return {
            "selected_ids": (
                [candidates[0]["id"]]
                if candidates and not skills.negative(query, candidates[0])
                else []
            ),
            "confidence": 0.9,
            "reject_all": False,
        }

    monkeypatch.setattr(provider, "decide", decide)
    monkeypatch.setattr(provider, "embed", fake)
    return calls


def test_roundtrip():
    p = pkg.validate(package())
    assert pkg.import_zip(pkg.export_zip(p)) == p
    assert "instructions" not in pkg.matching_text(
        p
    ) and "Check dates" not in pkg.matching_text(p)


@pytest.mark.parametrize(
    "path",
    [
        "../bad",
        "/etc/passwd",
        "scripts/../../bad",
        "scripts\\bad",
        "scripts//bad",
        "scripts/./bad",
        "scripts/x\x00",
        "C:/bad",
        "bad.py",
        "scripts/",
        "scripts/e\u0301",
    ],
)
def test_resource_paths(path):
    with pytest.raises(ValueError):
        pkg.validate(package(resources=[{"path": path, "text": "x"}]))


@pytest.mark.parametrize(
    "yaml",
    [
        "name: a\nname: b",
        "name: !!python/object/apply:os.system [touch /tmp/bad]",
        "name: &a [*a]",
        "name: [[[[[[a]]]]]]",
        "1: name",
    ],
)
def test_yaml(yaml):
    with pytest.raises(ValueError):
        pkg.parse_markdown(("---\n" + yaml + "\n---\nx").encode())


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("version", True),
        ("version", 0),
        ("tags", "bad"),
        ("tags", ["x"] * 13),
        ("capabilities", ["host_shell"]),
        ("instructions", "x" * 12001),
        ("resources", [{"path": "assets/x", "data": "!!!"}]),
    ],
)
def test_validation(field, value):
    with pytest.raises(ValueError):
        pkg.validate(package(**{field: value}))


def test_duplicate_size():
    with pytest.raises(ValueError):
        pkg.validate(
            package(
                resources=[
                    {"path": "scripts/a", "text": "x"},
                    {"path": "scripts/A", "text": "x"},
                ]
            )
        )
    with pytest.raises(ValueError):
        pkg.validate(
            package(resources=[{"path": "assets/a", "text": "x" * (pkg.MAX_FILE + 1)}])
        )


def zipraw(entries):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SKILL.md", pkg.markdown(pkg.validate(package())))
        for name, body in entries:
            z.writestr(name, body)
    return b.getvalue()


def test_zip_abuse():
    for raw in [
        b"notzip",
        zipraw([("../bad", "x")]),
        zipraw([("assets/x", "a" * 500000)]),
        zipraw([("assets/a", "x"), ("assets/A", "y")]),
    ]:
        with pytest.raises(ValueError):
            pkg.import_zip(raw)
    symlink = zipfile.ZipInfo("scripts/link")
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError):
        pkg.import_zip(zipraw([(symlink, "/etc/passwd")]))


@pytest.mark.parametrize(
    "v", [[], [0, 0], [float("nan")], [float("inf")], ["1"], [True], [1] * 4097]
)
def test_vector_reject(v):
    with pytest.raises(ValueError):
        provider.vector(v)


def test_owner_versions_atomic_pins(embed):
    a, b = user(), user()
    p = asyncio.run(skills.save(a, package()))
    id = p["id"]
    v1 = p["version_id"]
    assert len(skills.listing(a)) == 1 and skills.listing(b) == []
    with pytest.raises(KeyError):
        skills.get(b, id)
    with pytest.raises(KeyError):
        skills.selection(b, {"mode": "selected", "pins": [{"id": id}]})
    pin = skills.selection(a, {"mode": "selected", "pins": [{"id": id}]})
    updated = asyncio.run(
        skills.save(a, package(instructions="New instructions"), id, p["revision"])
    )
    assert (
        skills.get(a, id, v1)["package"]["instructions"].startswith("Search primary")
        and pin["pins"][0]["version_id"] == v1
        and updated["version_id"] != v1
    )
    with pytest.raises(ValueError):
        asyncio.run(skills.save(a, package(), id, p["revision"]))
    assert len(skills.versions(a, id)) == 2
    with core.db() as c:
        with pytest.raises(Exception):
            c.execute(
                "UPDATE skill_versions SET instructions=%s WHERE id=%s", ("bad", v1)
            )


def test_failed_provider_keeps_version(embed, monkeypatch):
    owner = user()
    p = asyncio.run(skills.save(owner, package()))

    async def fail(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(provider, "embed", fail)
    with pytest.raises(RuntimeError):
        asyncio.run(skills.save(owner, package(), p["id"], p["revision"]))
    assert skills.get(owner, p["id"])["version_id"] == p["version_id"]


def test_race_during_embedding(embed, monkeypatch):
    owner = user()
    p = asyncio.run(skills.save(owner, package()))

    async def race(*a, **k):
        skills.status(owner, p["id"], p["revision"], enabled=False)
        return [[1.0, 0.0, 0.0]]

    monkeypatch.setattr(provider, "embed", race)
    with pytest.raises(ValueError):
        asyncio.run(skills.save(owner, package(), p["id"], p["revision"]))
    assert len(skills.versions(owner, p["id"])) == 1


def test_matching_empty_none_selected_and_negative(embed):
    owner = user()
    assert asyncio.run(skills.match(owner, "A query"))["pins"] == [] and embed == []
    p = asyncio.run(skills.save(owner, package()))
    before = len(embed)
    tid = core.create_task(
        owner, "Research brief", mode="work", skills_config={"mode": "none"}
    )
    row = core.owned(owner, tid)
    state = core.state(row)
    asyncio.run(skills.ensure(row, state))
    assert len(embed) == before and not state["skills"]["pins"]
    result = asyncio.run(skills.match(owner, "Use Research brief"))
    assert result["pins"][0]["id"] == p["id"] and result["reranked"]
    assert not asyncio.run(
        skills.match(owner, "Research brief for private account changes")
    )["pins"]
    skills.status(owner, p["id"], p["revision"], enabled=False)
    before = len(embed)
    assert (
        not asyncio.run(skills.match(owner, "Research brief"))["pins"]
        and len(embed) == before
    )


def test_unavailable_pin_fails(embed):
    owner = user()
    p = asyncio.run(skills.save(owner, package()))
    tid = core.create_task(
        owner,
        "Research",
        mode="work",
        skills_config={"mode": "selected", "pins": [{"id": p["id"]}]},
    )
    row = core.owned(owner, tid)
    state = core.state(row)
    skills.status(owner, p["id"], p["revision"], archived=True)
    with pytest.raises(ValueError):
        asyncio.run(skills.ensure(row, state))


def test_stage_only_requested_sandbox_resource(embed):
    owner = user()
    p = asyncio.run(
        skills.save(
            owner,
            package(
                resources=[
                    {"path": "scripts/check.py", "text": "print(42)"},
                    {"path": "references/readme.md", "text": "guide"},
                ]
            ),
        )
    )
    config = skills.selection(owner, {"mode": "selected", "pins": [{"id": p["id"]}]})
    state = {"skills": config}
    calls = []

    async def broker(*a):
        calls.append(a)

    path = skills.root(config["pins"][0]) + "/references/readme.md"
    asyncio.run(skills.stage(owner, "task", state, "read_file", {"path": path}, broker))
    assert len(calls) == 1 and calls[0][1] == "file" and calls[0][2]["path"] == path
    assert "SKILL TRUST BOUNDARY" in skills.prompt(
        owner, state
    ) and "print(42)" not in skills.prompt(owner, state)
    execution = skills.prompt(owner, state)
    assert (
        "SKILL EXECUTION" in execution
        and "two distinct targeted repair attempts" in execution
    )
    assert "Work notebook" in execution and "approved package registries" in execution
    assert (
        "current user request override" in execution
        and "Never fabricate completion" in execution
    )
    assert skills.prompt(owner, {"skills": {"pins": []}}) == ""
    calls.clear()
    asyncio.run(
        skills.stage(
            owner, "task", state, "run_code", {"command": "echo hello"}, broker
        )
    )
    assert not calls


def test_api_auth_csrf_and_drafts(client, embed, monkeypatch):
    assert client.get("/api/skills").status_code == 401
    h = login(client)
    assert (
        client.post(
            "/api/skills",
            headers={"Origin": "https://testserver"},
            json={"package": package()},
        ).status_code
        == 403
    )
    r = client.post("/api/skills", headers=h, json={"package": package()})
    assert r.status_code == 200, r.text
    p = r.json()
    assert client.get("/api/skills/" + p["id"] + "/export").content[:2] == b"PK"
    assert (
        client.put(
            "/api/skills/" + p["id"],
            headers=h,
            json={"package": package(), "expected_revision": -1},
        ).status_code
        == 400
    )

    async def fake(*a, **k):
        return package()

    monkeypatch.setattr(provider, "structured", fake)
    assert (
        "draft"
        in client.post(
            "/api/skills/generate", headers=h, json={"goal": "research"}
        ).json()
    )
    assert len(client.get("/api/skills").json()["skills"]) == 1
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, base_url="https://testserver") as other:
        h2 = login(other, "other@example.com")
        for suffix in ("", "/export", "/versions"):
            assert other.get("/api/skills/" + p["id"] + suffix).status_code == 400
        assert (
            other.request(
                "DELETE",
                "/api/skills/" + p["id"],
                headers=h2,
                json={"expected_revision": p["revision"]},
            ).status_code
            == 400
        )


def test_ambiguous_rerank_valid_reject_invalid_fallback(embed, monkeypatch):
    owner = user()
    asyncio.run(skills.save(owner, package(name="Market research")))
    asyncio.run(skills.save(owner, package(name="Investment analysis")))

    async def decide(*a, **k):
        return {"selected_ids": [], "confidence": 0.9, "reject_all": True}

    monkeypatch.setattr(provider, "decide", decide)
    result = asyncio.run(skills.match(owner, "Compare market investment evidence"))
    assert result["reranked"] and not result["pins"] and result["reasons"]

    async def invalid(*a, **k):
        return {"selected_ids": ["foreign"], "confidence": 0.9, "reject_all": False}

    monkeypatch.setattr(provider, "decide", invalid)
    result = asyncio.run(skills.match(owner, "Compare market investment evidence"))
    assert result["fallback"] and not result["pins"]


def test_followup_policy():
    state = {
        "skills": {"mode": "auto", "pins": [{"id": "old"}], "resolved": True},
        "messages": [
            {"role": "user", "content": "Research renewable energy markets and sources"}
        ],
    }
    skills.followup(state, "continue")
    assert state["skills"]["pins"]
    skills.followup(
        state, "Build a Python program to clean spreadsheet columns and produce charts"
    )
    assert not state["skills"]["resolved"] and state["skill_transitions"]
    for mode in ("none", "selected"):
        state["skills"]["mode"] = mode
        state["skills"]["resolved"] = True
        skills.followup(
            state,
            "Explain ancient Roman pottery techniques and dating methods using books",
        )
        assert state["skills"]["resolved"]


def test_embedding_billing_and_current_model(monkeypatch):
    owner = user()
    assert provider.DEFAULT_MODEL == "google/gemini-embedding-2"
    dim = provider.dimensions()
    calls = []

    async def catalog():
        return {provider.model(): {"pricing": {"prompt": "0.0000002"}}}

    async def request(url, body, key):
        calls.append(body)
        return {
            "id": "embed-1",
            "data": [{"index": 0, "embedding": [1.0] + [0.0] * (dim - 1)}],
            "usage": {"prompt_tokens": 10},
        }

    monkeypatch.setattr(provider, "catalog", catalog)
    monkeypatch.setattr(provider.providers, "request", request)
    result = asyncio.run(provider.embed(owner, ["test"], query=True))
    assert len(result[0]) == 1536 and calls[0]["input"][0].startswith(
        "task: search result | query: "
    )
    with core.db() as c:
        r = c.execute(
            "SELECT * FROM usage_operations WHERE owner=%s", (owner,)
        ).fetchone()
    assert (
        r["service"] == "skill_embedding"
        and r["status"] == "settled"
        and r["charge_nano"] == 2000
    )


def test_rebuild_stale_guard(embed, monkeypatch):
    owner = user()
    p = asyncio.run(skills.save(owner, package()))

    async def race(*a, **k):
        skills.status(owner, p["id"], p["revision"], enabled=False)
        return [[0.0, 1.0, 0.0]]

    monkeypatch.setattr(provider, "embed", race)
    assert asyncio.run(skills.rebuild(owner)) == {"indexed": 0, "stale": 1}


def test_schedule_pin_survives_edit(embed):
    from app import scheduling
    from datetime import datetime, timezone

    owner = user()
    p = asyncio.run(skills.save(owner, package()))
    d = {
        "prompt": "Research public sources",
        "timezone": "UTC",
        "local_start": datetime.fromtimestamp(
            time.time() + 7200, timezone.utc
        ).strftime("%Y-%m-%dT%H:%M"),
        "recurrence": "once",
        "enabled": True,
        "inputs": {},
        "consent": False,
        "skills": {"mode": "selected", "pins": [{"id": p["id"]}]},
    }
    saved = scheduling.save(owner, d)
    pin = scheduling.list_schedules(owner)[0]["skills"]["pins"][0]
    asyncio.run(
        skills.save(owner, package(instructions="Changed"), p["id"], p["revision"])
    )
    assert scheduling.list_schedules(owner)[0]["skills"]["pins"][0] == pin
    result = scheduling.dispatch_due(
        only=saved["id"], owner=owner, manual_token=core.ident()
    )
    assert core.state(core.owned(owner, result["tasks"][0]))["skills"]["pins"][0] == pin


def test_export_repetitive_resources():
    p = pkg.validate(package(resources=[{"path": "assets/x", "text": "a" * 500000}]))
    assert pkg.import_zip(pkg.export_zip(p)) == p


def test_reranker_has_small_output_budget(monkeypatch):
    caps = []

    async def model(row, state, tools, system, max_tokens):
        caps.append(max_tokens)
        assert not tools
        return {"content": "{}"}

    monkeypatch.setattr(provider.providers, "model_call", model)
    asyncio.run(provider.structured("owner", "goal", "skill_rerank"))
    asyncio.run(provider.structured("owner", "goal", "skill_generation"))
    assert caps == [512, 6000]


def test_scrub_secrets():
    result = skill_routes.scrub(
        "password=supersecret\nuser@example.com\nhttps://example.com/preview/123\nOTP 123456\n4111111111111111"
    )
    assert all(
        x not in result
        for x in ("supersecret", "user@example", "https://", "123456", "411111")
    )


@pytest.mark.parametrize(
    "query,rows,expected,ambiguous",
    [
        (
            "Please use Research brief",
            [("Research brief", 0.2, 0), ("Financial analysis", 0.9, 0.5)],
            "Research brief",
            False,
        ),
        (
            "Hello friend",
            [("Research brief", 0.2, 0), ("Financial analysis", 0.3, 0)],
            None,
            False,
        ),
        (
            "Explain changing public evidence",
            [("Research brief", 0.9, 0.7), ("Financial analysis", 0.3, 0)],
            "Research brief",
            False,
        ),
        (
            "Compare financial risks and investment outlook",
            [("Financial research", 0.83, 0.7), ("Investment analysis", 0.82, 0.65)],
            "Financial research",
            True,
        ),
        (
            "Clean financial table data",
            [("Spreadsheet cleanup", 0.85, 0.1), ("Financial research", 0.61, 0.8)],
            None,
            True,
        ),
        (
            "Help me",
            [("Research brief", 0.4, 0), ("Spreadsheet cleanup", 0.42, 0)],
            None,
            False,
        ),
    ],
)
def test_decision_policy_geometry(query, rows, expected, ambiguous):
    items = [
        {
            "id": str(i),
            "metadata": json.dumps(package(name=name)),
            "similarity": sim,
            "lexical": lex,
        }
        for i, (name, sim, lex) in enumerate(rows)
    ]
    candidates, reasons = skills.hybrid(items, query)
    if expected:
        assert candidates[0]["name"] == expected
    elif not ambiguous:
        assert not candidates
    assert bool(reasons) == ambiguous
