# Troubleshooting by symptom

Find the next useful check for sign-in, models, workspaces, files and installation.

Applies to: Both

## Cannot sign in

Cloud: confirm the registration email was verified, then use the password-recovery flow if needed. Community: check that first-owner setup was completed or your invitation is valid; email recovery does not exist. An owner may have suspended the account. Do not keep guessing passwords against rate limits.


## A model is missing or unavailable

Check both the mode-specific model policy and provider configuration. Auto means the configured default, not a promise to route to whichever model seems best. A provider can reject a model because of account permissions, credit or upstream availability. See Models for the exact fallback boundary.


## Search or Work fails before starting

Community: ensure the necessary provider keys are configured in Instance settings. Cloud: check available credits and account limits. For code networking, review the effective policy rather than weakening the host firewall. Inspect the actual error before retrying.


## Browser is waiting for me

Open the browser preview and inspect the requested input or approval. Some websites need human login, CAPTCHA or other intervention. Provide input through the available takeover controls. Do not enter credentials into an unrelated conversation when the site is asking for them.


## A coding preview is blank

Confirm a server was started in the workspace, is still running, and is listening on the port used by the preview. Read terminal output for build errors. A local preview is not a public deployment and will not survive every runtime lifecycle unchanged.


## A file fails to upload or parse

Check supported format, file-size limits and available workspace capacity. PDF OCR has page and processing limits. Temporary Chat does not support document uploads. Archives need safe extraction in a workspace; an archive is not automatically a parsed document collection.


## A schedule did not run as expected

Check enabled state, timezone, next-run time, missed-run policy and history. Budget, model access, provider configuration or active-run limits can prevent completion. Human input may still be needed during a scheduled task.


## Community installation stops

Read the first failure and check the documented host requirements. Use --check-system before installation. Confirm PostgreSQL tools/pgvector, Docker/gVisor, disk space and supported firewall backend. Keep logs, but redact tokens, passwords and keys before sharing. Never bypass runtime checks or use destructive fresh installation as the first repair step.


## Use a reproducible diagnostic sequence

Record which edition and instance you are using, the exact action, the time and the full visible error. Try a minimal version of the same action with non-sensitive input. Change one variable at a time: testing a different model, provider and file simultaneously makes a successful retry difficult to interpret.

Separate page reachability from account access, and account access from task execution. If the page cannot load, investigate host/proxy connectivity. If sign-in fails, investigate account and origin. If sign-in works but Work fails, investigate keys, policy, capacity and the execution services.


## A saved setting appears not to change

Provider key fields intentionally return blank after saving because secrets are write-only. Check the configured status instead of assuming the key disappeared. A blank field on a later save preserves the value; explicit removal clears it.

If a configuration save reports a version conflict, another administrator may have changed the settings. Reload, inspect the current state and reapply only the intended edit. Do not disable concurrency checks or send repeated stale saves.


## A runtime fails after host maintenance

Check disk space and the status of Docker, PostgreSQL, the broker and worker. Review whether a firewall-manager reload removed the required isolation chains or a package upgrade changed PostgreSQL tool discovery. Prepared-host deployments require the same runtime checks as automatic installations.

Preserve gVisor and the firewall boundary while diagnosing. Switching to ordinary containers may make a task start while silently removing the expected isolation. Restore the intended runtime configuration and verify a local smoke test before enabling member workloads.


## Know where to take the evidence

Cloud users can open Help & support → My tickets → Create ticket. Include the time, steps, expected result and sanitized error. For an unavailable model, use the dedicated model-request guide and category Feature request.

Community has no provided support. Use the operational guides and source to investigate, and submit a reproducible public bug report where the source is hosted if you find a defect. Security issues belong in the private channel described by SECURITY.md. Never attach config.env, provider keys, session cookies or private browser profiles.

