# Automatic bot and web-panel updates

Use **Setup → Bot & web panel updates** or `/suiteupdate` in Telegram.
The owner can enable automatic installation, set a check interval from 1 to
168 hours (24 by default), check a release, or install the latest validated
release. New installations default to off. Operator panel logins cannot change
update settings or request installation. Changes use CSRF protection and exact
server confirmation nonces.

`RDPSuiteUpdate` is an independent SYSTEM scheduled task. It runs after boot
and hourly, applying the configured interval. It survives stopping the other
suite tasks and needs no extra client application. Install it with the normal
Administrator suite installer, or `scripts/install_updates.ps1`. Settings and
status live under the private `control/updates` directory. The page and bot
show queued/checking/available/deferred/applying/installed/rolled-back/error
outcomes; request acceptance is not proof of installation.

Each successful main-branch push through `.github/workflows/tests.yml` publishes
a stable code-only `suite-<run number>-<commit>` GitHub release. The release job
runs only after the Windows test job passes, with write permission limited to
that publishing job. PR builds never publish. The updater checks the fixed
Mans230/RDPMonitor repository over HTTPS, verifies GitHub's SHA-256 asset digest,
the tag's commit, matching package identity, successful main-branch workflow,
and every packaged file hash before replacing code. Older/divergent releases
are refused. This trusts GitHub and repository maintainers; it is not a
separate publisher-signature or offline verification scheme.

Private repositories require a GitHub credential with Contents and Actions read
access for this repository. Save/remove it in the owner-only update panel, or
pipe it privately to `python suite_update.py auth-stdin`. It is stored with
machine-scope Windows DPAPI under the Administrators/SYSTEM-only update folder;
status APIs expose only whether it is saved. Tokens are sent only to this
repository's GitHub API paths, never redirected to the asset CDN. Private assets
download through the authenticated asset API. Do not paste credentials in chat
or put them in command arguments. Public repositories need no credential.

Packages exclude configuration, tokens, TLS keys/certificates, backups, rclone
accounts, history, logs, tests and agent files. Paths, sizes, duplicate names,
links and Python syntax are validated before extraction. Changed Python
dependencies require a manual installation; pip is never run automatically.
The legacy `/update` and `update_url` mechanism remains a separate single-file
monitor updater. Use `/suiteupdate` for the unified release workflow.

Installation waits for backup/system-image activity. New backup and image jobs
share a cross-process lease with installation, so a job cannot start between a
status check and stopping the worker. Pending administrative requests also
defer installation. The updater disables only the three runtime tasks, stops
verified suite processes, saves private rollback copies, replaces runtime code,
then restores the previous hosting mode and worker state. It tests both panel
authentication and the monitor RPC before recording the new version.

An unhealthy release restores code and configuration from the checkpoint and
restarts the old runtime. A durable journal recovers interrupted installations
on the next updater task run. A failed release is not retried automatically;
manual installation requests permit another attempt. Rollback checkpoints are
kept locally for diagnosis. Monitor restarts emit the existing **is UP** Telegram
message. Panel sessions end during installation and require another login.
