# Community 1.0 validation

Checked on 2026-10-13 against the included source and production frontend build.

## Results

- Backend: **566 passed, 3 skipped**. The suite covers authentication, setup protection, invitations, role boundaries, secret encryption, CSRF/origin protection, usage accounting, task/runtime behavior and installer regressions. Eight framework deprecation warnings remain.
- Frontend unit tests: **32 passed**.
- Chromium end-to-end checks: owner setup, HTTP login, provider-key persistence, invitation signup, member restrictions, mobile layout and usage filters passed; no uncaught page errors.
- Next.js production static build completed. Integrity verification passed for **315 assets**.
- Shell syntax and Python compilation checks passed.
- Dependency snapshots: npm audit and pip-audit reported **zero known vulnerabilities** in the resolved frontend dependencies and backend lockfile, respectively. This is a point-in-time check, not a security guarantee.

## Test environment and limits

The backend suite used real PostgreSQL SQL through PGlite with pgvector and its wire-protocol adapter. This was necessary because this execution environment cannot switch to the native PostgreSQL service user. It does **not** validate native PostgreSQL multi-process concurrency or production deployment. The three skips concern two native Caddy checks and a restricted service-user filesystem check.

The browser tests used the actual API and built frontend on HTTP with a disposable database; provider model catalog responses were stubbed. No paid AI requests were made. A clean Ubuntu installation, systemd lifecycle, native PostgreSQL, live Caddy TLS, Docker/gVisor isolation, host firewall behavior and real provider calls still require validation on a dedicated supported server. This is a community preview, not a production certification or a complete penetration test.

Before deployment, run the native suite using `scripts/test_postgresql.sh`, install on a disposable dedicated server, run `owncmdctl smoke`, configure keys and run `owncmdctl smoke --live`. Confirm backup restoration, owner recovery, update rollback and network isolation for your host. The included CI workflow is supplied for a future repository; it has not been executed on a hosted CI service here.

## Security and behavior changes reviewed

- Removed credits, checkout/Stripe, SMTP, verification/reset email flows and SaaS administration modules. Usage and optional spending safeguards remain.
- Closed public registration; installer-token-protected first-owner setup and hashed, expiring, single-use invitations replace it.
- Enforced owner-only instance configuration and last-active-owner protection.
- Provider keys remain encrypted and write-only; clearing a key explicitly masks environment fallback. Optional keys fail with an actionable settings message when a dependent feature is used.
- Preserved session revocation, password hashing, CSRF/origin checks, workspace ownership and sandbox boundaries.
- Hardened invalid/oversized Content-Length handling, updated vulnerable frontend dependencies, removed credit-based provider gating and fixed upgrade previous-release tracking.
- Exercised non-HTTPS login and fixed invitation-fragment preservation plus secure random ID generation on HTTP LAN origins.

Existing SaaS deployments are deliberately rejected by the installer. No production customer-data migration has been tested or supplied.


## Linux portability follow-up (2026-10-13)

- Full regression run after adding capability checks, Debian 13 package selection, prepared-host mode and PostgreSQL layout discovery: **582 passed, 3 skipped**.
- After correcting systemd template expansion, the targeted portability/runtime/regression checks passed: **33 passed**, including the additional rendered-unit test.
- Shell syntax, Python compilation and the 315-asset frontend integrity check passed. The application UI/assets were not changed in this follow-up.
- The actual environment correctly fails the read-only host check because it has no running systemd, Docker or gVisor. No host installation was attempted here.
- Distribution selection and tool-layout logic were exercised using fixtures. Debian, Fedora, Arch, Rocky/Alma/RHEL and openSUSE were **not** booted or installed in this environment. Prepared-host capability acceptance is not production certification. OpenRC/runit and immutable hosts remain outside the native installer scope. See `LINUX.md` for exact prerequisites and service/firewall requirements.
