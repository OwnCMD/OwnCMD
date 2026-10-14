"""Portable installer decisions without changing packages, services or host data."""

import importlib.util
from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "linux_host", ROOT / "scripts/linux_host.py"
)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


@pytest.mark.parametrize(
    "name,version,automatic",
    [
        ("ubuntu", "24.04", True),
        ("ubuntu", "26.04", True),
        ("debian", "13", True),
        ("debian", "12", False),
        ("fedora", "44", False),
        ("arch", "", False),
        ("rocky", "9", False),
        ("opensuse-tumbleweed", "", False),
        ("alpine", "3.22", False),
    ],
)
def test_package_selection(name, version, automatic):
    assert host.automatic_packages({"ID": name, "VERSION_ID": version}) is automatic


def test_os_release_is_data_not_shell(tmp_path):
    path = tmp_path / "os-release"
    path.write_text(
        'ID=debian\nVERSION_ID="13"\nPRETTY_NAME="$(touch /no-command-execution)"\n'
    )
    assert host.os_release(path)["PRETTY_NAME"] == "$(touch /no-command-execution)"


def tools_at(path, major=18):
    path.mkdir()
    for name in ("initdb", "postgres", "pg_ctl", "psql", "pg_dump", "createdb"):
        tool = path / name
        tool.write_text(f'#!/bin/sh\necho "{name} (PostgreSQL) {major}.1"\n')
        tool.chmod(0o755)
    return path


def test_explicit_postgres_directory_and_mismatched_clients(tmp_path):
    directory = tools_at(tmp_path / "pgsql")
    env = {"OWNCMD_PG_BINDIR": str(directory)}
    assert host.postgres_bin(env) == directory
    (directory / "pg_dump").write_text('#!/bin/sh\necho "pg_dump (PostgreSQL) 16.1"\n')
    with pytest.raises(RuntimeError, match="matching PostgreSQL"):
        host.postgres_bin(env)


def test_invalid_override_does_not_silently_choose_another_cluster(tmp_path):
    with pytest.raises(RuntimeError):
        host.postgres_bin({"OWNCMD_PG_BINDIR": str(tmp_path / "missing")})


def test_prepared_check_reports_missing_services_without_crashing(monkeypatch):
    monkeypatch.setattr(host.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        host,
        "postgres_bin",
        lambda: (_ for _ in ()).throw(RuntimeError("Missing PostgreSQL")),
    )
    errors = host.check(True)
    assert "Missing required command: systemctl" in errors
    assert "Missing required command: runsc" in errors
    assert "Missing PostgreSQL" in errors


def test_non_linux_rejected_before_lock_and_reset(tmp_path):
    binary = tmp_path / "uname"
    binary.write_text("#!/bin/sh\necho FreeBSD\n")
    binary.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--check-system"],
        env={**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "requires Linux" in result.stdout


def test_prepared_pgvector_never_runs_package_manager(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import configure_pgvector

    monkeypatch.setenv("OWNCMD_PACKAGE_MODE", "prepared")
    monkeypatch.setattr(
        configure_pgvector.subprocess,
        "run",
        lambda *a, **k: pytest.fail("Unexpected package manager call"),
    )
    configure_pgvector.install(18)


def test_service_and_backup_paths_are_preserved():
    installer = (ROOT / "install.sh").read_text()
    assert 'Environment="PATH=$pg_bindir:' in installer
    assert "OWNCMD_PG_BINDIR=" in installer
    assert 'env["OWNCMD_PG_BINDIR"] + os.pathsep' in (ROOT / "asterctl").read_text()
    assert "iptables -S DOCKER-USER" in installer


def test_generated_systemd_units_expand_selected_postgres_path():
    # Evaluate the actual heredocs, without writing to /etc or starting services.
    import re

    installer = (ROOT / "install.sh").read_text()
    blocks = re.findall(
        r"cat > (/etc/systemd/system/[^ ]+) <<('?)UNIT\n(.*?)\nUNIT", installer, re.S
    )
    assert len(blocks) >= 5
    for name, quoted, body in blocks:
        if 'Environment="PATH=' not in body:
            continue
        script = (
            "pg_bindir=/usr/pgsql-18/bin\nrelease=/opt/aster/releases/test\ncat <<"
            + quoted
            + "UNIT"
            + quoted
            + "\n"
            + body
            + "\nUNIT\n"
        )
        rendered = subprocess.check_output(["bash", "-c", script], text=True)
        assert "$pg_bindir" not in rendered, name
        assert 'Environment="PATH=/usr/pgsql-18/bin:' in rendered, name
