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

## Community UI 1.0.1 (2026-10-14)

This update changes the Community application, not the marketing site. The following checks were rerun against the release source and rebuilt assets:

- **21 focused backend tests passed**, covering raw provider costs, reconciliation, free default runtime allocation, date-range switching, rate cards, setup/invitations, permissions, key handling and last-owner protection. A new rate-card regression verifies that a legacy multiplier cannot change displayed provider prices.
- **32 frontend tests passed**. Production build and integrity verification passed for **315 assets**. Python compilation and installer shell syntax passed.
- Chromium exercised actual HTTP APIs: first-owner setup; write-only provider-key replacement; invitation signup; member model overrides; role promotion/demotion; cancellation, suspension and restoration; instance model selection and saved Auto defaults; custom Usage dates; model filters; sorting; CSV export and provider rates.
- A provider cost of **$0.125** remained **$0.125** in the dashboard and filtered CSV. Adding a **$0.025** title operation produced **$0.15** total. No wallet/top-up controls were present.
- Browser flows and layout checks passed at **320, 390, 768 and 1440 pixels**. Visual review caught and corrected squeezed advanced filters on phones; regression checks now assert that these controls do not overlap. Member identity and status also use separate rows on phones to prevent squeezed names. Light and dark rendering were inspected. No uncaught browser page errors occurred.
- Account role/access actions use persisted member policy rather than implicitly saving draft model edits. Member inheritance uses the saved instance policy.

These are focused regression results, not a new full-suite or penetration-test claim. The backend/browser database used disposable PGlite with pgvector and its socket multiplexer. Native PostgreSQL concurrency, clean Linux installation, systemd/gVisor/Caddy lifecycle and paid provider requests were not retested here; the deployment limits above still apply. Run the native PostgreSQL suite and host smoke checks before rollout. Browser regression source is included in `scripts/community_browser_checks.py`; it refuses non-test databases and occupied fixture ports.
