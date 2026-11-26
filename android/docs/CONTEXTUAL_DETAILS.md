# Contextual management details (0.6.1)

Known management responses use API-specific presentation models instead of recursive key capitalization. The approved backup reference is implemented in native Compose; its sample constants are not used as production data.

## Backups

Order: Latest backup result, Stored archives, Backup schedule, Local retention, Sources & destination, Actions. Optional setup-operation cards and raw disclosures follow the primary workflow.

- `last.files` is files processed in the latest reported run. It is never used as the archive count or copied into per-archive details.
- `items` contains local archive records. The server returns **at most ten** entries, so the app says how many are reported and does not claim a complete inventory.
- `items[].size` is bytes, formatted with binary units (`524288000` -> `500 MiB`). Unknown/raw values remain unconverted in additional details.
- `items[].modified` is **Archive last modified**, formatted in **device time**. It is not a completion timestamp.
- `keep_local_copies` is a retention limit, not the number currently stored.
- Worker `idle` means No job running. It is separate from the latest result. A success timestamp without a result cannot prove the latest attempt succeeded or an archive was verified. Conflicting verification fields are explicit.
- Daily/interval/multiple-time schedules use their declared server mode and reported timezone. No next date or countdown is invented from the phone clock. Conflicting setup/status settings are explicit.
- Folder and remote counts describe configuration. They do not prove cloud copies exist or have passed verification.
- Partial and malformed responses show Unavailable rather than becoming zero counts.

The original demo values are preserved: 42 processed files, 1 reported archive, 500 MiB archive size, up to 3 local copies, daily 03:00, 2 folders and 1 configured remote.

## Other reviewed schemas

RDP uses configured TCP port, allowlist/panic/lockdown state and blocked-address counts; configuration is not external reachability proof. Local users distinguish account sign-in from app access. Service inventory reports actual service status; service-watch rules are configuration. Memory thresholds use MiB, RAM/disk/image capacities use binary byte units, and host uptime uses a duration. Trap-name configuration is not an inventory of enabled Windows accounts. Cloud destinations do not imply upload success. App-session creation/expiry and host boot times explicitly use device time. Updater check intervals are hours and checks remain distinct from installation. Audit counts refer to the returned history rather than an inferred calendar day.

Settings retain the server's group/field labels and editing metadata. Additional server details show redacted raw keys/values without guessing unknown numbers' units or timestamps. App-session revoke and cloud answer/cancel controls still use the existing review/confirmation path and remain absent or disabled without the existing access rights. Demo mutations remain disabled.

Schema review also corrected the native automation option `autokill` to the server-supported `svcwatch`, and supports the server's structured cloud question (`id`, `name`, `choices`, `default`, `required`, `secret`) without bypassing review or exposing secrets. No server API, credentials or host state are changed.

## Validation

`ContextualDetailsTest` covers number meanings, binary units, unknown/zero/malformed data, dates, verification/schedule conflicts, retention, trap names, supported automation lists and redaction. Native journeys cover backup labels on screen and disabled demo actions. Component tests check cloud-question payload binding and the retained revoke control without server requests. Screenshots include backup result/archive/plan views at phone and tablet widths.

Run `powershell -File android/scripts/check-app.ps1`, inspect `app/build/reports/app-journeys`, and do not claim hardware acceptance from these renderer tests. The separate real Google sign-in check from 0.6.0 remains pending until the owner tests it on a phone.
