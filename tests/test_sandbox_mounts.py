"""Check the actual Docker launch arguments and the installer's matching runtime gate."""

import asyncio, csv, shlex, uuid
from pathlib import Path
import httpx, pytest
from app import broker, core
from app.workspace_storage import workspace_mount

ROOT = Path(__file__).resolve().parents[1]


def mounts(arguments):
    return {
        arguments[i + 1].split(":", 1)[0]: set(
            arguments[i + 1].split(":", 1)[1].split(",")
        )
        for i, arg in enumerate(arguments)
        if arg == "--tmpfs"
    }


def volume_options(arguments):
    fields = next(csv.reader([arguments[arguments.index("--mount") + 1]]))
    values = dict(
        field.split("=", 1) if "=" in field else (field, True) for field in fields
    )
    assert (
        values["type"] == "volume"
        and values["target"] == "/work"
        and values["volume-driver"] == "local"
    )
    assert (
        values["volume-nocopy"] is True
        and "source" not in values
        and "src" not in values
    )
    assert "volume-opt=type=tmpfs" in fields and "volume-opt=device=tmpfs" in fields
    return set(
        next(
            field.removeprefix("volume-opt=o=")
            for field in fields
            if field.startswith("volume-opt=o=")
        ).split(",")
    )


@pytest.mark.parametrize("kind", ["code", "browser"])
def test_container_mount_execution_policy_and_isolation(kind, monkeypatch):
    owner = str(uuid.uuid4())
    with core.db() as c:
        c.execute(
            "INSERT INTO users VALUES(%s,%s,%s,%s)",
            (owner, owner + "@test.com", "unused", 0),
        )
    task = core.create_task(owner, "Mount test")
    captured = []

    async def docker(*args):
        if args[0] == "ps":
            return ""
        if args[0] == "run":
            captured.extend(args)
            return "test-container"
        raise AssertionError(args)

    async def inspect(*args):
        return "http://sandbox"

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args):
            return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(broker, "cmd", docker)
    monkeypatch.setattr(broker, "inspect_url", inspect)
    monkeypatch.setattr(broker.httpx, "AsyncClient", Client)
    monkeypatch.setattr(broker, "task_owner", lambda task: None)
    try:
        assert asyncio.run(broker.endpoint(task, kind=kind)) == "http://sandbox"
        policy = mounts(captured)
        expected = "exec" if kind == "code" else "noexec"
        if kind == "code":
            assert "/work" not in policy
            policy["/work"] = volume_options(captured)
            assert "--rm" in captured
        assert set(policy) == {"/work", "/tmp"}
        for options in policy.values():
            assert {
                expected,
                "rw",
                "nosuid",
                "nodev",
                "uid=1000",
                "gid=1000",
            } <= options
            assert ("noexec" if expected == "exec" else "exec") not in options
        assert "--read-only" in captured and "--cap-drop=ALL" in captured
        assert captured[captured.index("--security-opt") + 1] == "no-new-privileges"
        assert "--privileged" not in captured and "--network" in captured
        assert (
            "--runtime=" + ("runsc" if kind == "code" else "runsc-browser") in captured
        )
    finally:
        broker.forget(broker.name(task, kind))


def test_installer_runtime_gate_allows_compiled_code_without_extra_privileges():
    line = next(
        line
        for line in (ROOT / "install.sh").read_text().splitlines()
        if line.startswith("docker run ") and "/opt/verify_runtime.py" in line
    )
    args = shlex.split(line)
    policy = mounts(args)
    assert args[args.index("--mount") + 1] == "$runtime_work_mount"
    policy["/work"] = volume_options(["--mount", workspace_mount(1536, 100000)])
    for path in ("/work", "/tmp"):
        assert {"exec", "nosuid", "nodev", "rw", "uid=1000", "gid=1000"} <= policy[path]
        assert "noexec" not in policy[path]
    assert (
        "--read-only" in args and "--cap-drop=ALL" in args and "--network=none" in args
    )
    assert "--runtime=runsc" in args and "--privileged" not in args
