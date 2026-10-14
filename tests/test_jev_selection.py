import asyncio, json, math
import pytest
from app import core, skills, billing, skill_providers as provider
from test_skills import user, package, embed


def candidates(n=2):
    return [{"id": f"skill-{i}", **package(name=f"Research {i}")} for i in range(n)]


def response(choice="c0", confidence=0.9, n=2):
    return {
        "id": "jev-request",
        "model": "typesafe/jev-1.13-20260917",
        "usage": {"input_tokens": 100, "output_tokens": 10, "cost": 0.0000042},
        "answers": {
            "primary": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {
                    **{f"c{i}": 0.9 if choice == f"c{i}" else 0.05 for i in range(n)},
                    "none": 0.9 if choice == "none" else 0.05,
                },
            },
            **{
                f"include_c{i}": {
                    "type": "noul",
                    "noul": 0.9 if i == 0 or choice == f"c{i}" else 0.2,
                }
                for i in range(n)
            },
        },
    }


def test_jev_request_uses_decisions_api_and_actual_billed_cost(monkeypatch):
    owner = user()
    state = {"cost": 0}
    calls = []

    async def request(url, body, key):
        calls.append((url, body))
        return response()

    monkeypatch.setattr(provider.providers, "request", request)
    result = asyncio.run(
        provider.decide(owner, "Research public sources", candidates(), state=state)
    )
    assert (
        calls[0][0] == "https://openrouter.ai/api/alpha/decisions"
        and calls[0][1]["model"] == "typesafe/jev-1.13"
    )
    assert (
        "messages" not in calls[0][1]
        and "none" in calls[0][1]["questions"]["primary"]["criteria"]
    )
    assert result["selected_ids"] == ["skill-0"] and math.isclose(
        state["cost"], 0.0000042
    )
    with core.db() as c:
        r = c.execute(
            "SELECT * FROM usage_operations WHERE owner=%s", (owner,)
        ).fetchone()
    assert (
        r["model"] == provider.JEV_MODEL
        and r["service"] == "skill_rerank"
        and r["charge_nano"] == 4200
    )
    assert json.loads(r["metadata"])["prompt_tokens"] == 100


@pytest.mark.parametrize(
    "choice,confidence,expected",
    [("none", 0.99, []), ("c1", 0.9, ["skill-1", "skill-0"]), ("c0", 0.3, [])],
)
def test_choice_none_and_uncertainty(choice, confidence, expected):
    assert (
        provider.parse_decision(response(choice, confidence), candidates())[
            "selected_ids"
        ]
        == expected
    )


@pytest.mark.parametrize("broken", ["foreign", "missing", "nan", "bool", "badtype"])
def test_invalid_decisions_never_apply_a_skill(broken):
    r = response()
    if broken == "foreign":
        r["answers"]["primary"]["choice"] = "unknown"
    elif broken == "missing":
        r["answers"].pop("include_c0")
    elif broken == "nan":
        r["answers"]["include_c0"]["noul"] = float("nan")
    elif broken == "bool":
        r["answers"]["primary"]["confidence"] = True
    else:
        r["answers"]["primary"]["type"] = "score"
    with pytest.raises(ValueError):
        provider.parse_decision(r, candidates())


def test_candidate_payload_is_bounded_and_omits_executable_instructions():
    items = candidates(8)
    for r in items:
        r.update(
            description="数" * 1000,
            when_to_use=["据" * 500] * 10,
            when_not_to_use=["除" * 500] * 10,
            instructions="SECRET SCRIPT",
        )
    body = provider.decision_payload("研" * 4000, items)
    raw = json.dumps(body, ensure_ascii=False)
    assert (
        len(raw.encode()) <= 28000
        and "SECRET SCRIPT" not in raw
        and len(body["state"]["candidates"]) == 8
    )


@pytest.mark.parametrize("status,pending", [(400, False), (503, True)])
def test_jev_failure_accounting(monkeypatch, status, pending):
    owner = user()

    async def request(*args):
        raise provider.providers.ProviderError("Failed", status)

    monkeypatch.setattr(provider.providers, "request", request)
    with pytest.raises(provider.providers.ProviderError):
        asyncio.run(provider.decide(owner, "Research", candidates()))
    assert (billing.activity(owner)["rows"][0]["status"] == "pending") == pending


def test_missing_cost_stays_pending_but_decision_is_valid(monkeypatch):
    owner = user()
    r = response()
    r["usage"].pop("cost")

    async def request(*args):
        return r

    monkeypatch.setattr(provider.providers, "request", request)
    assert asyncio.run(provider.decide(owner, "Research", candidates()))[
        "selected_ids"
    ] == ["skill-0"]
    assert billing.activity(owner)["rows"][0]["status"] == "pending"


def test_exact_match_and_old_disable_flag_cannot_skip_jev(embed, monkeypatch):
    owner = user()
    item = asyncio.run(skills.save(owner, package()))
    calls = []

    async def decide(*args):
        calls.append(args)
        return {"selected_ids": []}

    monkeypatch.setenv("ASTER_SKILL_RERANK", "0")
    monkeypatch.setattr(provider, "decide", decide)
    result = asyncio.run(skills.match(owner, "Use Research brief"))
    assert len(calls) == 1 and result["reranked"] and not result["pins"]


def test_weak_match_reaches_jev_and_provider_error_does_not_use_embedding_winner(
    embed, monkeypatch
):
    owner = user()
    asyncio.run(skills.save(owner, package()))
    calls = []

    async def weak(*args, **kwargs):
        return [[0.0, 1.0, 0.0]]

    async def offline(*args):
        calls.append(args)
        raise RuntimeError("Unavailable")

    monkeypatch.setattr(provider, "embed", weak)
    monkeypatch.setattr(provider, "decide", offline)
    result = asyncio.run(skills.match(owner, "Write a birthday greeting"))
    assert len(calls) == 1 and result["fallback"] and not result["pins"]


def test_resuming_same_task_does_not_rebill_matching(embed, monkeypatch):
    owner = user()
    asyncio.run(skills.save(owner, package()))
    calls = []

    async def decide(*args):
        calls.append(args)
        return {"selected_ids": []}

    monkeypatch.setattr(provider, "decide", decide)
    tid = core.create_task(owner, "Research a company", mode="work")
    row = core.owned(owner, tid)
    state = core.state(row)
    asyncio.run(skills.ensure(row, state))
    asyncio.run(skills.ensure(row, state))
    assert len(calls) == 1


def test_conflicting_jev_inclusion_rejects_primary():
    r = response()
    r["answers"]["include_c0"]["noul"] = 0.1
    assert provider.parse_decision(r, candidates())["reject_all"]
