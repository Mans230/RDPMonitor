# Native management milestone — 0.3.0

Replaces the old workflow outlines with native data views, forms and explicit
action review. No section requires opening the web panel to perform its
implemented operations.

## Permissions and upgrade

Existing app sessions remain monitoring-only. The new app requests the distinct
`administration` scope during a fresh browser pairing. The owner consent page
explicitly describes account, firewall, execution, backup and power permissions.
Only an approved owner Passkey can grant it. Mobile sessions cannot approve other
app sessions. Raw file downloads remain outside the mobile API allow-list.

Install the new APK, open server connections, select the saved address and check
the connection to approve the new permissions. Existing Passkeys still work;
there is no need to register a replacement key.

## Native sections

- **Protection:** security/RDP posture, blocked addresses, traps, block/unblock,
  subnet controls, lockdown and panic state.
- **Backups:** archive and worker status, progress, sources, schedules, cloud
  destinations, backup now, restore review and verification drill.
- **RDP & users:** local accounts, active session IDs, allow-list edits, port
  changes, messages and session logoff.
- **Cloud & images:** guided Drive/OneDrive/Dropbox sign-in, native storage
  provider fields, token import, OAuth client settings, connection tests,
  destination selection, image creation/upload/stop/link and job answers/cancel.
- **Command center:** services, process termination, program launch, commands,
  diagnostics, automation, temporary file cleanup, file/log delivery to Telegram
  and reviewed power controls. Existing execution gates remain enforced.
- **Updates:** release status, channel check, validated update application and
  automatic-update settings. Installation may restart the bot and panel.
- **Settings & alerts:** real setting values, contextual edits, alert mute/resume,
  test notifications and usage reporting.
- **Private access:** access configuration, app-session scope/expiry, revocation
  and native disconnect.
- **Bandwidth:** real daily ledger, billing-cycle totals, quota, coverage metadata,
  adapter/connection detail and the server's scope caveat. Missing data is not
  fabricated as zero; the chart scales to actual recorded amounts.
- **Activity:** grouped recorded audit events, process CPU/RAM and reviewed
  process termination. Audit events are not presented as a complete incident feed.

Server folders/files can be browsed with parent navigation and pagination.
Existing backup sources/schedules/targets prefill the edit forms. Storage
provider fields exclude stale inputs from another provider. Secrets are kept out
of confirmation text and are not persisted as form drafts.

## Confirmation and navigation

Server changes first prepare a nonce bound to the exact action/arguments. A
separate native dialog identifies the server and effect. Changed, expired and
replayed nonces fail server-side. Session revocation uses the dedicated
CSRF-protected endpoint with a native confirmation. Failed requests are never
automatically repeated as writes. Demo mode cannot read or mutate a server.

Opening server connections preserves the current session and provides Back to
monitor. Section switches cancel obsolete data loads rather than dropping the
new destination's request. Data failures remain visible with explicit retry.

## Validation and limits

The Python suite includes administration-consent, CSRF, action argument binding,
nonce replay and monitoring-session isolation. Android tests cover provider field
isolation, secret redaction, process IDs, cycle accounting and supported update
operations. Builds and signatures are verified before delivery.

Physical Android interaction acceptance belongs to the owner. A requested
separate UX review will identify navigation/confusion findings against this
version and distinguish source-traced findings from actual device observations.
The app retains explicit refresh controls for long-running job/progress views;
it does not run administrative jobs merely by opening a section.
