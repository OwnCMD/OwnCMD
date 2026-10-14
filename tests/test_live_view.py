"""Regression: long browser actions must not starve or mislabel the live view."""

import asyncio, base64, time
import pytest
from test_sandbox import sandbox


class CDP:
    def __init__(self):
        self.calls = 0
        self.fail = False

    async def send(self, method, params):
        assert method == "Page.captureScreenshot"
        assert params["format"] == "jpeg"
        self.calls += 1
        if self.fail:
            raise RuntimeError("Navigation interrupted capture")
        return {
            "data": base64.b64encode(
                b"fresh-frame-" + str(self.calls).encode()
            ).decode()
        }

    async def detach(self):
        pass


class Context:
    def __init__(self, cdp):
        self.cdp = cdp

    async def new_cdp_session(self, p):
        return self.cdp


class Page:
    def __init__(self, cdp):
        self.context = Context(cdp)
        self.url = "https://example.com/new-page"


@pytest.fixture
def capture(monkeypatch):
    cdp = CDP()
    p = Page(cdp)
    for name, value in {
        "frame_cache": b"old-frame",
        "frame_seq": 10,
        "frame_ts": time.monotonic() - 10,
        "frame_page": None,
        "frame_cdp": None,
        "frame_url": "https://old.example",
        "frame_lock": asyncio.Lock(),
        "lock": asyncio.Lock(),
    }.items():
        monkeypatch.setattr(sandbox, name, value)
    return cdp, p


def test_live_frame_updates_while_navigation_holds_action_lock(capture):
    cdp, p = capture

    async def check():
        async with sandbox.lock:
            await asyncio.wait_for(sandbox.refresh_frame(p), 1)

    asyncio.run(check())
    assert sandbox.frame_cache == b"fresh-frame-1"
    assert sandbox.frame_seq == 11
    assert int(sandbox.frame_headers()["X-Aster-Frame-Age"]) < 1000
    assert "new-page" in sandbox.frame_headers()["X-Aster-Frame-URL"]


def test_parallel_viewers_share_capture_and_action_can_force_refresh(capture):
    cdp, p = capture

    async def check():
        await asyncio.gather(*[sandbox.refresh_frame(p) for _ in range(8)])
        assert cdp.calls == 1
        await sandbox.refresh_frame(p, True)

    asyncio.run(check())
    assert cdp.calls == 2


def test_capture_failure_retains_pixels_but_reports_staleness(capture):
    cdp, p = capture
    cdp.fail = True
    asyncio.run(sandbox.refresh_frame(p))
    assert sandbox.frame_cache == b"old-frame"
    assert sandbox.frame_seq == 10
    assert int(sandbox.frame_headers()["X-Aster-Frame-Age"]) >= 10000


def test_new_page_cannot_be_hidden_behind_recent_cached_frame(capture):
    cdp, p = capture

    async def check():
        await sandbox.refresh_frame(p)
        other = Page(cdp)
        other.url = "https://example.com/popup"
        await sandbox.refresh_frame(other)

    asyncio.run(check())
    assert cdp.calls == 2
    assert sandbox.frame_url.endswith("/popup")
