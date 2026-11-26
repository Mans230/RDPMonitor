# Security and administration changes

Every trusted Telegram controller and WebConsole owner/operator has broad
administrator access. Personal tokens provide attribution and revocation, not
read-only roles, MFA or a boundary for untrusted tenants.

## Request confirmations

State-changing actions and sensitive data-transfer actions require a server nonce:
users, power, processes, services, commands/programs, screenshots, backups/restores,
RDP/firewall, settings, automation, updates, exports and file sending. Read-only
service status, RDP status and automation/trap lists are exempt. The authoritative
list is `webconsole/action_policy.py`; tests compare it with the browser policy.

1. POST `/api/action` with `action: "prepare"`, `target: <action>` and the arguments.
2. Submit identical arguments with `action: <action>` and the returned `nonce`.

Both steps require authentication and CSRF. Nonces bind to session, action and an
HMAC of arguments, expire after 60 seconds, and are consumed once (including on a
mismatch). At most 16 are pending per session. `confirm: true` alone is insufficient;
existing operation-specific flags/checks still apply. Update HTML and Python
together. A nonce prevents stale/replayed/mismatched requests; it cannot prove
that a human read a dialog.

## Account safety

`user_management` gates every panel account mutation. Panel delete/disable/password
actions and Telegram delete/disable use the last-admin guard. Unavailable/incomplete
inventory or a missing target denies guarded operations. Group lookup uses the
built-in Administrators SID. Panel password creation/reset uses the existing local
password policy.

`account_safety.py` serializes Telegram account commands and panel account actions
inside the monitor process. One reentrant lock spans validation, inventory and
mutation, preventing concurrent channels from disabling both remaining admins.
It cannot coordinate unrelated Windows tools, domain policy or other processes.

## Resource bounds

- Telegram messages/files and callbacks share 30 commands per minute per user.
  At most 100 jobs wait; overload is rejected without blocking polling or claiming
  an unaccepted job was accepted.
- Every panel `api_diag` operation uses one diagnostic worker with a default
  90-second response budget (below the panel's 150-second request timeout). A
  timed-out worker holds capacity until it actually exits.
- `diagnostic_runtime.py` propagates a cooperative deadline. Diagnostic
  `subprocess.run` timeouts are clamped to remaining time; Python kills/waits for
  its direct child on timeout. Speed-test HTTP timeouts use remaining time.
  Non-diagnostic subprocess timeouts are preserved.
- This does not forcibly terminate Python threads, kill entire Windows process
  trees or guarantee that DNS/native code/HTTP streaming ends at an exact instant.
  A stuck worker blocks diagnostics until it exits or the process restarts;
  monitoring and control threads remain separate.

## Secrets and audit

See [operators and usage](USAGE-AUDIT.md). Backup secrets use machine-scoped DPAPI
for SYSTEM access, so file ACLs are essential. ACL command failures now return
failure and warn; the backup worker logs aggregate failures. Command success is
not an effective-permissions audit: inspect inherited/explicit ACEs on a VM.

Panel and bot configuration exports mask sensitive values of every JSON type.
Export files use unique temporary paths. Sensitive command payloads are scrubbed
from the legacy Telegram action audit. Local logs remain administrator-editable,
not tamper-proof evidence.

## Upstream alignment

The original local source was `431c81a`. The PR starts from upstream
[`e4e9050`](https://github.com/Mans230/RDPMonitor/commit/e4e905047617e4a04f9effe95cf681a6bc3aa202).
Its any-type credential masking, bot-export correction and regression tests are
retained. This diagnostic policy is stricter: one worker overall rather than one
per job name, with a cooperative native-operation deadline.
