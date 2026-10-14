import asyncio, json, time
import pytest
from app import core, worker, main
from test_worker import owner
from test_sandbox import sandbox, sc
from test_workspace_upgrade import Page


@pytest.mark.parametrize(
    "text",
    [
        "Please provide your shipping address and phone number.",
        "What is your email address?",
        "Could you enter the verification code?",
        "I need your size preference before continuing.",
        "Let me know which delivery option to select.",
        "What's your preferred size?",
        "Enter the one-time code.",
        "Do you have a preferred delivery date?",
    ],
)
def test_prose_input_requests_become_forms_without_release(monkeypatch, text):
    uid = owner()
    tid = core.create_task(uid, "Buy the selected item")
    row = core.acquire()
    s = core.state(row)
    s["browser_used"] = True
    core.save(row, s)

    async def model(*a):
        return {"role": "assistant", "content": text}

    calls = []

    async def broker(*a):
        calls.append(a)
        return {}

    monkeypatch.setattr(worker, "model_call", model)
    monkeypatch.setattr(worker, "broker", broker)
    asyncio.run(worker.step(core.acquire()))
    asyncio.run(worker.step(core.acquire()))
    row = core.owned(uid, tid)
    s = core.state(row)
    assert (
        row["status"] == "approval" and s["pending"]["approval"]["name"] == "ask_user"
    )
    assert s["pending"]["approval"]["arguments"]["question"] == text
    assert not calls and not s["result"]
    assert main.detail_payload(row, s, [])["approval"]


def test_final_answer_does_not_turn_into_question():
    assert (
        worker.input_request(
            {"content": "Your order was placed. Confirmation number ABC."},
            {"browser_used": True},
        )
        is None
    )
    assert (
        worker.input_request(
            {
                "content": "Your order was placed. Let me know if you need anything else."
            },
            {"browser_used": True},
        )
        is None
    )
    assert (
        worker.input_request(
            {"content": "What is your email?"}, {"browser_used": False}
        )
        is None
    )


def pending(uid, tid, args):
    s = core.state(core.owned(uid, tid))
    s["browser_used"] = True
    s["restored"] = True
    s["pending"] = {
        "calls": [
            {"id": "buy", "function": {"name": "browse", "arguments": json.dumps(args)}}
        ],
        "index": 0,
        "control_epoch": 0,
    }
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET state=%s WHERE id=%s", (core.enc(json.dumps(s)), tid)
        )


def test_final_purchase_uses_same_single_approval(monkeypatch):
    uid = owner()
    tid = core.create_task(uid, "Buy selected item")
    pending(
        uid,
        tid,
        {
            "action": "click",
            "ref": 5,
            "confirm": True,
            "confirmation_reason": "Place the final order",
        },
    )
    calls = []
    executed = []

    async def broker(task, op, body=None):
        calls.append(body)
        return {
            "approval_required": True,
            "approval_token": "one-use",
            "confirmation_reason": "Pay CAD 25.00",
        }

    async def execute(row, s, name, args):
        assert (
            s["pending"]["approved"] == "buy"
            and s["pending"]["payment_challenge"] == "one-use"
        )
        executed.append(args)
        return {"ok": True}

    monkeypatch.setattr(worker, "broker", broker)
    monkeypatch.setattr(worker, "execute", execute)
    asyncio.run(worker.step(core.acquire()))
    row = core.owned(uid, tid)
    s = core.state(row)
    assert row["status"] == "approval" and len(calls) == 1 and calls[0]["check_only"]
    s["pending"]["approved"] = "buy"
    core.save(row, s)
    asyncio.run(worker.step(core.acquire()))
    row = core.owned(uid, tid)
    assert len(executed) == 1 and len(calls) == 1 and row["status"] == "queued"
    with core.db() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM events WHERE task=%s AND kind='approval'", (tid,)
            ).fetchone()[0]
            == 1
        )


def test_routine_checkout_does_not_request_approval(monkeypatch):
    uid = owner()
    tid = core.create_task(uid, "Buy a product")
    pending(
        uid,
        tid,
        {
            "action": "click",
            "ref": 2,
            "confirm": True,
            "confirmation_reason": "Go to checkout",
        },
    )

    async def broker(*a):
        return {"approval_required": False, "routine": True}

    executed = []

    async def execute(row, s, name, args):
        executed.append(args)
        return {"ok": True}

    monkeypatch.setattr(worker, "broker", broker)
    monkeypatch.setattr(worker, "execute", execute)
    asyncio.run(worker.step(core.acquire()))
    assert len(executed) == 1 and not executed[0]["confirm"]
    assert core.owned(uid, tid)["status"] == "queued"


def test_typing_does_not_ask_for_payment():
    async def run():
        p = Page()
        assert await sandbox.payment_guard(p, "text", {"text": "a"}) is None
        assert await sandbox.payment_guard(p, "key", {"key": "Tab"}) is None
        assert (await sandbox.payment_guard(p, "key", {"key": "Enter"}))[
            "approval_required"
        ]

    asyncio.run(run())


def test_preflight_issues_token_without_executing_click(sc, monkeypatch):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")

    class Fake(Page):
        def locator(self, *a):
            raise AssertionError("Final click must not execute during preflight")

    async def get():
        return Fake()

    monkeypatch.setattr(sandbox, "getpage", get)
    r = sc.post(
        "/action", json={"kind": "click", "args": {"ref": 5}, "check_only": True}
    )
    assert r.status_code == 200 and r.json()["approval_required"]
    token = r.json()["approval_token"]
    assert (
        asyncio.run(sandbox.payment_guard(Fake(), "click", {"ref": 5}, token)) is None
    )
