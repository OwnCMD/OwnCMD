#!/usr/bin/env python3
"""Read-only host capability checks shared by native Linux installers.

Distribution names select package automation only. Prepared hosts qualify by
capabilities, without bypassing the sandbox, database or service requirements.
"""

import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def os_release(path=Path("/etc/os-release")):
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def automatic_packages(values):
    return (values.get("ID"), values.get("VERSION_ID")) in {
        ("ubuntu", "24.04"),
        ("ubuntu", "26.04"),
        ("debian", "13"),
    }


def postgres_bin(environ=None):
    """Find complete, matching server/client tools; explicit override wins.

    Debian keeps majors under /usr/lib, PGDG RPMs under /usr/pgsql-N,
    SUSE under /usr/lib/postgresqlN, and Arch/Fedora may use /usr/bin.
    Never mix initdb from one major with pg_ctl/pg_dump from another.
    """
    env = os.environ if environ is None else environ
    required = ("initdb", "pg_ctl", "postgres", "psql", "createdb", "pg_dump")
    explicit = env.get("OWNCMD_PG_BINDIR")
    if explicit:
        candidates = [Path(explicit)]
    else:
        candidates = list(Path("/usr/lib/postgresql").glob("*/bin"))
        candidates += list(Path("/usr").glob("pgsql-*/bin"))
        candidates += list(Path("/usr/lib").glob("postgresql*/bin"))
        candidates += [Path("/usr/bin"), Path("/usr/local/pgsql/bin")]
        found = shutil.which("initdb")
        if found:
            candidates.append(Path(found).resolve().parent)
    matches = []
    for directory in set(candidates):
        if not re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(directory)):
            continue
        if not directory.is_absolute() or not all(
            os.access(directory / name, os.X_OK) for name in required
        ):
            continue
        versions = []
        for name in required:
            result = subprocess.run(
                [str(directory / name), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            match = re.search(r"\(PostgreSQL\) (\d+)", result.stdout)
            if result.returncode or not match:
                break
            versions.append(int(match.group(1)))
        if (
            len(versions) == len(required)
            and len(set(versions)) == 1
            and versions[0] >= 14
        ):
            matches.append((versions[0], str(directory)))
    if not matches:
        raise RuntimeError(
            "Install matching PostgreSQL 14+ server/client tools, or set OWNCMD_PG_BINDIR to their absolute bin directory."
        )
    return Path(max(matches)[1])


def check(prepared=False):
    errors = []
    if platform.system() != "Linux":
        errors.append("A Linux host is required.")
    if platform.machine() not in ("x86_64", "aarch64"):
        errors.append("Supported architectures: x86_64 and aarch64.")
    version = re.match(r"(\d+)\.(\d+)", platform.release())
    if not version or tuple(map(int, version.groups())) < (5, 6):
        errors.append("gVisor requires Linux kernel 5.6 or newer.")
    if sys.version_info < (3, 12):
        errors.append("Python 3.12 or newer is required as python3.")
    if not Path("/run/systemd/system").is_dir():
        errors.append(
            "A running systemd host is required. OpenRC/runit hosts need a service adapter; do not run this installer in an ordinary container."
        )
    commands = [
        "bash",
        "systemctl",
        "flock",
        "runuser",
        "useradd",
        "findmnt",
        "mount",
        "umount",
        "nologin",
    ]
    if prepared:
        commands += [
            "docker",
            "dockerd",
            "runsc",
            "caddy",
            "iptables",
            "pdftotext",
            "pdftoppm",
            "tesseract",
        ]
    for name in commands:
        if not shutil.which(name):
            errors.append(f"Missing required command: {name}")
    if prepared:
        try:
            postgres_bin()
        except RuntimeError as exc:
            errors.append(str(exc))
        # Check presence, not active state: services are enabled only by install.
        for unit in (
            ("docker.service", "postgresql.service", "caddy.service")
            if shutil.which("systemctl")
            else ()
        ):
            result = subprocess.run(
                ["systemctl", "show", "-p", "LoadState", "--value", unit],
                capture_output=True,
                text=True,
            )
            if result.returncode or result.stdout.strip() != "loaded":
                errors.append(
                    f"Missing systemd unit: {unit}. Supply the documented unit/alias before installation."
                )
        result = subprocess.run(
            [sys.executable, "-c", "import venv, ensurepip"], capture_output=True
        )
        if result.returncode:
            errors.append("Python venv and ensurepip support is required.")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-host", action="store_true")
    parser.add_argument("--pg-bindir", action="store_true")
    args = parser.parse_args()
    if args.pg_bindir:
        try:
            print(postgres_bin())
        except RuntimeError as exc:
            parser.exit(1, str(exc) + "\n")
        return
    values = os_release() if Path("/etc/os-release").exists() else {}
    print("Host:", values.get("PRETTY_NAME", platform.system()), platform.machine())
    prepared = args.prepared_host or not automatic_packages(values)
    print(
        "Package mode:",
        "operator-prepared dependencies" if prepared else "automatic APT setup",
    )
    errors = check(prepared)
    for error in errors:
        print("FAIL:", error)
    if not errors:
        print(
            "Host prerequisites passed. Runtime, database, firewall and sandbox checks still run during installation."
        )
    sys.exit(bool(errors))


if __name__ == "__main__":
    main()
