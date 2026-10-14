"""Regression coverage for passive browser sizing and complete confirmation forms."""

import asyncio, json, time
import pytest
from app import core, profile, main, worker, scheduling
from conftest import login
from test_billing import account
from test_sandbox import sandbox, sc

YAHOO = {
    "question": "Yahoo requires these details to create the account: first name, last name, desired Yahoo address (the part before @yahoo.com), a password, and date of birth (MM/DD/YYYY). Please provide them. Yahoo may also request a mobile number and verification code on the next step.",
    "input_type": "text",
}


def pending(owner, tid, args=YAHOO):
    s = core.state(core.owned(owner, tid))
    s["pending"] = {
        "calls": [
            {
                "id": "review-1",
                "function": {"name": "ask_user", "arguments": json.dumps(args)},
            }
        ],
        "index": 0,
        "approval": {"name": "ask_user", "arguments": args},
    }
    with core.db() as c:
        c.execute(
            "UPDATE tasks SET state=%s,status='approval' WHERE id=%s",
            (core.enc(json.dumps(s)), tid),
        )
    return s


def fields(owner, args=YAHOO):
    return {
        f["key"]: f
        for f in profile.prefill(owner, {"name": "ask_user", "arguments": args})[
            "fields"
        ]
    }


def test_exact_reported_signup_has_all_fields_and_partial_prefill():
    owner, _ = account()
    profile.save(
        owner,
        {
            "version": 0,
            "fields": {
                "full_name": "Morgan Sample",
                "email": "existing@example.test",
                "phone": "5551234567",
            },
        },
    )
    f = fields(owner)
    assert list(f) == [
        "first_name",
        "last_name",
        "username",
        "password",
        "date_of_birth",
    ]
    assert f["first_name"]["value"] == "Morgan" and f["last_name"]["value"] == "Sample"
    assert all(f[k]["value"] == "" for k in ("username", "password", "date_of_birth"))
    assert f["password"]["type"] == "secret" and f["password"]["sensitive"]
    assert f["username"]["type"] == "text" and profile.sensitive_answer(YAHOO)


@pytest.mark.parametrize("disabled", [False, True])
def test_missing_and_disabled_profile_still_render_complete_blank_form(disabled):
    owner, _ = account()
    if disabled:
        profile.save(
            owner,
            {"version": 0, "enabled": False, "fields": {"full_name": "Never Disclose"}},
        )
    f = fields(owner)
    assert len(f) == 5 and not any(x["value"] for x in f.values())


def test_profile_names_are_scoped_and_ambiguous_single_name_is_not_split():
    owner, _ = account()
    profile.save(owner, {"version": 0, "fields": {"full_name": "Cher"}})
    assert fields(owner)["first_name"]["value"] == ""
    assert (
        fields(owner, {"question": "What is their first name and last name?"})[
            "last_name"
        ]["value"]
        == ""
    )


def test_structured_fields_ignore_fabricated_values_and_do_not_map_secrets():
    owner, _ = account()
    profile.save(
        owner,
        {
            "version": 0,
            "fields": {"email": "saved@example.test"},
            "custom": [
                {"id": "birth", "label": "Date of birth", "value": "1991-08-09"}
            ],
        },
    )
    args = {
        "question": "Review these fields",
        "fields": [
            {
                "key": "recovery",
                "label": "Recovery email",
                "type": "email",
                "profile_key": "email",
                "value": "invented",
            },
            {
                "key": "password",
                "label": "Password",
                "type": "text",
                "profile_key": "email",
            },
            {
                "key": "dob",
                "label": "Date of birth",
                "type": "date",
                "profile_key": "custom_birth",
            },
            {
                "key": "note",
                "label": "Note",
                "type": "text",
                "profile_key": "",
                "required": False,
            },
        ],
    }
    f = fields(owner, args)
    assert f["recovery"]["value"] == "saved@example.test"
    assert f["password"]["value"] == "" and f["password"]["type"] == "secret"
    assert f["dob"]["value"] == "1991-08-09" and not f["note"]["required"]
    assert profile.sensitive_answer(args)


def test_scheduled_partial_inputs_cannot_skip_missing_fields_or_secret_confirmation():
    state = {
        "schedule_inputs": {"first_name": {"label": "First name", "value": "Morgan"}}
    }
    args = {
        "question": "Review all details",
        "profile_fields": ["first_name"],
        "fields": [
            {"key": "first", "label": "First name", "profile_key": "first_name"},
            {"key": "username", "label": "Username", "profile_key": ""},
        ],
    }
    assert scheduling.confirmed_answer(state, args) == ""
    args["fields"][1] = {
        "key": "password",
        "label": "Password",
        "type": "secret",
        "profile_key": "first_name",
    }
    assert scheduling.confirmed_answer(state, args) == ""


def test_confirmed_signup_stays_private_and_reaches_worker_once(client):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Create an account")
    profile.save(owner, {"version": 0, "fields": {"full_name": "Morgan Sample"}})
    pending(owner, tid)
    payload = client.get("/api/tasks/" + tid).json()
    assert payload["approval"]["id"] == "review-1"
    assert "Morgan" not in json.dumps(core.state(core.owned(owner, tid)))
    answers = {
        "first_name": "Edited",
        "last_name": "Sample",
        "username": "test.person",
        "password": "  NeverLogThisSecret!  ",
        "date_of_birth": "1991-08-09",
    }
    body = {"action": "answer", "approval_id": "review-1", "field_values": answers}
    assert (
        client.post(
            f"/api/tasks/{tid}/command", headers=h, json={**body, "approval_id": "old"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/tasks/{tid}/command",
            headers=h,
            json={**body, "field_values": {**answers, "password": ""}},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/tasks/{tid}/command",
            headers=h,
            json={**body, "field_values": {**answers, "extra": "x"}},
        ).status_code
        == 400
    )
    assert client.post(f"/api/tasks/{tid}/command", json=body).status_code == 403
    assert (
        client.post(f"/api/tasks/{tid}/command", headers=h, json=body).status_code
        == 200
    )
    assert (
        client.post(f"/api/tasks/{tid}/command", headers=h, json=body).status_code
        == 409
    )
    assert profile.get(owner)["fields"]["full_name"] == "Morgan Sample"
    detail = client.get("/api/tasks/" + tid).json()
    assert "NeverLogThisSecret" not in json.dumps(detail)
    with core.db() as c:
        assert (
            "NeverLogThisSecret"
            not in c.execute("SELECT state FROM tasks WHERE id=%s", (tid,)).fetchone()[
                0
            ]
        )
    asyncio.run(worker.step(core.acquire()))
    s = core.state(core.owned(owner, tid))
    result = json.loads(
        next(m["content"] for m in s["messages"] if m.get("tool_call_id") == "review-1")
    )
    assert (
        "Password:   NeverLogThisSecret!  " in result["answer"]
        and "First name: Edited" in result["answer"]
    )
    assert not s.get("pending")


@pytest.mark.parametrize("kind", ["text", "secret", "otp"])
def test_legacy_answer_with_sensitive_question_is_redacted(client, kind):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Legacy approval")
    pending(owner, tid, {"question": "Email and password", "input_type": kind})
    assert (
        client.post(
            f"/api/tasks/{tid}/command",
            headers=h,
            json={"action": "answer", "text": "private-secret-987"},
        ).status_code
        == 200
    )
    assert "private-secret-987" not in json.dumps(
        client.get("/api/tasks/" + tid).json()
    )


def test_passive_resize_preserves_ai_control_and_human_input_guard(client, monkeypatch):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Browse")
    calls = []

    async def broker(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(main, "broker", broker)
    resize = {"kind": "resize", "args": {"width": 700, "height": 950}}
    before = core.owned(owner, tid)
    assert (
        client.post(f"/api/tasks/{tid}/browser", headers=h, json=resize).status_code
        == 200
    )
    after = core.owned(owner, tid)
    assert all(
        after[k] == before[k]
        for k in ("control", "control_epoch", "busy", "status", "lease")
    )
    assert calls == [(tid, "action", resize)]
    assert (
        client.post(
            f"/api/tasks/{tid}/browser",
            headers=h,
            json={
                "kind": "input",
                "args": {"events": [{"kind": "text", "args": {"text": "bad"}}]},
            },
        ).status_code
        == 400
    )
    assert client.post(f"/api/tasks/{tid}/browser", json=resize).status_code == 403
    for a in (
        {"width": 0, "height": 800},
        {"width": True, "height": 800},
        {"width": 700, "height": 950, "events": []},
        {"width": "700", "height": 950},
    ):
        assert (
            client.post(
                f"/api/tasks/{tid}/browser",
                headers=h,
                json={"kind": "resize", "args": a},
            ).status_code
            == 400
        )
    client.post("/api/logout", headers=h, json={})
    h2 = login(client, "other@example.test")
    assert (
        client.post(f"/api/tasks/{tid}/browser", headers=h2, json=resize).status_code
        == 404
    )
    assert len(calls) == 1


def test_sandbox_resize_uses_action_lock_without_waiting_for_capture(sc, monkeypatch):
    monkeypatch.setenv("ASTER_SANDBOX_KIND", "browser")
    seen = []

    class Page:
        url = "https://fixture.test"

        async def set_viewport_size(self, size):
            assert sandbox.lock.locked()
            seen.append(size)

    async def get():
        return Page()

    async def frame(p, force=False):
        seen.append(force)

    async def display(p, profile):
        await p.set_viewport_size({k: profile[k] for k in ("width", "height")})

    monkeypatch.setattr(sandbox, "apply_display", display)
    monkeypatch.setattr(sandbox, "getpage", get)
    monkeypatch.setattr(sandbox, "refresh_frame", frame)
    r = sc.post(
        "/action", json={"kind": "resize", "args": {"width": 390, "height": 650}}
    )
    assert r.status_code == 200 and seen == [{"width": 390, "height": 650}]
    assert (
        sc.post(
            "/action",
            json={
                "kind": "resize",
                "args": {"width": 390, "height": 650, "text": "no"},
            },
        ).status_code
        == 400
    )
