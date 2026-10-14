# Security

## Private vulnerability reports

Sign in at https://console.owncmd.com and open **Help & support → My tickets → Create ticket**. Choose **Bug**, start the subject with **Security report — Community**, and include the affected version, impact and a minimal reproduction using synthetic data. Submit with **Submit ticket**. Keep the ticket reference for follow-up replies.

This channel accepts security reports about Community; it does not provide general Community installation or usage support. No response-time or security-fix guarantee is offered. Do not publish exploit details or include API keys, passwords, cookies, private browser profiles or real user data. Community 1.0 is the current release line; use the latest available patch within it and report the exact revision.

## Trust model

Owners control instance-wide paid provider credentials, network policy and membership. Treat them as trusted operators. Members cannot administer secrets and are restricted to their own conversations/files. The application user cannot directly access Docker; the loopback broker is privileged and authenticates requests with an installer-generated secret. A compromised host or privileged broker is outside tenant isolation guarantees.

Model content and generated code are untrusted. Code/browser workloads remain in resource-limited gVisor containers with the existing network isolation, checkpoint encryption and approval controls. This review is not a penetration test or proof of sandbox escape resistance.

## Controls in this release

- Installer-secret-protected, one-time owner bootstrap; serialized creation avoids two owners claiming a fresh instance concurrently.
- Random, hashed, single-use invitations bound to a login identifier and expiry; manual revocation, rate limiting and issuer-role checks.
- Argon2id passwords; hashed session tokens; HttpOnly/SameSite cookies; Secure flag on HTTPS.
- Exact Origin and CSRF checks on mutations; owner authorization for instance settings; last-owner protection.
- Encrypted stored provider keys; masked status only; credential changes never appear in audit payloads. Explicit removal masks environment keys.
- Stripe, registration verification and email queues/routes are removed. No forgotten-password endpoint that can be abused for email enumeration remains.
- Frontend dependency updates and a cryptographic UUID fallback for HTTP LAN use.
- CSV formula-injection escaping and existing file/preview ownership restrictions retained.

## Operator responsibilities

Use HTTPS on untrusted networks, firewall public ingress, patch the OS/Docker/gVisor, use limited provider keys and provider-side budgets, and back up the encryption key separately. Do not expose PostgreSQL, port 8000, or the broker's port 8091 publicly. Configure no wildcard trusted proxy addresses. Keep owner access limited.

No broad security guarantee is made: read `docs/VALIDATION.md` for tested and untested boundaries. Live server installation, TLS issuance, native concurrency, sandbox escape resistance, load testing and external provider behavior require independent validation.
