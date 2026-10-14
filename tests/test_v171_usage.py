import pytest
from app import core, billing
from test_billing import account
from conftest import login


def test_breakdown_uses_display_categories_and_preserves_every_charge():
    owner, work = account()
    chat = core.create_task(owner, "Chat example", mode="chat")
    deleted = core.ident()
    entries = [
        (work, "model", {}, 0.01),
        (work, "model", {"mode": "chat"}, 0.02),
        (chat, "model", {"mode": "work"}, 0.03),
        (deleted, "model", {}, 0.04),
        (work, "search", {"mode": "work"}, 0.05),
        (chat, "search", {"mode": "chat"}, 0.06),
        (work, "browser", {}, 0.07),
        (deleted, "browser", {}, 0.08),
        (chat, "code", {}, 0.09),
        (work, "code", {}, 0.1),
    ]
    for task, service, metadata, cost in entries:
        rid = billing.reserve(owner, task, cost, service=service, metadata=metadata)
        billing.settle(rid, cost)
    result = billing.activity(owner)
    groups = {(r["service"], r["mode"]): r for r in result["breakdown"]}
    assert len(groups) == len(result["breakdown"]) == 5
    assert groups["model", "work"]["requests"] == 3
    assert groups["model", "work"]["charge"] == pytest.approx(0.08)
    assert groups["model", "chat"]["charge"] == pytest.approx(0.02)
    assert groups["search", "all"]["requests"] == 2
    assert groups["browser", "all"]["charge"] == pytest.approx(0.15)
    assert groups["code", "all"]["charge"] == pytest.approx(0.19)
    assert sum(r["requests"] for r in groups.values()) == len(entries)
    assert sum(r["charge"] for r in groups.values()) == pytest.approx(
        result["totals"]["charge"]
    )
    # Every card drills into exactly its constituent rows without losing existing mode filters.
    for mode in ("all", "chat", "work"):
        filtered = billing.activity(owner, mode=mode)
        for group in filtered["breakdown"]:
            detail = billing.activity(
                owner,
                service=group["service"],
                mode=group["mode"] if group["service"] == "model" else mode,
            )
            assert detail["total"] == group["requests"]
            assert detail["totals"]["charge"] == pytest.approx(group["charge"])


def test_empty_legacy_mode_falls_back_to_conversation_mode():
    owner, work = account()
    chat = core.create_task(owner, "Chat example", mode="chat")
    rid = billing.reserve(owner, chat, 0.01, metadata={"mode": ""})
    billing.settle(rid, 0.01)
    r = billing.activity(owner, mode="chat")
    assert r["total"] == 1 and r["rows"][0]["mode"] == "chat"
    assert r["breakdown"] == [
        {"service": "model", "mode": "chat", "charge": 0.01, "requests": 1}
    ]


def test_public_pricing_no_longer_explains_title_cost(client, monkeypatch):
    from app import providers

    login(client)

    async def catalog():
        return {}

    monkeypatch.setattr(providers, "catalog", catalog)
    assert "title" not in client.get("/api/pricing").json()["policy"].lower()
