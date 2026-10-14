# OwnCMD Community

Self-hosted AI chat and a workspace that can browse, write files, run code and schedule work. Bring your own OpenRouter and Exa keys. Conversations, credentials and files stay in your instance; selected AI and search providers receive the content needed to process requests.

**Community 1.0.1.** Derived from the supplied OwnCMD v27.3.2 SaaS installer. Read [validation](docs/VALIDATION.md) before production use.

## Install on a dedicated Linux server

Automatic package setup: Ubuntu 24.04 / 26.04 and Debian 13. Other systemd-based Linux distributions can use the operator-prepared dependency mode described in [Linux installation](docs/LINUX.md). Requires Linux 5.6+, Python 3.12+, x86-64 or ARM64, at least 4 GB RAM (8 GB recommended), and 18 GB free disk for runtime builds. Native systemd, Docker and gVisor are required. This is not an ordinary Docker Compose deployment: the privileged broker provisions isolated execution environments.

```bash
unzip owncmd-community.zip
cd owncmd-community
bash install.sh --check-system
sudo bash install.sh
```

On automatic APT targets, the installer provisions PostgreSQL + pgvector, gVisor, the sandbox image, Caddy and systemd services. Review `install.sh` before running: it installs packages, configures Docker runtimes, restarts Docker and configures sandbox firewall rules. Use a dedicated host.

1. Enter a hostname or IPv4 address, or press Enter for `localhost`.
2. Choose optional HTTPS. HTTP needs no domain and no certificate. `localhost` binds only to loopback. For remote setup, use a private server IP with access over a trusted VPN/LAN, or use the localhost tunnel described below.
3. API keys are **optional**. Press Enter for either key to skip it.
4. Open the URL printed by the installer. Enter its private setup token, display name, email identifier and password to create the first owner.
5. Go to **Instance settings → Providers** to add, replace or remove provider keys at any time. No restart is needed. OpenRouter powers models; Exa powers search/page retrieval.

The default localhost origin is `http://localhost`, on port 80. For an SSH tunnel without changing the origin, forward local port 80 to server port 80 (may require local administrator privileges), then open `http://localhost`. The installer currently accepts a hostname/IPv4 on standard ports only; custom reverse proxies and ports require manual origin/proxy configuration.

HTTP sends credentials and content without transport encryption. Use it on a trusted private network; enable HTTPS for public access. HTTPS and HTTP both enforce exact-origin writes, CSRF tokens and HttpOnly session cookies. Secure random IDs work on non-HTTPS LAN origins.

For other systemd distributions, prepare the dependencies in [docs/LINUX.md](docs/LINUX.md), then run `sudo bash install.sh --prepared-host`. OpenRC/runit hosts do not yet have a service adapter. No per-distribution live deployment certification is claimed.

## Accounts and roles

- **Owner:** configure shared provider keys, models, resource limits and network policy; invite members; change roles; suspend access; revoke sessions. At least one active owner must remain.
- **Member:** own conversations, files, memory, skills, schedules and usage. Cannot configure instance secrets or administer accounts.
- Public registration is closed. Owners create one-use, email-bound invitation links valid for 24 hours and share them manually. No messages are sent by OwnCMD.
- Email is only a login identifier. No SMTP, email verification, reset codes, payment invoices or transactional email service exists in Community.
- Reset forgotten passwords from the server: `sudo owncmdctl reset-password user@example.com`. This revokes existing sessions. Signed-in users can change their password under Settings.
- Internal database/API role values remain `admin` and `user`, mapped to Owner and Member in the UI. The retained `/api/admin/*` routes are owner-only instance configuration, not the SaaS administration product.

## Usage, not credits

Usage records include requests, model IDs, tokens, provider costs and runtime seconds. No wallet, signup credit, checkout, top-up, Stripe webhook or markup exists. All model services, including title generation, are recorded at provider cost. Estimates can be reconciled when a provider settles its bill; your provider invoice is authoritative.

Local browser/code runtime cost defaults to zero. Operators may optionally set `ASTER_BROWSER_COST_PER_HOUR` / `ASTER_CODE_COST_PER_HOUR` to estimate infrastructure allocation. No money is collected. Daily/per-schedule spending limits remain optional safeguards; zero daily spend limit means unlimited. They are application estimates, not provider-enforced hard billing caps.

## Operation

```bash
sudo owncmdctl status
sudo owncmdctl logs
sudo owncmdctl restart
sudo owncmdctl backup
sudo owncmdctl smoke          # checks local runtime without paid model calls
sudo owncmdctl smoke --live   # requires both provider keys; makes real paid requests
sudo owncmdctl reset-password owner@example.com
```

Back up both the database/workspaces and `/etc/aster/config.env` securely off-server. Without `ASTER_MASTER_KEY`, encrypted content cannot be recovered. Never commit that file. Service/data paths retain `/opt/aster`, `/etc/aster`, `/var/lib/aster` and `aster-*` for compatibility with the tested runtime scripts. `owncmdctl` aliases `asterctl`.

Updates: back up first, unpack a new Community release, then rerun `sudo bash install.sh`. Configuration and data are preserved. The installer rejects existing SaaS configuration: deploy Community on a separate host. An in-place SaaS-to-Community migration is intentionally not implemented or claimed. `--fresh-install` is destructive and requires the existing interactive reset flow; do not use it as an update command.

## Source and contribution

This archive contains actual editable files, not a base64 payload. `app/` is the Python API/worker; `frontend/` is React/Next.js source; `sandbox/` is the execution runtime; `scripts/` handles deployment and tests. Prebuilt `app/static/` assets are included so a server installation does not need Node. Edit frontend source and rebuild instead of editing generated assets.

See [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/ARCHITECTURE.md), [SECURITY.md](SECURITY.md) and [validation](docs/VALIDATION.md). The project is licensed under [Apache License 2.0](LICENSE); see [NOTICE](NOTICE) for attribution. Third-party components retain their own licenses. Community is self-service: we do not provide Community support. Cloud support is available after signing in at https://console.owncmd.com.

Read the [complete user and operator handbook](docs/handbook/README.md), [release notes](CHANGELOG.md) and [contribution guide](CONTRIBUTING.md).
