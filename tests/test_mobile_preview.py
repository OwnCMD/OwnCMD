import asyncio
import pytest
from test_sandbox import sandbox
from conftest import login
from app import core, main


def test_new_task_retains_mobile_profile(client):
    h = login(client)
    profile = {"width": 390, "height": 844, "mobile": True}
    r = client.post(
        "/api/tasks",
        headers=h,
        json={
            "prompt": "Browse on my phone",
            "mode": "work",
            "browser_display": profile,
        },
    )
    assert r.status_code == 200
    with core.db() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=%s", (r.json()["id"],)).fetchone()
    assert core.state(row)["browser_display"] == profile
    assert (
        client.post(
            "/api/tasks",
            headers=h,
            json={"prompt": "Bad", "browser_display": {**profile, "mobile": "true"}},
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "validator", [main.validate_browser_display, sandbox.validate_browser_display]
)
def test_tall_viewports_are_bounded_without_clipping_to_old_height(validator):
    from fastapi import HTTPException

    assert validator({"width": 960, "height": 1800, "mobile": False})["height"] == 1800
    assert validator({"width": 960, "height": 4096})["height"] == 4096
    with pytest.raises(HTTPException):
        validator({"width": 960, "height": 4097})


@pytest.mark.parametrize(
    "path,body,op",
    [
        ("browser", {"kind": "resize"}, "action"),
        ("workspace", {"op": "preview", "kind": "resize"}, "dev-action"),
    ],
)
def test_passive_mobile_display_is_authenticated_and_preserves_control(
    client, monkeypatch, path, body, op
):
    h = login(client)
    with core.db() as c:
        owner = c.execute("SELECT id FROM users").fetchone()[0]
    tid = core.create_task(owner, "Phone")
    before = core.owned(owner, tid)
    calls = []

    async def broker(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(main, "broker", broker)
    args = {"width": 390, "height": 600, "mobile": True}
    body = {**body, "args": args}
    url = f"/api/tasks/{tid}/{path}"
    assert client.post(url, headers=h, json=body).status_code == 200
    assert calls == [(tid, op, {"kind": "resize", "args": args})]
    after = core.owned(owner, tid)
    assert all(
        before[k] == after[k]
        for k in ("status", "busy", "lease", "control", "control_epoch")
    )
    assert client.post(url, json=body).status_code == 403
    for bad in (
        {**args, "mobile": 1},
        {**args, "width": True},
        {**args, "events": []},
        {**args, "height": 9999},
    ):
        assert (
            client.post(url, headers=h, json={**body, "args": bad}).status_code == 400
        )


class Session:
    def __init__(self):
        self.calls = []

    async def send(self, m, a):
        self.calls.append((m, a))


class Page:
    def __init__(self, s):
        self.context = self
        self.session = s
        self.sizes = []

    async def new_cdp_session(self, p):
        return self.session

    async def set_viewport_size(self, size):
        self.sizes.append(size)


def test_mobile_desktop_transition_preserves_context_and_sets_matching_hints(
    monkeypatch,
):
    session = Session()
    p = Page(session)
    monkeypatch.setattr(sandbox, "device_sessions", {})
    monkeypatch.setattr(sandbox, "device_applied", {})
    monkeypatch.setattr(sandbox, "browser_version", "153.0.8010.12")
    monkeypatch.setattr(sandbox, "desktop_user_agent", "Mozilla Chrome/153.0.0.0")

    async def check():
        mobile = {"width": 390, "height": 650, "mobile": True}
        await sandbox.apply_display(p, mobile)
        n = len(session.calls)
        await sandbox.apply_display(p, mobile)
        assert len(session.calls) == n
        ua = session.calls[-1][1]
        assert "Mobile" in ua["userAgent"] and "Chrome/153.0.0.0" in ua["userAgent"]
        assert (
            ua["userAgentMetadata"]["mobile"]
            and ua["userAgentMetadata"]["platform"] == "Android"
        )
        await sandbox.apply_display(p, {"width": 1000, "height": 700, "mobile": False})
        assert session.calls[-1][1]["userAgentMetadata"]["mobile"] is False
        assert session.calls[-2][1]["enabled"] is False

    asyncio.run(check())


def test_scroll_targets_nested_panel_and_touch_taps_use_touch_events(monkeypatch):
    session = Session()
    p = Page(session)
    seen = []

    class Mouse:
        async def move(self, x, y):
            seen.append(("move", x, y))

        async def wheel(self, x, y):
            seen.append(("wheel", x, y))

    p.mouse = Mouse()
    monkeypatch.setattr(sandbox, "device_sessions", {p: session})
    monkeypatch.setattr(
        sandbox, "display_profile", {"width": 390, "height": 650, "mobile": True}
    )

    async def check():
        await sandbox.dev_input(
            p, "scroll", {"x": 0, "delta": 120, "atX": 80, "atY": 240}
        )
        await sandbox.dev_input(p, "pointer", {"x": 80, "y": 100, "touch": True})

    asyncio.run(check())
    assert seen == [("move", 80, 240), ("wheel", 0, 120)]
    assert [a["type"] for _, a in session.calls] == ["touchStart", "touchEnd"]
