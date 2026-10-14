import asyncio, sys, os, time, json, pathlib, tarfile, tempfile, getpass, subprocess, secrets
import httpx
from . import core
from .tools import broker
from .providers import catalog, request, ProviderError
from .integrations import credential


def browser_probe_targets():
    """Probe independent public sites; sandbox-to-host access is denied by design.
    The installer's separate HTTPS readiness check verifies the application's site.
    """
    return [
        ("https://registry.npmjs.org/express/latest", "npm"),
        ("https://pypi.org/simple/pip/", "pypi"),
    ]


def browser_probe_valid(url, kind, result):
    from urllib.parse import urlsplit
    import re

    expected = urlsplit(url)
    actual = urlsplit(str(result.get("url", "")))
    status = result.get("http_status")
    if type(status) != int or not 200 <= status < 300:
        return False
    if (actual.scheme, actual.netloc, actual.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ):
        return False
    text = str(result.get("text", ""))
    if kind == "health":
        try:
            return (
                json.loads(text[text.index("{") : text.rindex("}") + 1]).get("ok")
                is True
            )
        except (ValueError, AttributeError):
            return False
    if kind == "npm":
        return bool(re.search(r'"name"\s*:\s*"express"', text))
    return (
        kind == "pypi"
        and "Links for pip" in str(result.get("title", ""))
        and "pip-" in text
    )


async def public_browser_smoke(task):
    failures = []
    for url, kind in browser_probe_targets():
        print("Checking public browser HTTPS: " + url, flush=True)
        try:
            # A failed goto can leave Chromium committing an error page. Replacing only
            # this probe's tab cancels that navigation without restarting the context.
            result = await broker(
                task,
                "action",
                {"kind": "navigate", "args": {"url": url, "fresh_page": True}},
            )
            if browser_probe_valid(url, kind, result):
                return url
            failures.append(
                f"{url}: HTTP {result.get('http_status','unknown')}; returned URL {str(result.get('url',''))[:180]}; title {str(result.get('title',''))[:120]!r}; expected page content was absent"
            )
        except Exception as error:
            failures.append(f"{url}: {type(error).__name__}: {str(error)[:350]}")
        print("NOTE: browser probe fallback: " + failures[-1], flush=True)
    raise RuntimeError(
        "Public browser navigation failed for every probe. Chromium started, but public HTTPS/DOM access was not verified. Check browser egress, DNS/TLS and provider logs. "
        + " | ".join(failures)
    )


async def live_probe_request(label, url, body, key, exa=False):
    try:
        return await request(url, body, key, exa, diagnostics=True)
    except ProviderError as error:
        detail = error.diagnostic or str(error)
        raise RuntimeError(
            f'{label} failed (HTTP {error.status or "unavailable"}): {detail}. Check the configured model, provider access and account settings; the live check has not passed.'
        ) from None


async def live_model_smoke(model, metadata):
    """Use production-compatible parameters, then verify a complete tool call."""
    if not metadata or "tools" not in metadata.get("supported_parameters", []):
        raise RuntimeError("Configured model absent or lacks tools: " + model)
    from .work_output import output_limit

    cap = output_limit({}, model, metadata, 4096)
    tool = {
        "type": "function",
        "function": {
            "name": "smoke_check",
            "description": "Return smoke test status",
            "parameters": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["ready"]}},
                "required": ["status"],
                "additionalProperties": False,
            },
        },
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Call smoke_check once with status ready. Do not answer with plain text.",
            }
        ],
        "tools": [tool],
        "max_completion_tokens": cap,
        "provider": {"allow_fallbacks": True, "require_parameters": True},
    }
    # Production Work mode does not force tool_choice. Checking a real tool call
    # below verifies tool support without adding a provider-specific constraint.
    print(
        f"Checking LIVE OpenRouter tool calling: {model} (output limit {cap})",
        flush=True,
    )
    result = await live_probe_request(
        "OpenRouter model " + model,
        "https://openrouter.ai/api/v1/chat/completions",
        body,
        credential("OPENROUTER_API_KEY"),
    )
    try:
        choice = result["choices"][0]
        if choice.get("finish_reason") not in ("tool_calls", "stop"):
            raise ValueError()
        calls = choice["message"]["tool_calls"]
        if not isinstance(calls, list) or len(calls) != 1:
            raise ValueError()
        call = calls[0]
        fn = call["function"]
        args = fn["arguments"]
        if isinstance(args, str):
            args = json.loads(args)
        if (
            call.get("type") != "function"
            or fn["name"] != "smoke_check"
            or args != {"status": "ready"}
        ):
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise RuntimeError(
            f"OpenRouter model {model} did not return a complete smoke_check(status=ready) tool call within {cap} output tokens. The live check has not passed."
        ) from None


def prepare_smoke_account():
    # Installation probes have an explicit service-account policy, so disabling a
    # product feature globally cannot make a healthy installation fail readiness.
    from . import billing, accounts

    owner = "aster-installation-checks"
    with core.db() as c:
        c.begin_write()
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                owner,
                "installation-checks@aster.invalid",
                core.PH.hash(secrets.token_urlsafe(48)),
                time.time(),
            ),
        )
        c.commit()
    previous = accounts.account(owner)
    accounts.save_account(
        "operator",
        owner,
        {
            "role": "user",
            "disabled": False,
            "overrides": {
                "features": {"chat": True, "work": True, "browser": True, "code": True}
            },
            "version": previous["version"],
        },
    )
    return owner


async def smoke(live=False):
    checks = []

    def passed(message):
        checks.append(message)
        print("PASS:", message, flush=True)

    async with httpx.AsyncClient(timeout=5) as c:
        for _ in range(30):
            try:
                r = await c.get("http://127.0.0.1:8000/health")
                r.raise_for_status()
                break
            except httpx.HTTPError:
                await asyncio.sleep(1)
        else:
            raise RuntimeError("Web service failed readiness check")
    passed("web service and database readiness")
    owner = prepare_smoke_account()
    task = core.create_task(owner, "Installation smoke checks", mode="chat")
    try:
        r = await broker(
            task, "run", {"command": "python -c 'assert 2+2==4; print(\"SMOKE_OK\")'"}
        )
        assert r["exit_code"] == 0 and "SMOKE_OK" in r["output"]
        passed("gVisor code execution")
        await broker(
            task,
            "file",
            {
                "op": "write",
                "path": "index.html",
                "content": "<!doctype html><title>Smoke</title><h1>OwnCMD smoke test</h1>",
            },
        )
        r = await broker(task, "file", {"op": "read", "path": "index.html"})
        assert "OwnCMD smoke test" in r["content"]
        passed("workspace write/read")
        snap = await broker(task, "snapshot")
        assert snap.get("data")
        passed("workspace snapshot")
        r = await broker(
            task,
            "run",
            {
                "command": "python - <<'CODE'\nimport socket\nfor host in ['172.30.0.1','172.31.0.1','169.254.169.254','1.1.1.1']:\n s=socket.socket();s.settimeout(2)\n try:s.connect((host,80));raise AssertionError('Unexpected egress: '+host)\n except (TimeoutError,OSError):pass\n finally:s.close()\nprint('EGRESS_BLOCKED')\nCODE"
            },
        )
        assert r["exit_code"] == 0 and "EGRESS_BLOCKED" in r["output"]
        passed("code network isolation (host, metadata, direct public egress)")
        r = await broker(
            task,
            "run",
            {
                "command": "python -c \"import urllib.request; r=urllib.request.urlopen('https://registry.npmjs.org/express',timeout=20); assert r.status==200; print('REGISTRY_OK')\""
            },
        )
        assert r["exit_code"] == 0 and "REGISTRY_OK" in r["output"]
        passed("allowlisted HTTPS package downloads")
        r = await broker(
            task,
            "run",
            {
                "command": "python - <<'CODE'\nimport urllib.request,urllib.error\ntry:urllib.request.urlopen('https://example.com/',timeout=10);raise AssertionError('Unlisted destination allowed')\nexcept urllib.error.URLError as e:assert '403' in str(e),str(e)\nprint('UNLISTED_BLOCKED')\nCODE"
            },
        )
        assert r["exit_code"] == 0 and "UNLISTED_BLOCKED" in r["output"]
        passed("unlisted HTTPS destination blocked by package proxy")
        r = await broker(task, "action", {"kind": "observe", "args": {}})
        assert "elements" in r
        passed("Chromium startup and DOM observation")
        frame = await broker(task, "frame")
        assert len(frame["image"]) > 100
        passed("live browser screenshot")
        # At least one real public HTTPS page must pass; never rely on example.com.
        target = await public_browser_smoke(task)
        passed("public HTTPS browser navigation and DOM content: " + target)
        frame = await broker(task, "frame")
        assert len(frame["image"]) > 100
        passed("rendered public-page screenshot")
        if live:
            from . import accounts

            if not credential("OPENROUTER_API_KEY") or not credential("EXA_API_KEY"):
                raise RuntimeError(
                    "Live checks require OpenRouter and Exa keys. Add them in Instance settings > Providers first."
                )
            models = await catalog()
            configured = [
                accounts.resolve_model(owner, mode) for mode in ("chat", "work")
            ]
            for model in dict.fromkeys(configured):
                await live_model_smoke(model, models.get(model))
                passed("LIVE OpenRouter tool calling: " + model)
            r = await live_probe_request(
                "Exa search",
                "https://api.exa.ai/search",
                {"query": "OpenRouter documentation", "numResults": 1},
                credential("EXA_API_KEY"),
                True,
            )
            assert r.get("results")
            passed("LIVE Exa search")
    finally:
        await broker(task, "stop")
        with core.db() as c:
            c.execute("DELETE FROM events WHERE task=%s", (task,))
            c.execute("DELETE FROM tasks WHERE id=%s", (task,))
            c.execute("DELETE FROM users WHERE id=%s", (owner,))
    print(
        "Smoke checks passed. This is not a load test or proof of full feature parity."
    )


def backup():
    directory = core.DATA / "backups"
    directory.mkdir(mode=0o700, exist_ok=True)
    name = directory / (
        "aster-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".tar.gz"
    )
    with tempfile.TemporaryDirectory() as tmp:
        from .database import dump_database

        dest = pathlib.Path(tmp) / "postgres.dump"
        dump_database(dest)
        with tarfile.open(name, "w:gz") as archive:
            archive.add(dest, arcname="postgres.dump")
            if (core.DATA / "snapshots").exists():
                archive.add(core.DATA / "snapshots", arcname="snapshots")
            if (core.DATA / "uploads").exists():
                archive.add(core.DATA / "uploads", arcname="uploads")
    os.chmod(name, 0o600)
    print(name)
    print(
        "Encryption key is not inside this archive. Back up /etc/aster/config.env separately and off-server."
    )


def reset(email):
    password = getpass.getpass("New password (12–128 characters): ")
    confirm = getpass.getpass("Confirm: ")
    if password != confirm or not 12 <= len(password) <= 128:
        raise SystemExit("Invalid password or mismatch")
    with core.db() as c:
        c.begin_write()
        u = c.execute(
            "SELECT id FROM users WHERE email=%s", (email.lower(),)
        ).fetchone()
        if not u:
            raise SystemExit("Account not found")
        c.execute(
            "UPDATE users SET password=%s WHERE id=%s",
            (core.PH.hash(password), u["id"]),
        )
        c.execute("DELETE FROM sessions WHERE owner=%s", (u["id"],))
        c.commit()
    print("Password updated and all sessions revoked.")


async def main():
    command = sys.argv[1]
    if command == "smoke":
        await smoke("--live" in sys.argv)
    elif command == "models":
        models = await catalog()
        configured = [
            ("chat", os.getenv("ASTER_CHAT_MODEL", "google/gemini-3.5-flash-lite")),
            ("work", os.getenv("ASTER_WORK_MODEL", "openai/gpt-5.6-luna")),
        ]
        for mode, id in configured:
            m = models.get(id)
            print(
                mode,
                id,
                json.dumps((m or {}).get("pricing", {})),
                "tools="
                + str(bool(m and "tools" in m.get("supported_parameters", []))),
            )
    elif command == "billing-pending":
        with core.db() as c:
            for r in c.execute(
                "SELECT id,owner,service,provider_id,status,created FROM usage_operations WHERE status IN ('reserved','pending') OR coalesce(metadata::jsonb->>'provisional','false') IN ('true','1') ORDER BY created"
            ):
                print(json.dumps(dict(r)))
    elif command == "reconcile-usage":
        from .billing import reconcile_operation

        if len(sys.argv) != 5:
            raise SystemExit(
                "Usage: asterctl reconcile-usage OPERATION_ID VERIFIED_COST_USD EVIDENCE_REFERENCE"
            )
        reconcile_operation(sys.argv[2], sys.argv[3], sys.argv[4])
        print("Provider usage reconciled.")
    elif command == "grant-admin":
        from .accounts import bootstrap

        bootstrap(sys.argv[2])
        print("Administrator access granted.")
    elif command == "create-admin":
        from . import integrations, accounts

        if len(sys.argv) != 3:
            raise SystemExit("Usage: asterctl create-admin EMAIL")
        email = integrations.email_address(sys.argv[2])
        password = getpass.getpass("Administrator password (12–128 characters): ")
        if not 12 <= len(password) <= 128 or password != getpass.getpass(
            "Confirm password: "
        ):
            raise SystemExit("Invalid password or mismatch")
        with core.db() as c:
            c.begin_write()
            if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
                raise SystemExit("Account already exists. Use grant-admin instead.")
            c.execute(
                "INSERT INTO users VALUES(%s,%s,%s,%s)",
                (core.ident(), email, core.PH.hash(password), time.time()),
            )
            c.commit()
        accounts.bootstrap(email)
        print(
            "Owner created. Sign in and configure provider keys in Instance settings."
        )
    elif command == "backup":
        backup()
    elif command == "reset-password":
        reset(sys.argv[2])


if __name__ == "__main__":
    asyncio.run(main())
