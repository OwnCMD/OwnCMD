# Security and data boundaries

Understand provider data flow, sandboxing, permissions and operational limits.

Applies to: Both

## Data flow

Self-hosting gives you control over your OwnCMD instance and stored data. Requests still send the necessary content to selected AI and search providers. Browser tasks contact external websites. Do not interpret self-hosting as offline model execution or a guarantee that data never leaves the server.


## Account protection

The source includes password hashing, hashed session tokens, HttpOnly/SameSite cookies, origin/CSRF validation and server-side access control. Secure-cookie behavior depends on HTTPS. Owners are trusted instance operators and can administer shared credentials and membership.


## Execution boundary

Generated code and model-selected actions are untrusted inputs. Workspaces use gVisor containers, limits, network policy and approval/input boundaries. The privileged host and broker remain part of the trusted computing base; the design is not a proof against all sandbox escapes.


## Your responsibilities

For Community, patch the OS and runtime, protect secrets and backups, limit exposed ports, use HTTPS on untrusted networks and test recovery. For either edition, review consequential output and approve sensitive actions only when you understand them.


## Claims and limitations

No SOC 2, ISO certification, regulatory compliance guarantee, audit certification or service-level agreement is asserted by this documentation. Review the actual service terms before supplying regulated data. The included security review is not a penetration-test certificate.


## Trace a request before deciding what to upload

Your conversation may include the prompt, relevant prior context, selected memory, document extracts and tool results. A model provider receives what is needed for the request. Web research can send a query to a search provider and read external pages. A browser task can interact with third-party sites. Self-hosting controls the OwnCMD host, not every destination involved in the task.

Before uploading confidential material, consider the configured providers and intended action. Do not treat a private conversation as a promise that no external processor is involved. Avoid putting production credentials into prompts or files when a narrower credential or manual sign-in step is sufficient.


## Separate content instructions from authorization

A web page, document or generated file can contain instructions that conflict with your task. Treat that material as untrusted content. When a task asks for an approval, inspect the destination and action yourself; an authoritative-looking page is not proof that you intended to send it data.

Use browser takeover for site-specific human input when available, and verify the site before entering credentials. Review generated scripts before running them outside the isolated workspace. The workspace boundary does not follow a downloaded script onto your personal computer.


## Protect the operational control plane

On Community, root access, the broker secret, the instance master key and Owner privileges are high-value capabilities. Store configuration with restricted permissions, keep backups private and patch the host. Never publish a diagnostic archive containing /etc/aster/config.env or real browser profiles.

The application account should not have general Docker access. Internal database and broker ports should remain inaccessible from the public network. Keep exact-origin and CSRF checks in place even for private HTTP deployments; transport protection and request-forgery protection solve different problems.


## Report a vulnerability privately

Security reports should describe the affected release, minimal reproduction and impact without including real user data. For this distribution, use the signed-in Cloud support channel with a subject beginning “Security report — Community” and category Bug. This is a private vulnerability-reporting route, not a promise of Community installation or usage support. Avoid posting exploit details publicly before the maintainers can assess them.

