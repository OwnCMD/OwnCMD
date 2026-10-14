"""Provision pgvector for the actual PostgreSQL major, without elevating app role."""

import os, subprocess, sys
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict
from linux_host import postgres_bin


def install(major):
    if not 13 <= major <= 99:
        raise SystemExit("Unsupported PostgreSQL major")
    if os.environ.get("OWNCMD_PACKAGE_MODE") == "prepared":
        # Never guess RPM/PGDG/Arch package names or mix PostgreSQL majors.
        # The disposable cluster and production database both exercise vector.
        print(
            f"Using operator-provided pgvector for PostgreSQL {major}; SQL verification follows."
        )
        return
    package = f"postgresql-{major}-pgvector"
    r = subprocess.run(["apt-cache", "show", package], capture_output=True)
    if r.returncode or not r.stdout:
        setup = Path("/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh")
        if not setup.exists():
            raise SystemExit(
                f"Configure the official PostgreSQL APT repository for {package}, then retry."
            )
        subprocess.run([str(setup), "-y"], check=True)
        subprocess.run(["apt-get", "update"], check=True)
    subprocess.run(
        ["apt-get", "install", "-y", "--no-install-recommends", package], check=True
    )


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit(
            "Run as root; the application database role remains least-privileged."
        )
    if sys.argv[1:] == ["--test-tools"]:
        output = subprocess.check_output(
            [str(postgres_bin() / "postgres"), "--version"], text=True
        )
        import re

        major = int(re.search(r"\(PostgreSQL\) (\d+)", output).group(1))
        install(major)
        sys.exit(0)
    if sys.argv[1:]:
        raise SystemExit("Usage: configure_pgvector.py [--test-tools]")
    values = dict(
        line.split("=", 1)
        for line in Path("/etc/aster/config.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    url = values["ASTER_DATABASE_URL"]
    info = conninfo_to_dict(url)
    with psycopg.connect(url, connect_timeout=10) as c:
        major = c.info.server_version // 10000
        if c.execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone():
            c.execute("SELECT '[1,0]'::vector <=> '[1,0]'::vector")
            print(f"pgvector verified on PostgreSQL {major}.")
            sys.exit(0)
    if info.get("host", "") not in (
        "",
        "localhost",
        "127.0.0.1",
        "::1",
        "/var/run/postgresql",
    ):
        raise SystemExit(
            f"Remote PostgreSQL {major}: ask its administrator to install matching pgvector and CREATE EXTENSION vector in the OwnCMD database, then retry. Existing data is unchanged."
        )
    install(major)
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
            info.get("port", "5432"),
            "-U",
            "postgres",
            "-d",
            info.get("dbname", "aster"),
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input="CREATE EXTENSION IF NOT EXISTS vector;\n",
        text=True,
        check=True,
        timeout=60,
    )
    with psycopg.connect(url, connect_timeout=10) as c:
        if c.info.server_version // 10000 != major:
            raise SystemExit("PostgreSQL server changed during setup; retry")
        c.execute("SELECT '[1,0]'::vector <=> '[1,0]'::vector")
    print(
        f"pgvector verified on existing PostgreSQL {major}; application privileges unchanged."
    )
