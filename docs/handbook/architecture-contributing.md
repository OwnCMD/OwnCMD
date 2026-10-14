# Architecture and contributing

Find the readable source, rebuild the frontend and contribute safely.

Applies to: Community

## Source map

- app/main.py: API, sessions, conversations and streaming.
- app/chat.py, worker.py, providers.py and tools.py: model/tool execution.
- app/broker.py, sandbox/ and firewall.sh: isolated execution and network boundaries.
- app/documents.py, skills.py and scheduling.py: documents, skills and schedules.
- frontend/: React/Next.js source; app/static/: generated production assets.
- scripts/: deployment helpers, integrity checks and tests.

## Development workflow

The Community archive includes readable source, an Apache 2.0 license and third-party notices. Use Python 3.12+ and Node 22+ for the documented development workflow. Build frontend source instead of editing generated static files.


```text
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cd frontend
npm ci
npm test
npm run build
cd ..
bash scripts/test_postgresql.sh "$PWD/.venv/bin/python"
python3 scripts/verify_frontend.py
```

## Test database safety

The native runner creates a disposable PostgreSQL cluster with pgvector. Tests reject database names that do not begin with aster_test. Never use production database credentials for tests. Live smoke checks are a separate, explicit operation.


## Contribution boundaries

Keep server-side permissions, parameterized SQL, transaction invariants, secret encryption and runtime isolation intact. Do not introduce a fallback to ordinary containers. Include focused regression coverage for changed behavior and document target-host verification.


## Project status

Community 1.0 is a self-service distribution; we do not provide Community support. The download includes contribution guidance; a public repository URL has not been configured for this website. No fabricated GitHub link or support SLA is supplied.


## Follow one request through the system

The frontend sends authenticated API requests to the application. The API checks ownership, origin and policy before reading or changing state. Chat and worker orchestration call provider and tool adapters. Code and browser execution pass through an authenticated privileged broker into gVisor environments rather than giving the application direct Docker access.

Persistent records live in PostgreSQL, with workspace storage and encrypted checkpoints managed by their dedicated modules. Provider credentials are read from encrypted live settings, allowing Owner changes to affect new requests without restarting the worker. Preserve these boundaries when implementing a feature.


## Prepare a focused contribution

1. Read CONTRIBUTING.md and find the module that owns the behavior. Keep generated assets separate from their source.
2. Write a concise issue or pull-request description explaining the user-visible problem and intended behavior.
3. Make the smallest coherent change and add regression coverage for a real failure or invariant.
4. Use the disposable PostgreSQL test runner; never provide production database credentials.
5. For a frontend change, run its tests, rebuild the static export and verify the generated manifest.
6. Document any deployment, policy or data-migration effects and the validation you actually performed.

## License and contribution terms

OwnCMD Community 1.0 is Apache-2.0 licensed. LICENSE contains the operative terms and NOTICE records attribution. Third-party notices under licenses/ retain their original terms. Earlier MIT distributions retain their existing grants; the prior project notice is kept separately.

Contributions intentionally submitted for inclusion are provided under Apache License 2.0 unless explicitly stated otherwise, consistent with its contribution clause. Do not contribute code or assets you lack permission to distribute. Preserve upstream notices and identify material modifications to third-party work.


## Package a release from the source tree

scripts/package_release.py verifies the built frontend and packages readable source with explicit executable permissions. It excludes dependency caches, local environments, Git metadata, encrypted state, database dumps and nested ZIP files. Write the output outside the source tree.

The repository includes CI for backend tests, frontend tests and a static build. Those checks are useful regression evidence; they do not prove a clean installation on every Linux distribution. Record native-host installation and runtime-isolation results separately.


## Community participation and support

Use reproducible issues for software defects and small pull requests for improvements. Include the release version, relevant platform details and a minimal sanitized reproduction. For documentation changes, explain the workflow that was unclear and verify any commands against the current source.

Community is self-service and has no provided support or response-time commitment. Cloud account and billing questions belong in the signed-in Cloud support flow. Report security defects privately using SECURITY.md rather than publishing exploit details in an ordinary issue.

