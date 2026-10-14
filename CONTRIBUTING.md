# Contributing

Use small pull requests with a clear problem statement, behavior changes and tests. Do not include credentials, real customer data, browser profiles or generated installation configuration.

## Development

Use Python 3.12+ and Node 22+ (the frontend requires Node >=20.9). Install the pinned backend dependencies in a virtual environment. A disposable native PostgreSQL installation with pgvector is needed for the full test suite.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cd frontend
npm ci
NEXT_TELEMETRY_DISABLED=1 npm run build
npm test
cd ..
bash scripts/test_postgresql.sh "$PWD/.venv/bin/python"
python3 scripts/verify_frontend.py
```

The PostgreSQL runner creates and destroys its own temporary cluster; tests refuse a database whose name does not begin `aster_test`. Never point tests at production. Provider/broker calls in unit tests use deterministic fakes. Live provider and gVisor checks are separately run by the installer/operator.

`frontend/app` contains page styles and entry points; `frontend/components` contains UI components; `frontend/lib` contains state-free utilities. `scripts/export_frontend.py` copies the static build and generates `frontend-manifest.json`. Include that output in release archives. Do not edit `app/static` manually.

Format Python with Black; format JS/JSX/JSON/CSS with the pinned frontend Prettier. Keep explanatory comments around trust boundaries, write transactions, lock ordering, encryption and recovery. Avoid comments that merely restate an assignment.

## Change boundaries

- Enforce ownership/roles on the API, never only in UI.
- Use parameterized SQL and the shared short write transaction for account/task invariants. Do not perform provider calls inside a database write transaction.
- Never add a fallback from gVisor to ordinary containers.
- Protect host metadata and private addresses; preserve sandbox resource limits and approval boundaries.
- Do not reintroduce SaaS credits, SMTP, paid feature gating or open public signup.
- Provider secrets are write-only in the UI. Blank input preserves a key; explicit removal masks environment fallback.
- Recheck frontend security advisories after dependency changes, rebuild Monaco as well as Next.js, and run HTTP-origin browser checks.

## Contributions and review

Submit a focused pull request in the repository hosting this source. Explain the problem, resulting behavior, tests performed and remaining validation limits. Maintainers review changes before merging; no response-time commitment is offered. Community is self-service and does not include provided support.

By intentionally submitting a contribution for inclusion, you provide it under Apache License 2.0 unless you explicitly state otherwise, consistent with section 5. Submit only work you may distribute. Preserve third-party notices and identify modifications to third-party code. No separate contributor agreement is required by this project.

For vulnerabilities, follow [SECURITY.md](SECURITY.md). For ordinary defects, use the bug-report issue template with sanitized reproduction steps. Be respectful and specific in reviews; focus criticism on the work, never on the person.

## Linux portability

Read [docs/LINUX.md](docs/LINUX.md) before adding distribution adapters. Keep detection read-only and keep all sandbox gates active in prepared-host mode. Tests in `tests/test_linux_host.py` cover package selection, PostgreSQL tool compatibility and safe rejection. Target-host installation tests are still required for each new distribution.

## Community browser regression checks

After rebuilding the frontend, install Playwright in your development virtual environment and install its Chromium browser (`python -m playwright install chromium`), or set `OWNCMD_BROWSER_BINARY` to an existing Chromium executable. Provision an **empty disposable** PostgreSQL database with pgvector whose name begins `aster_test`. Export `ASTER_DATABASE_URL` for that database, `ASTER_DATA` for a temporary directory, a new Fernet `ASTER_MASTER_KEY`, a test `ASTER_BROKER_KEY`, `ASTER_ORIGIN=http://127.0.0.1:8765` and `OWNCMD_SETUP_TOKEN=browser-test-token`.

Run `.venv/bin/python scripts/community_browser_checks.py` from the source root. The runner starts and stops its own loopback fixture server, uses the real app/session/CSRF APIs and substitutes a deterministic model catalog. It creates test accounts and raw-cost records; no paid provider request is submitted. Do not run it against existing application data. Port 8765 must be free. Screenshots and server logs go to `test-results/community` (or `OWNCMD_BROWSER_OUTPUT`), which release packaging excludes. The script covers responsive settings, account actions, model persistence and Usage/CSV cost consistency.
