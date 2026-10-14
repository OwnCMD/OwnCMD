# Linux compatibility

Automatic Debian/Ubuntu setup and the prepared-host path for other systemd distributions.

Applies to: Community

## Automatic package setup

Ubuntu 24.04, Ubuntu 26.04 and Debian 13 use the APT setup path. Other distribution names do not automatically receive guessed package commands. The installer selects package setup independently from its host capability checks.


## Other Linux distributions

Fedora, Arch, Rocky/Alma, RHEL and openSUSE can use --prepared-host after the operator installs the required dependencies. This is a capability-based path, not a claim of tested installation on each distribution. OpenRC/runit-only and immutable hosts do not have a native adapter in this release.


## Prepared-host prerequisites

- Python 3.12+ with venv and ensurepip; rootful Docker Engine and docker.service.
- Full gVisor installation including companion binaries; Caddy and caddy.service.
- PostgreSQL 14+ with matching server/client tools, matching pgvector files, a postgres OS account, and an initialized local cluster managed as postgresql.service.
- GNU utilities, Bash, util-linux, user-management commands, iptables, Poppler and Tesseract with English data.
- Administrative PostgreSQL peer access through /var/run/postgresql on port 5432; SCRAM password access on loopback for application users.

## Verify then install


```text
bash install.sh --prepared-host --check-system
sudo bash install.sh --prepared-host
```

## Versioned PostgreSQL paths

Tool discovery covers Debian, RPM/PGDG, SUSE and standard paths. Mixed-major tools are rejected. Select the intended complete tool directory explicitly when needed:


```text
sudo env OWNCMD_PG_BINDIR=/usr/pgsql-18/bin bash install.sh --prepared-host
```

## Firewall and policy requirements

Docker must expose DOCKER-USER through its iptables backend; iptables-nft compatibility is acceptable, but the separate native nftables backend is not supported by these rules. Preserve SELinux/AppArmor and configure narrowly scoped policy where required. Review docs/LINUX.md in the release for detailed service, Caddy default-file and authentication requirements.


## CentOS and related systems

CentOS is not an automatic package-install target in this release. A systemd-based CentOS-family host must satisfy the prepared-host checks, including Python 3.12+, the kernel requirement, matching PostgreSQL/pgvector tools, Docker and the complete gVisor runtime. A distribution name alone does not establish compatibility.

Do not assume a Rocky, AlmaLinux, RHEL or CentOS Stream server has the same package names, PostgreSQL service unit or security policy as Ubuntu. Prepare the supported packages for that exact host, then run the read-only check. This is an operator-prepared path, not a claim that every CentOS release has been tested.


## PostgreSQL compatibility is a complete toolchain

The application needs a running local database and matching tools for provisioning, test clusters and backups. Finding psql alone is insufficient. The selected directory must contain compatible initdb, postgres, pg_ctl, psql, createdb and pg_dump programs. Install pgvector for the same server major.

When several PostgreSQL majors exist, explicitly select the intended complete directory with OWNCMD_PG_BINDIR. That selection is carried into service and CLI execution so a backup does not silently use a different client from an interactive shell. The installer rejects incomplete or mixed-major sets rather than guessing.


## Prove the deployment after host preparation

1. Verify the canonical PostgreSQL, Docker and Caddy services exist and survive a reboot.
2. Confirm local postgres peer authentication and application loopback password authentication; never expose the database publicly.
3. Check that Docker provides DOCKER-USER through its iptables backend. An iptables-nft compatibility command is different from Docker’s native nftables backend.
4. Run the installer without disabling SELinux, AppArmor or the sandbox firewall. Resolve specific policy denials narrowly.
5. Exercise a browser task and a coding task, then validate their network restrictions.
6. Test backup and restore on an isolated host and record the exact distribution, kernel and package versions.

## When the host is outside this installer’s scope

OpenRC/runit-only systems do not have the systemd service adapter used here. Ordinary containers and immutable host layouts are also outside the provided installation path. Do not replace failed capability checks with a forced success or substitute a standard container runtime for gVisor. Choose a compatible dedicated host or contribute a tested adapter.

