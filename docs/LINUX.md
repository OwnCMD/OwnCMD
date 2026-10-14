# Linux installation and portability

The installer now selects package automation independently from host capability checks. It does not assume that every Linux system is Ubuntu. This release still needs a **systemd host**, Linux kernel **5.6+**, **x86-64 or ARM64**, Python **3.12+**, 4 GB RAM (8 GB recommended), and 18 GB free build space. A dedicated host is required because installation configures Docker runtimes, service units and sandbox firewall rules.

## Installation paths

| Host | Package setup | Deployment validation |
| --- | --- | --- |
| Ubuntu 24.04 / 26.04 | Automatic APT setup | Original target; full live-host validation remains outstanding |
| Debian 13 | Automatic APT setup | New path; target-host validation required |
| Fedora, Arch, Rocky/Alma, RHEL, openSUSE and other systemd distributions | Operator prepares dependencies; common installer then configures OwnCMD | Capability-based path; no claim of completed per-distribution installation testing |
| Older distributions with Python below 3.12 | Prepare a supported `python3` and matching dependencies first | Version check blocks incompatible Python |
| Alpine/OpenRC, runit-only, immutable hosts, ordinary containers | No native service adapter in this release | Not supported by this installer |

This is broader Linux portability, **not a claim that every Linux distribution works automatically**. No sandbox isolation is removed to expand compatibility.

### Read-only prerequisite report

```bash
bash install.sh --check-system
```

This command does not require root, take the installation lock, install packages, change services or reset data. On automatic APT hosts it reports base requirements; on other hosts it also checks the installed dependency commands and required systemd units. Missing prerequisites are reported together. A successful report is not a substitute for the runtime checks performed during installation.

### Ubuntu and Debian

```bash
sudo bash install.sh
```

The installer retains signed gVisor repository installation and PostgreSQL-major-specific pgvector packages. API keys remain optional; domain and TLS remain optional. Debian 12's default Python is too old for this installation path; prepare a supported host rather than changing system Python blindly.

### Other systemd distributions

Use your distribution's supported repositories to install and initialize these dependencies:

- Python 3.12+ as `python3`, with `venv`, `ensurepip` and functioning TLS certificates.
- Rootful Docker Engine (`docker`, `dockerd`) with a `docker.service` unit. Podman's Docker-compatible CLI is not a substitute.
- The full gVisor release: `runsc` **and its companion binaries**, kept together. Follow the [official installation guide](https://gvisor.dev/docs/user_guide/install/), including checksum verification. This mode does not download or update gVisor automatically.
- PostgreSQL 14+ server and matching client tools (`initdb`, `postgres`, `pg_ctl`, `psql`, `createdb`, `pg_dump`), the `postgres` OS account, and matching pgvector extension files. Use a supported PostgreSQL major for your distribution. An initialized local cluster must be managed by `postgresql.service` (supply a proper unit/alias if your vendor uses a versioned name, and enable the canonical unit at boot).
- Caddy and `caddy.service`; GNU core utilities; Bash; util-linux (`flock`, `runuser`, `findmnt`, `mount`, `umount`); user-management tools including `useradd` and `nologin`.
- `iptables`; Poppler (`pdftotext`, `pdftoppm`); Tesseract with English language data.

Before installation, inspect `/etc/caddy/Caddyfile` if it exists. The installer refuses to overwrite an unowned configuration. On a new dedicated host, preserve the unused packaged default under a different filename before proceeding; do not remove a configuration serving other sites.

Configure the local PostgreSQL cluster to accept administrative peer authentication for the `postgres` OS user via `/var/run/postgresql` on port 5432, and password authentication (SCRAM-SHA-256) on loopback for application users. PostgreSQL must not listen publicly. On a **new, empty cluster**, `initdb --auth-local=peer --auth-host=scram-sha-256` supplies suitable authentication defaults; initialize under the `postgres` user in the directory expected by the distribution's unit. Never run initdb over existing data. Consult [PostgreSQL initdb documentation](https://www.postgresql.org/docs/current/app-initdb.html) and your distribution's service documentation.

The installer deliberately does not rewrite an existing database's authentication rules. Check local administrative access first:

```bash
sudo -u postgres psql -X --no-password -h /var/run/postgresql -U postgres -d postgres -c 'SELECT 1'
bash install.sh --prepared-host --check-system
sudo bash install.sh --prepared-host
```

For versioned client directories, specify the complete matching tool directory explicitly:

```bash
sudo env OWNCMD_PG_BINDIR=/usr/pgsql-18/bin bash install.sh --prepared-host
```

Discovery otherwise searches Debian, RPM/PGDG, SUSE and ordinary `/usr/bin` layouts. Mixed-major or incomplete toolsets are rejected. The selected path is retained for service processes and CLI backups. For hosts with multiple majors, use the override to select the intended server major. Install pgvector for that major before proceeding; the installer creates a disposable local test cluster and exercises the actual extension before activating the application.

### Firewalls and host security policies

Docker must use its **iptables firewall backend**, providing the `DOCKER-USER` chain. An iptables command using the nft compatibility layer (`iptables-nft`) is compatible; Docker's separate native nftables backend is not supported by these rules. The installer checks for the chain before proceeding. Follow Docker's [firewall documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/) when configuring the daemon.

Do not disable SELinux, AppArmor or the host firewall to make a check pass. Distribution-specific policies may need to permit the documented service paths and Caddy's loopback API connection. Review denials and add narrowly scoped policy through the distribution's supported tools. Host firewall reloads must preserve/reapply OwnCMD's isolation chains. Firewall-manager integration on each target host is part of deployment validation; do not expose the instance before confirming it.

The common installer still verifies gVisor execution, the sandbox image, browser startup, network settings, workspace mounts and application health. It fails when a requirement is missing; it never substitutes ordinary containers for gVisor.

## Adding distribution support

`scripts/linux_host.py` owns read-only detection and PostgreSQL tool discovery. `install.sh` owns mutation ordering and package setup; `--prepared-host` skips all package-manager calls, including pgvector installation. Contributions adding another automatic package adapter should test clean installation, interrupted retry, upgrade, backup/restore, reboot, unprivileged services, database major selection, SELinux/AppArmor and sandbox network isolation on that distribution. Do not use `ID_LIKE` alone to assume identical package names or service layouts.
