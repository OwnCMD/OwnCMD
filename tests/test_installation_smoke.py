"""Public smoke probes must verify browser networking without a single fragile website."""

import asyncio, json
import pytest
from app import core, operations


@pytest.mark.parametrize(
    "mode,origin",
    [
        (None, "https://aster.example.org"),
        ("letsencrypt", "https://aster.example.org"),
        ("internal", "https://aster.example.org"),
        (None, "https://203.0.113.12"),
    ],
)
def test_probe_targets_respect_sandbox_host_isolation(monkeypatch, mode, origin):
    monkeypatch.setattr(core, "ORIGIN", origin)
    if mode:
        monkeypatch.setenv("ASTER_TLS_MODE", mode)
    else:
        monkeypatch.delenv("ASTER_TLS_MODE", raising=False)
    targets = operations.browser_probe_targets()
    assert (origin + "/health", "health") not in targets
    assert len(targets) == 2
    assert targets[0] == ("https://registry.npmjs.org/express/latest", "npm")
    assert all(
        url.startswith("https://") and "example.com" not in url for url, _ in targets
    )


@pytest.mark.parametrize(
    "status,text,valid",
    [
        (200, '{"ok":true}', True),
        (200, 'Pretty-print\n{ "ok": true }', True),
        (503, '{"ok":true}', False),
        (200, '{"ok":false}', False),
        (200, "Verify you are human", False),
        (None, '{"ok":true}', False),
    ],
)
def test_navigation_requires_status_url_and_page_content(status, text, valid):
    url = "https://aster.example.org/health"
    result = {"url": url, "http_status": status, "text": text}
    assert operations.browser_probe_valid(url, "health", result) == valid
    assert not operations.browser_probe_valid(
        url, "health", {**result, "url": "https://challenge.invalid/health"}
    )


@pytest.mark.parametrize("first_error", [False, True])
def test_probe_fallback_is_bounded_and_visible(monkeypatch, capsys, first_error):
    targets = [
        ("https://aster.example.org/health", "health"),
        ("https://registry.npmjs.org/express", "npm"),
    ]
    calls = []
    monkeypatch.setattr(operations, "browser_probe_targets", lambda: targets)

    async def broker(task, op, body):
        assert body["args"]["fresh_page"] is True
        calls.append(body["args"]["url"])
        if len(calls) == 1:
            if first_error:
                raise RuntimeError("TLS connection failed")
            return {
                "http_status": 403,
                "url": targets[0][0],
                "title": "Access denied",
                "text": "Blocked",
            }
        return {
            "http_status": 200,
            "url": targets[1][0],
            "text": '{"name":"express","versions":{',
        }

    monkeypatch.setattr(operations, "broker", broker)
    assert asyncio.run(operations.public_browser_smoke("task")) == targets[1][0]
    assert calls == [x[0] for x in targets]
    assert "probe fallback" in capsys.readouterr().out


def test_all_failed_probes_are_fatal_with_diagnostics(monkeypatch):
    targets = [
        ("https://aster.example.org/health", "health"),
        ("https://pypi.org/simple/pip/", "pypi"),
    ]
    calls = []
    monkeypatch.setattr(operations, "browser_probe_targets", lambda: targets)

    async def broker(task, op, body):
        calls.append(body["args"]["url"])
        return {
            "http_status": 503,
            "url": calls[-1],
            "title": "Unavailable",
            "text": "Try later",
        }

    monkeypatch.setattr(operations, "broker", broker)
    with pytest.raises(
        RuntimeError, match="Public browser navigation failed for every probe"
    ) as error:
        asyncio.run(operations.public_browser_smoke("task"))
    assert (
        len(calls) == 2
        and "HTTP 503" in str(error.value)
        and "Unavailable" in str(error.value)
    )


def test_pypi_fallback_needs_content_not_just_success_status():
    url = "https://pypi.org/simple/pip/"
    result = {
        "url": url,
        "http_status": 200,
        "title": "Links for pip",
        "text": "pip-25.0.tar.gz",
    }
    assert operations.browser_probe_valid(url, "pypi", result)
    assert not operations.browser_probe_valid(
        url, "pypi", {**result, "text": "Challenge"}
    )


@pytest.mark.parametrize("fail", [False, True])
def test_smoke_cleans_up_and_reports_completed_checks(monkeypatch, capsys, fail):
    calls = []

    class Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args):
            return self

        def raise_for_status(self):
            pass

    monkeypatch.setattr(operations.httpx, "AsyncClient", Client)

    async def broker(task, op, body=None):
        calls.append(op)
        if op == "run":
            return {
                "exit_code": 0,
                "output": "SMOKE_OK EGRESS_BLOCKED REGISTRY_OK UNLISTED_BLOCKED",
            }
        if op == "file":
            return {"content": "OwnCMD smoke test"}
        if op == "snapshot":
            return {"data": "snapshot"}
        if op == "action":
            return {"elements": []}
        if op == "frame":
            return {"image": "x" * 150}
        return {}

    async def public(task):
        if fail:
            raise RuntimeError("Public probe failed")
        return "https://aster.example.org/health"

    monkeypatch.setattr(operations, "broker", broker)
    monkeypatch.setattr(operations, "public_browser_smoke", public)
    if fail:
        with pytest.raises(RuntimeError, match="Public probe failed"):
            asyncio.run(operations.smoke())
    else:
        asyncio.run(operations.smoke())
    assert calls[-1] == "stop"
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    output = capsys.readouterr().out
    assert "PASS: Chromium startup and DOM observation" in output
    assert ("Smoke checks passed." in output) == (not fail)
