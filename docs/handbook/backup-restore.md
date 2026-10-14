# Backups and disaster recovery

Preserve the database, workspaces and encryption keys together.

Applies to: Community

## Create a backup


```text
sudo owncmdctl backup
```

## What must be retained

Keep database/workspace backups and a protected copy of /etc/aster/config.env off the server. The configuration includes encryption material and credentials. Without ASTER_MASTER_KEY, encrypted content may not be recoverable. Protect backups as sensitive data.


## Plan a restore before an incident

This release does not supply a verified one-click restore wizard. On an isolated host, reinstall a compatible release, restore the database using matching PostgreSQL tools, restore the required data/workspace files and protected configuration, then verify ownership and permissions before starting services. Follow the structure of your actual backup output rather than assuming a generic tar layout.


## Verify recovery

1. Record the application version, PostgreSQL major and backup time.
2. Keep an encrypted off-host copy and its recovery material accessible to authorized operators.
3. Restore into an isolated test environment.
4. Check sign-in, conversation history, files, encrypted provider settings and representative work tasks.
5. Record the result and repeat after material upgrades.

## Portability

The installer preserves the selected PostgreSQL client directory for service and CLI execution. Restoring across PostgreSQL majors or application schema changes still requires compatibility review; a successful backup command alone does not prove restorability.


## What the backup command actually writes

The backup creates a timestamped aster-YYYYMMDDTHHMMSSZ.tar.gz file inside /var/lib/aster/backups. It contains postgres.dump plus snapshots and uploads directories when they exist. The output file is set to mode 0600. The command prints the path and explicitly reminds you that encryption keys are not inside the archive.

This is not a complete host image. It does not automatically include /etc/aster/config.env, operating-system packages, external provider accounts or unrelated web-server configuration. Do not assume that an archive existing on the same disk protects you from disk loss.


## Create a consistent recovery point

Choose a maintenance window and stop new user activity while making a coordinated backup. Database dump and file collection are separate operations; copying a busy instance can capture changes at different moments. Record the exact release, PostgreSQL major, backup time and configuration version together.

Store the archive and protected configuration off-host with restricted access. Keep an additional recovery copy of encryption material under the control of authorized operators. Encrypt backup storage: database content, uploads and browser state may be sensitive even when some application fields are encrypted.


## Inspect without restoring over production


```text
sudo owncmdctl backup
# Use the exact archive path printed above to inspect its entries.
# The archive should contain postgres.dump and any stored snapshots/uploads.
```

## A recovery rehearsal sequence

1. Provision an isolated compatible host using the same Community release and suitable PostgreSQL/pgvector versions. Keep it inaccessible to ordinary members.
2. Stop application and worker activity before restoring state. Preserve the test host’s initial state separately.
3. Inspect the archive and restore the database dump using matching PostgreSQL tooling. Restore snapshots and uploads into the configured data directory with the expected ownership.
4. Restore the protected application configuration and original master key. Check origin and host-specific settings before starting services.
5. Prevent restored schedules from making unintended external requests during the rehearsal; keep outbound access controlled until you have reviewed them.
6. Start dependencies and application services, check local health, then sign in and verify conversations, files, encrypted settings and representative tasks.
7. Record what worked, how long recovery took and which data was unavailable. Keep the recovery host isolated until you intentionally promote or discard it.

## Why there is no generic restore command here

The CLI supplies backup, not a one-click restore. Database ownership, service paths, origin and PostgreSQL major vary with the target host. A generic command that drops a database could destroy an unrelated instance. Use an isolated rehearsal and a reviewed procedure for your deployment instead of trying unverified destructive commands during an incident.

