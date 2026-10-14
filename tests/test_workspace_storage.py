"""Quota transport and cleanup regressions. Native enforcement runs in install.sh."""

import asyncio
import importlib.util
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app import broker, core
from app.workspace_storage import workspace_mount
from test_sandbox_mounts import volume_options

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "workspace_probe", ROOT / "scripts/verify_workspace_storage.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize("mb,files", [(1, 31), (16, 100), (64, 500), (1536, 500000)])
def test_limits_reach_host_volume_without_csv_splitting(mb, files):
    opts = volume_options(["--mount", workspace_mount(mb, files)])
    assert {
        f"size={mb}m",
        f"nr_inodes={files+1}",
        "mode=0700",
        "uid=1000",
        "gid=1000",
        "nosuid",
        "nodev",
        "exec",
    } <= opts


@pytest.mark.parametrize(
    "mb,files",
    [
        (0, 100),
        (1537, 100),
        (64, 0),
        (64, 500001),
        ("64", 100),
        (True, 100),
        (64, False),
        (64, 1.5),
        (None, 100),
    ],
)
def test_mount_rejects_invalid_or_unbounded_limits(mb, files):
    with pytest.raises(ValueError):
        workspace_mount(mb, files)


@pytest.mark.parametrize("failure", [None, "exit", "timeout"])
def test_native_gate_checks_real_writes_and_cleans_up(failure, monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == "run":
            assert volume_options(args) >= {"size=1m", "nr_inodes=32"}
            assert (
                "--rm" in args
                and "--runtime=runsc" in args
                and "--network=none" in args
            )
            assert "--cap-drop=ALL" in args and "--read-only" in args
            assert (
                "ThreadPoolExecutor" in kwargs["input"]
                and "errno.ENOSPC" in kwargs["input"]
            )
            assert (
                "large.unlink" in kwargs["input"] and "replacement" in kwargs["input"]
            )
            compile(kwargs["input"], "<native-quota-probe>", "exec")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 90)
            return subprocess.CompletedProcess(args, 1 if failure == "exit" else 0)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(probe.subprocess, "run", run)
    if failure:
        with pytest.raises(
            RuntimeError if failure == "exit" else subprocess.TimeoutExpired
        ):
            probe.verify()
    else:
        probe.verify()
    assert len(calls) == 2
    name = calls[0][0][calls[0][0].index("--name") + 1]
    assert calls[1][0] == ["docker", "rm", "-f", "-v", name]


def test_installer_checks_same_mount_before_activation_and_limits_overlays():
    script = (ROOT / "install.sh").read_text()
    assert (
        script.index("verify_workspace_storage.py")
        < script.index("/opt/verify_runtime.py")
        < script.index('atomic_current "$release"')
    )
    assert '$(python3 "$HERE/app/workspace_storage.py" 1536 100000)' in script
    assert '--mount "$runtime_work_mount"' in script
    assert "'--overlay2=root:self'" in script
    assert "update gVisor before continuing" not in script
    # A broker restart/failure must not be the owner of a privileged host mount.
    assert "volume-driver=local" in workspace_mount(64, 500)
    assert "mount -t" not in (ROOT / "app/broker.py").read_text()


@pytest.mark.parametrize("failure", ["run", "inspect", "health", "credit"])
def test_failed_allocation_removes_container_and_anonymous_volume(failure, monkeypatch):
    task = core.ident()
    name = broker.name(task)
    calls = []

    async def docker(*args):
        calls.append(args)
        if args[0] == "run" and failure == "run":
            raise HTTPException(503, "simulated startup failure")
        return ""

    async def inspect(*args):
        if failure == "inspect":
            raise HTTPException(503, "simulated inspect failure")
        return "http://sandbox"

    async def sleep(*args):
        pass

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args):
            return httpx.Response(503 if failure == "health" else 200)

    def billing(*args):
        if failure == "credit":
            raise broker.billing.CreditError("No credit")

    monkeypatch.setattr(broker, "cmd", docker)
    monkeypatch.setattr(broker, "inspect_url", inspect)
    monkeypatch.setattr(broker, "task_owner", lambda task: None)
    monkeypatch.setattr(broker.httpx, "AsyncClient", Client)
    monkeypatch.setattr(broker.billing, "start_runtime", billing)
    monkeypatch.setattr(broker.asyncio, "sleep", sleep)
    try:
        with pytest.raises(HTTPException) as error:
            asyncio.run(broker.endpoint(task))
        assert error.value.status_code == (402 if failure == "credit" else 503)
        assert ("rm", "-f", "-v", name) in calls
        assert name not in broker.urls and name not in broker.stopping
    finally:
        broker.forget(name)


def test_failed_cleanup_stays_stopped_and_is_retried(monkeypatch):
    name = broker.name(core.ident())
    calls = []

    async def docker(*args):
        calls.append(args)
        if len(calls) == 1:
            raise HTTPException(503, "Docker temporarily unavailable")
        return ""

    monkeypatch.setattr(broker, "cmd", docker)
    try:
        asyncio.run(broker.discard_failed_start(name))
        assert name in broker.stopping
        with pytest.raises(HTTPException):
            broker.existing_endpoint(name.removeprefix("aster-code-"), "code")
        asyncio.run(broker.retire(name))
        assert name not in broker.stopping
        assert calls == [("rm", "-f", "-v", name)] * 2
    finally:
        broker.forget(name)
