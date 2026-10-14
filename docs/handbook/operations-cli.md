# Services and command line

Inspect health, logs, services and local or paid smoke tests.

Applies to: Community

## Common commands


```text
sudo owncmdctl status
sudo owncmdctl logs
sudo owncmdctl restart
sudo owncmdctl smoke
```

## Service layout

The installation retains aster-* service names and /opt/aster, /etc/aster and /var/lib/aster paths. owncmdctl aliases asterctl. Core services include the API, privileged broker, worker, restricted package proxy and firewall service, alongside PostgreSQL, Docker and Caddy.


## Local versus live checks

The ordinary smoke command checks the local runtime without paid model calls. The explicit --live variant requires provider keys and makes actual provider requests that may incur charges.


```text
sudo owncmdctl smoke --live
```

## Troubleshoot a stopped service

Use status first, then logs to find the earliest failure. Verify database availability, protected configuration, available disk and the required runtime. Restarting repeatedly without addressing the error can obscure the first useful diagnostic.


## Least privilege

The application runs as the aster OS user. The broker is privileged and uses its own authentication secret. Do not give the application account general Docker access as a workaround.


## Read status and logs together

owncmdctl status prints the configured URL and checks PostgreSQL, the API, broker, first worker and Caddy service state. It is a quick operational summary, not an exhaustive health certification. A service marked active can still fail a particular request because of database, upstream or runtime errors.

owncmdctl logs reads the latest 100 journal lines for the API, first worker and broker. Look for the earliest meaningful failure and correlate it with the user’s task time. This command does not include every Caddy or Docker message; inspect the corresponding service journal when those components are implicated.


## Collect focused diagnostics


```text
sudo owncmdctl status
sudo owncmdctl logs
sudo journalctl -u caddy -n 100 --no-pager
sudo journalctl -u docker -n 100 --no-pager
sudo owncmdctl smoke
```

## Understand restart scope

owncmdctl restart restarts the API, broker and first worker. It is not a host reboot and does not restart every dependency. Running work may be interrupted. Coordinate with members and collect the error first so a restart does not replace the evidence you need.

If a dependency is down, address that dependency and read its journal. Repeatedly restarting the application cannot repair a full disk, broken database authentication or a missing gVisor binary. Provider-key changes made through the panel do not require this command.


## Other maintenance commands

owncmdctl models inspects model-related operation through the application configuration. The CLI also retains historical accounting names such as billing-pending and reconcile-usage; in Community these concern usage estimates and reconciliation, not a credit wallet. Do not manually reconcile a cost without evidence from the provider.

create-admin and grant-admin are recovery/administrative operations corresponding to the Owner role. Their internal names do not reintroduce the SaaS administration dashboard. Use the panel for normal membership management and protect root access to the host.


## Keep diagnostics safe to share

Before attaching logs to any report, remove API keys, cookies, authorization headers, database URLs with passwords and user content. Keep timestamps, the exact service name, release version and the minimal failing operation. Community has no provided support; reproducible public bug reports should not contain private workspace data.

