"""Erase only an installer-managed local OwnCMD installation (--fresh-install).
No shell evaluation, host-wide pruning, PostgreSQL cluster deletion or SSH changes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

from configure_site import read_config, site_settings

BASE_UNITS = (
    "aster-api.service",
    "aster-broker.service",
    "aster-package-proxy.service",
    "aster-firewall.service",
)
WORKER = re.compile(r"aster-worker@[^/\s]*\.service\Z")
CONTAINER = re.compile(r"aster-(?:code|browser)-[a-f0-9-]{36}\Z")
ROOTS = ("/var/lib/aster", "/opt/aster", "/etc/aster")
PG_SQL = """SELECT json_build_object(
 'database_owner',(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='aster'),
 'role_exists',EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aster_app'),
 'privileged',EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aster_app' AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication)),
 'other_dependencies',EXISTS(SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass
   AND refobjid=(SELECT oid FROM pg_roles WHERE rolname='aster_app')
   AND (dbid NOT IN (0,coalesce((SELECT oid FROM pg_database WHERE datname='aster'),0))
        OR (dbid=0 AND NOT (classid='pg_database'::regclass AND objid=coalesce((SELECT oid FROM pg_database WHERE datname='aster'),0)))))
);"""


def run(args, **kwargs):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        env=env,
        **kwargs
    ).stdout.strip()


def validate_managed_config(values):
    if values.get("ASTER_DATA", "/var/lib/aster") != "/var/lib/aster":
        raise ValueError(
            "Clean installation refuses a custom ASTER_DATA location. Reset that deployment explicitly first."
        )
    url = values.get("ASTER_DATABASE_URL")
    if url:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("postgresql", "postgres")
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.port not in (None, 5432)
            or parsed.username != "aster_app"
            or parsed.path != "/aster"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Clean installation refuses a remote or custom PostgreSQL destination. No data was erased."
            )


def validate_database(state, managed):
    if (state["database_owner"] or state["role_exists"]) and not managed:
        raise ValueError(
            "Database/role found without OwnCMD installation ownership evidence; no data was erased."
        )
    if (
        state["database_owner"] not in (None, "aster_app")
        or state["privileged"]
        or state["other_dependencies"]
    ):
        raise ValueError(
            "OwnCMD database/role is shared or has unexpected ownership; no data was erased."
        )


def mount_points():
    # mountinfo also identifies same-filesystem bind mounts (ismount alone cannot).
    points = set()
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        encoded = line.split()[4]
        points.add(
            Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), encoded))
        )
    return points


def validate_path(path):
    # Do not follow links or erase mounted data elsewhere, even under a known root.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Refusing reset through a symlink: " + str(part))
    if path.exists() and path.is_dir():
        if any(point.is_relative_to(path) for point in mount_points()):
            raise ValueError(
                "Refusing reset of a directory containing mounted data: " + str(path)
            )
        for current, dirs, _ in os.walk(path, followlinks=False):
            if os.path.ismount(current):
                raise ValueError("Refusing reset of mounted directory: " + current)
            dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]


class Reset:
    def __init__(self, root=Path("/"), execute=run, which=shutil.which):
        self.root, self.execute, self.which = root, execute, which
        self.pg = False
        self.units = []
        self.containers = []
        self.networks = []
        self.images = []
        self.paths = []

    def path(self, absolute):
        return self.root / absolute.lstrip("/")

    def psql(self, statement):
        return self.execute(
            [
                "runuser",
                "-u",
                "postgres",
                "--",
                "psql",
                "--no-password",
                "-XAt",
                "-h",
                "/var/run/postgresql",
                "-p",
                "5432",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                statement,
            ]
        )

    def packaged_caddy_default(self, path):
        # A failed first install may still have Debian/Ubuntu's untouched default
        # site. Match its package-recorded checksum, never a loose text pattern.
        try:
            records = self.execute(["dpkg-query", "-W", "-f=${Conffiles}", "caddy"])
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
        return any(
            parts == ["/etc/caddy/Caddyfile", digest]
            for parts in (line.split() for line in records.splitlines())
        )

    def inspect_docker(self):
        if not self.which("docker"):
            return
        # Failure to contact an installed daemon is an error, not evidence of no data.
        rows = self.execute(
            ["docker", "ps", "-a", "--format", "{{json .}}"]
        ).splitlines()
        all_containers = [json.loads(row) for row in rows]
        self.containers = []
        for entry in all_containers:
            if not CONTAINER.fullmatch(entry["Names"]):
                continue
            detail = json.loads(self.execute(["docker", "inspect", entry["ID"]]))[0]
            if detail.get("Config", {}).get("Labels", {}).get("aster.sandbox") != "1":
                raise ValueError(
                    "OwnCMD-named container lacks ownership label; no data was erased."
                )
            self.containers.append(entry["ID"])
        names = self.execute(
            ["docker", "network", "ls", "--format", "{{.Name}}"]
        ).splitlines()
        self.networks = [
            name for name in ("aster-code", "aster-sandbox") if name in names
        ]
        for name in self.networks:
            detail = json.loads(self.execute(["docker", "network", "inspect", name]))[0]
            for entry in detail.get("Containers", {}).values():
                if not CONTAINER.fullmatch(entry.get("Name", "")):
                    raise ValueError(
                        "OwnCMD network contains an unrelated container; no data was erased."
                    )
        # Remove only OwnCMD image tags; shared underlying layers are Docker-managed.
        self.images = self.execute(
            [
                "docker",
                "image",
                "ls",
                "--filter",
                "reference=aster-sandbox:*",
                "--format",
                "{{.Repository}}:{{.Tag}}",
            ]
        ).splitlines()
        for entry in all_containers:
            if entry["ID"] not in self.containers and entry.get("Image") in self.images:
                raise ValueError(
                    "OwnCMD image is used by an unrelated container; no data was erased."
                )

    def preflight(self):
        config = self.path("/etc/aster/config.env")
        managed = any(
            self.path("/etc/aster/" + marker).is_file()
            for marker in ("installed", "install-started", "postgresql-setup.json")
        )
        if config.is_symlink():
            raise ValueError("Refusing a symlinked OwnCMD configuration.")
        values = read_config(config) if config.exists() else {}
        validate_managed_config(values)
        for absolute in ROOTS:
            path = self.path(absolute)
            validate_path(path)
            if path.exists() and any(path.iterdir()) and not managed:
                raise ValueError(
                    "OwnCMD directory found without installation ownership evidence; no data was erased."
                )
            self.paths.append(path)
        if self.root == Path("/"):
            here = Path(__file__).resolve()
            if any(here.is_relative_to(path) for path in self.paths):
                raise ValueError(
                    "Run the standalone installer outside /opt/aster, /etc/aster and /var/lib/aster."
                )
        caddyfile = self.path("/etc/caddy/Caddyfile")
        if caddyfile.exists() and caddyfile.read_text().strip():
            if not managed:
                raise ValueError(
                    "Existing Caddy configuration is not owned by OwnCMD; no data was erased."
                )
            # OwnCMD installs one reverse-proxy site. Reject operator-added shared sites.
            content = caddyfile.read_text()
            if values:
                host, _ = site_settings(values)
                from configure_site import render_caddy

                legacy_tls = "tls internal" if re.fullmatch(r"[0-9.]+", host) else ""
                legacy = (
                    host
                    + " { "
                    + legacy_tls
                    + " encode gzip request_body { max_size 26MB } reverse_proxy 127.0.0.1:8000 }"
                )
                compact = lambda text: re.sub(r"\s+", "", re.sub(r"(?m)#.*$", "", text))
                if compact(content) not in {
                    compact(legacy),
                    compact(render_caddy(values)),
                } and not self.packaged_caddy_default(caddyfile):
                    raise ValueError(
                        "Caddy configuration was customized; refusing to erase shared/custom sites."
                    )
                certs = self.path("/var/lib/caddy/.local/share/caddy/certificates")
                validate_path(certs)
                if certs.exists():
                    for issuer in certs.iterdir():
                        if issuer.is_dir() and not issuer.is_symlink():
                            cert = issuer / host
                            validate_path(cert)
                            if cert.exists():
                                self.paths.append(cert)
            elif not self.packaged_caddy_default(caddyfile):
                raise ValueError(
                    "Cannot identify the owner of the existing Caddy site; no data was erased."
                )
            validate_path(caddyfile)
            self.paths.append(caddyfile)
        self.inspect_docker()
        unit_rows = self.execute(
            ["systemctl", "list-unit-files", "--no-legend", "--no-pager"]
        ).splitlines()
        live_rows = self.execute(
            ["systemctl", "list-units", "--all", "--plain", "--no-legend", "--no-pager"]
        ).splitlines()
        available = {row.split()[0] for row in unit_rows + live_rows if row.split()}
        self.units = sorted(
            unit for unit in available if unit in BASE_UNITS or WORKER.fullmatch(unit)
        )
        if not managed and (
            self.units or self.containers or self.networks or self.images
        ):
            raise ValueError(
                "OwnCMD-named resources lack installation ownership evidence; no data was erased."
            )
        for unit in sorted(
            set(BASE_UNITS) | {"aster-worker@.service"} | set(self.units)
        ):
            for suffix in ("", ".d"):
                path = self.path("/etc/systemd/system/" + unit + suffix)
                validate_path(path)
                if path.exists():
                    self.paths.append(path)
        self.paths.append(self.path("/usr/local/bin/asterctl"))
        if self.which("psql"):
            self.pg = True
            validate_database(json.loads(self.psql(PG_SQL)), managed)
        elif (
            values.get("ASTER_DATABASE_URL")
            or self.path("/etc/aster/postgresql-setup.json").exists()
        ):
            raise ValueError(
                "PostgreSQL tools unavailable; cannot safely erase existing database. No data was erased."
            )
        return self

    def describe(self):
        print(
            "DESTRUCTIVE CLEAN INSTALL: erase all local OwnCMD accounts, conversations, credits, schedules,"
        )
        print(
            "workspaces, cookies, backups, secrets, releases, sandbox containers and the managed PostgreSQL database/role."
        )
        print(
            "New credentials and encryption keys will be generated. No automatic backup is retained."
        )
        print(
            "PostgreSQL target: local database aster / role aster_app"
            if self.pg
            else "No PostgreSQL installation detected."
        )
        print("Paths: " + ", ".join(map(str, self.paths)))
        print("OwnCMD units: " + ", ".join(self.units))
        print("OwnCMD containers: " + ", ".join(self.containers))
        print("OwnCMD networks/images: " + ", ".join(self.networks + self.images))

    def apply(self):
        # Preflight has completed before the first mutation. Stop all writers first.
        units = [unit for unit in self.units if unit != "aster-worker@.service"]
        if units:
            self.execute(["systemctl", "disable", "--now", *units])
        if self.path("/etc/caddy/Caddyfile") in self.paths:
            self.execute(["systemctl", "stop", "caddy"])
        self.inspect_docker()  # Workers can no longer create a late sandbox.
        if self.containers:
            self.execute(["docker", "rm", "-f", *self.containers])
        if self.networks:
            self.execute(["docker", "network", "rm", *self.networks])
        if self.images:
            self.execute(["docker", "image", "rm", *self.images])
        if self.pg:
            validate_database(json.loads(self.psql(PG_SQL)), True)
            self.psql("DROP DATABASE IF EXISTS aster WITH (FORCE)")
            self.psql("DROP ROLE IF EXISTS aster_app")
        self.clear_firewall()
        # Remove configuration last: ownership evidence survives interrupted resets.
        for path in sorted(self.paths, key=lambda p: p == self.path("/etc/aster")):
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        self.execute(["systemctl", "daemon-reload"])
        print("OwnCMD reset complete. Starting a new installation.")

    def clear_firewall(self):
        if not self.which("iptables"):
            return
        rules = [
            ("INPUT", "-s", subnet, "-j", "ASTER-HOST")
            for subnet in ("172.30.0.0/16", "172.31.0.0/16")
        ]
        rules += [
            ("DOCKER-USER", "-s", subnet, "-j", "ASTER-EGRESS")
            for subnet in ("172.30.0.0/16", "172.31.0.0/16")
        ]
        for rule in rules:
            while True:
                try:
                    self.execute(["iptables", "-C", *rule])
                except subprocess.CalledProcessError:
                    break
                self.execute(["iptables", "-D", *rule])
        for chain in ("ASTER-HOST", "ASTER-EGRESS"):
            try:
                self.execute(["iptables", "-S", chain])
            except subprocess.CalledProcessError:
                continue
            self.execute(["iptables", "-F", chain])
            self.execute(["iptables", "-X", chain])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo.")
    try:
        reset = Reset().preflight()
        reset.describe()
        if not args.dry_run:
            reset.apply()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Database URLs and config values are deliberately excluded from messages.
        raise SystemExit("Clean installation stopped: " + str(error)) from None
