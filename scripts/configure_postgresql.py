"""Provision a local least-privilege PostgreSQL database, preserving configured URLs."""

import os
from pathlib import Path
import secrets
import subprocess
import psycopg
from psycopg import sql

config = Path("/etc/aster/config.env")
text = config.read_text()
values = dict(
    line.split("=", 1)
    for line in text.splitlines()
    if line and not line.startswith("#") and "=" in line
)
if values.get("ASTER_DATABASE_URL"):
    if not values["ASTER_DATABASE_URL"].startswith(("postgresql://", "postgres://")):
        raise SystemExit("ASTER_DATABASE_URL must be PostgreSQL")
    with psycopg.connect(values["ASTER_DATABASE_URL"], connect_timeout=10) as c:
        c.execute("SELECT 1")
else:
    # The private provisioning record makes interrupted setup safely resumable.
    state = Path("/etc/aster/postgresql-setup.json")
    import json

    if state.exists():
        setup = json.loads(state.read_text())
    else:
        # Never take over a pre-existing role or database with an unknown owner.
        check = subprocess.run(
            [
                "runuser",
                "-u",
                "postgres",
                "--",
                "psql",
                "--no-password",
                "-h",
                "/var/run/postgresql",
                "-p",
                "5432",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-XAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT 1 FROM pg_roles WHERE rolname='aster_app' UNION ALL SELECT 1 FROM pg_database WHERE datname='aster'",
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=True,
        )
        if check.stdout.strip():
            raise SystemExit(
                "Existing aster database/role found without configuration; set ASTER_DATABASE_URL to the intended database before retrying"
            )
        setup = {"password": secrets.token_hex(32)}
        with state.open("x") as f:
            json.dump(setup, f)
        state.chmod(0o600)
    password = setup["password"]
    statement = (
        sql.SQL(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='aster_app') THEN CREATE ROLE aster_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}; END IF; END $$;"
        )
        .format(sql.Literal(password))
        .as_string()
    )
    subprocess.run(
        [
            "runuser",
            "-u",
            "postgres",
            "--",
            "psql",
            "--no-password",
            "-h",
            "/var/run/postgresql",
            "-p",
            "5432",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=statement,
        text=True,
        timeout=30,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    exists = subprocess.run(
        [
            "runuser",
            "-u",
            "postgres",
            "--",
            "psql",
            "--no-password",
            "-h",
            "/var/run/postgresql",
            "-p",
            "5432",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-XAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT 1 FROM pg_database WHERE datname='aster'",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=True,
    ).stdout.strip()
    if not exists:
        subprocess.run(
            [
                "runuser",
                "-u",
                "postgres",
                "--",
                "createdb",
                "--no-password",
                "-h",
                "/var/run/postgresql",
                "-p",
                "5432",
                "-U",
                "postgres",
                "--owner=aster_app",
                "--encoding=UTF8",
                "--template=template0",
                "aster",
            ],
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=True,
        )
    url = "postgresql://aster_app:" + password + "@127.0.0.1:5432/aster"
    with psycopg.connect(url, connect_timeout=10) as c:
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        c.execute("SELECT 1")
    temp = config.with_suffix(".postgres.tmp")
    temp.write_text(text.rstrip() + "\nASTER_DATABASE_URL=" + url + "\n")
    temp.chmod(0o640)
    os.chown(temp, config.stat().st_uid, config.stat().st_gid)
    temp.replace(config)
print(
    "PostgreSQL connection verified; credentials retained in protected configuration."
)
