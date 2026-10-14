"""Regression: host PostgreSQL must not become a sandbox checkpoint target in tests."""

import asyncio
import subprocess
import pytest
from test_sandbox import sandbox, sc


def test_snapshot_unit_tests_never_probe_host_databases(sc, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("A sandbox unit test tried to connect to a host database")

    monkeypatch.setattr(sandbox.asyncio, "open_connection", forbidden)
    result = sc.post("/snapshot", json={})
    assert result.status_code == 200
    assert result.json()["data"]


@pytest.mark.parametrize("failure", [False, True])
def test_postgresql_checkpoint_is_noninteractive_and_preserves_prior_dump(
    tmp_path, monkeypatch, failure
):
    monkeypatch.setattr(sandbox, "root", tmp_path)
    folder = tmp_path / ".aster"
    folder.mkdir()
    saved = folder / "postgres.sql"
    saved.write_bytes(b"previous valid dump")

    async def available(port):
        return port == 5432

    monkeypatch.setattr(sandbox, "database_available", available)
    calls = []

    class Process:
        returncode = 1 if failure else 0

        async def communicate(self):
            return None, b"authentication failed" if failure else b""

    async def create(*args, **kwargs):
        calls.append(args)
        assert "--no-password" in args
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        kwargs["stdout"].write(b"new valid dump" if not failure else b"partial output")
        return Process()

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", create)
    if failure:
        with pytest.raises(ValueError, match="Database export failed"):
            asyncio.run(sandbox._checkpoint_databases())
        assert saved.read_bytes() == b"previous valid dump"
    else:
        asyncio.run(sandbox._checkpoint_databases())
        assert saved.read_bytes() == b"new valid dump"
    assert len(calls) == 1 and calls[0][0] == "pg_dumpall"


def test_database_checkpoint_timeout_kills_export_and_preserves_saved_copy(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sandbox, "root", tmp_path)
    folder = tmp_path / ".aster"
    folder.mkdir()
    saved = folder / "postgres.sql"
    saved.write_bytes(b"valid dump")

    async def available(port):
        return port == 5432

    monkeypatch.setattr(sandbox, "database_available", available)
    calls = []

    class Process:
        async def communicate(self):
            raise asyncio.TimeoutError()

        def kill(self):
            calls.append("killed")

        async def wait(self):
            calls.append("reaped")

    async def create(*args, **kwargs):
        return Process()

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", create)
    with pytest.raises(ValueError, match="export timed out"):
        asyncio.run(sandbox._checkpoint_databases())
    assert calls == ["killed", "reaped"]
    assert saved.read_bytes() == b"valid dump"


def test_platform_backup_passes_generated_credentials_without_prompting(
    tmp_path, monkeypatch
):
    from app.database import dump_database

    monkeypatch.setenv(
        "ASTER_DATABASE_URL",
        "postgresql://aster_app:generated-secret@127.0.0.1:5432/aster",
    )
    calls = []

    def run(args, **kwargs):
        assert "--no-password" in args
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["PGPASSWORD"] == "generated-secret"
        assert kwargs["env"]["PGUSER"] == "aster_app"
        assert kwargs["env"]["PGDATABASE"] == "aster"
        assert "generated-secret" not in " ".join(args)
        calls.append(args)
        (tmp_path / "postgres.dump").write_bytes(b"test dump")

    monkeypatch.setattr(subprocess, "run", run)
    dump_database(tmp_path / "postgres.dump")
    assert len(calls) == 1
    assert (tmp_path / "postgres.dump").stat().st_mode & 0o777 == 0o600
