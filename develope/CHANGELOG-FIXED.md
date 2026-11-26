# RDP Monitor v4.3-fixed

Security and reliability corrections applied to a separate copy of v4.3:

- Replaced TCP-port instance locking with a per-installation Windows named mutex.
- Updated installer status and uninstall detection to use the same mutex.
- Reworked the RDP allow-list as explicit TCP and UDP rules.
- Windows `TermService`/RDP service rules are now treated as relevant RDP rules.
- Firewall rules are tracked by unique rule ID rather than non-unique display name.
- Firewall changes are made one at a time and rollback state is saved after each change.
- Failed scans, verification, policy changes, and rule changes trigger rollback.
- Firewall Guard does not enable the firewall unless an RDP access rule was verified.
- Lockdown no longer automatically trusts currently connected clients.
- Corrected Event 4625 NLA fields (`LogonProcessName` and `AuthenticationPackageName`).
- Failed unblock operations retain their local block record.
- Uninstall cleanup now reports a real exit status and `[cleanup] done` marker.
- Text, photo, and document retry queues persist across restarts.
- Password-bearing Telegram messages are deleted on receipt when bot permissions allow.
- Disk2vhd requires a valid signer whose certificate CN is exactly Microsoft Corporation.
- Disk imaging is disabled by default, requires confirmation, refuses the Windows system
  volume as its output target, and persists/reconciles operation state after restarts.
- File upload and Windows user management are disabled by default on fresh installs.
- Added safety regression tests under `tests/`.

Run non-destructive tests with:

```console
python -m unittest discover -s tests -v
```

The monitor still starts at user logon rather than early Windows boot. Changing it to run
as SYSTEM would break interactive screenshot/message features and user-scoped DPAPI, so
that architectural limitation is documented rather than hidden.

## Hardened WebConsole edition

- Integrated the patched core instead of the original v4.3 core.
- Localhost-only installation by default; no automatic public firewall opening.
- Direct remote mode requires TLS certificate/key and an explicit source-IP allow-list.
- Replaced URL bearer tokens with DPAPI-protected login token, HttpOnly SameSite session
  cookie, 30-minute expiry, CSRF token, login throttling, and token rotation.
- Shell/program execution and arbitrary file downloads are disabled by default.
- Added request/body/thread/time limits, security headers, Host checks, file-root and size
  limits, streamed downloads, application-level IP enforcement, and a single-instance lock.
- Escaped dynamic dashboard content and removed external Google Fonts.
- Added validated IP operations, verified unblock behavior, and cross-process blocklist lock.
- Added WebConsole security regression tests.
