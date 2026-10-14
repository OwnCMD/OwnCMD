# Updates, retries and fresh installation

Update Community safely and understand the destructive reset boundary.

Applies to: Community

## Normal update

Back up first. Unpack the new Community archive, review its documentation and rerun the installer using the appropriate automatic or prepared-host mode. The installer preserves configuration and data, builds the runtime and checks the new release before activation.


## Failure handling

A previous-release path is retained where a rollback is safe. Database cutover boundaries can require services to stop rather than revert to a release that might write incompatible data. Read the displayed failure instructions; do not assume every failed update has automatically restored a running instance.


## Fresh installation is destructive

--fresh-install erases the existing local OwnCMD installation, including backups and keys, through an interactive confirmation flow. It is not an update or routine retry flag. Preview its reset scope first:


```text
sudo bash install.sh --fresh-install --dry-run
```

## Cloud-to-Community migration

The Community installer rejects an existing non-Community configuration. Deploy Community separately. An in-place SaaS database conversion is not supplied or tested; do not remove the edition guard to force migration.


## Before applying a release

1. Read the release notes and validation boundaries; note any database or runtime changes.
2. Check available disk for a new application release, runtime image and a fresh backup.
3. Create an off-host backup of state and protected configuration, and verify that the recovery material is accessible.
4. Tell members about the maintenance window and avoid starting new long-running tasks.
5. Unpack the new release into a separate source directory and inspect the installer changes.

## Apply and verify

Run the normal installer with the same appropriate automatic or prepared-host path. Do not copy new Python files over an active release by hand; installation orders configuration, database work, runtime checks and activation. Preserve the edition guard and read any failure instructions.

After success, check status and local smoke tests. Verify sign-in, a conversation, a file download, an encrypted provider setting and a small Work task. Review scheduled work and usage after service recovery. Keep the previous recovery point until you have enough evidence that the new release operates correctly.


## What rollback does and does not mean

The installer can retain a previous application release where reverting is safe. That is different from restoring an entire database and file snapshot. A migration or database cutover can make an older application unsafe to run against newer state. If the installer stops services after a failed cutover, follow that boundary rather than manually forcing the old release online.

When a full restore is required, use the coordinated backup from before the upgrade and test it on an isolated host first. Restoring only application code cannot recover lost files or reverse every schema change.


## Use reset only for an intentional new instance

The dry-run reset displays what a fresh installation would remove. Review it on the intended machine and ensure that off-host backups exist before considering the actual reset. Local backups are inside the destructive boundary. Encryption keys removed by reset cannot be reconstructed from encrypted database content.

Routine configuration changes belong in the Owner panel, normal password problems belong in account recovery, and interrupted installation belongs in the normal retry path. None of those requires a fresh installation.

