# Personal operators and usage audit

## Personal administrator tokens

From the installed suite directory in an Administrator terminal:

```powershell
python webconsole/RDPWebConsole.py operator-add alice
python webconsole/RDPWebConsole.py operator-list
python webconsole/RDPWebConsole.py operator-remove alice
```

`operator-add` displays a new random token once. Store it privately and enter it in
the existing login field. Do not paste it into issues, PRs or screenshots. Only a
SHA-256 digest of the high-entropy token is stored under `operators` in the
ACL-protected panel state. Names accept 1-40 ASCII letters/digits/_.-; the limit is
64 operators. To replace a credential, remove and re-add the operator.

Removal/replacement revokes their sessions on the next authenticated request;
already-dispatched work continues. There is no web endpoint to manage credentials.
Owner-token rotation retains its existing all-session revocation. Owner token and
Telegram one-time links authenticate as `owner`; sharing them prevents individual
attribution. Use personal tokens for trusted admins. All operators have full
administration rights: no RBAC, MFA or protection from malicious admins is added.

## Journals

- `usage_audit.jsonl`: Telegram queue/admission/execution events.
- `webconsole/usage_audit.jsonl`: WebConsole POST login/control responses.
- Existing `audit.json` and `webconsole_audit.jsonl` remain compatible; the former
  still holds its latest 300 entries.

Events include `version`, Unix timestamp `t`, `source`, `actor`, `action`, `status`
and `request_id`. Completion/response events include `duration_ms`. Web events
include a one-way session fingerprint, never the cookie/token. Actions use fixed
labels. Command arguments, passwords, output and file contents are excluded.

Actors are `telegram:<user-id>`, `owner`, `operator:<name>` or `unauthenticated`.
Telegram queue/completion records share a request ID. Pending button execution is
labeled `confirmation`, without expanding its stored payload.

Status semantics:

- `queued`: admitted to Telegram's queue, not yet executed.
- `completed`: the Telegram Python handler returned without raising, not proof
  that Windows accepted an operation or that an asynchronous job finished.
- `ok`: a successful WebConsole POST response. A prepared nonce or queued backup
  does not mean the underlying job completed.
- `failed`: handler/server error or an explicitly failed response.
- `denied`: authentication, nonce, rate or queue-capacity rejection.

Periodic GET polls, every diagnostic GET and downloaded bodies are not recorded
in the new Web journal. This is an action/response audit, not a complete access
log. CPU/RAM history remains machine-wide, not per-Windows-user accounting.

Each source rotates at about 2 MiB and keeps ten rotated files plus the active
file (about 22 MiB, allowing one-record overshoot per file). Retention is based on
size, not days. Protect filesystem access and export logs to trusted storage when
longer/tamper-evident retention is needed. No external analytics service is added.

## Read-only usage report

```powershell
python -B scripts/usage_report.py
python -B scripts/usage_report.py --journal C:\path\usage_audit.jsonl
```

Counts group events by actor/action/status and include rotations. Missing journals
produce zero events, never invented samples. These are not unique-person/session/
successful-operation counts: do not sum prepare/queue/completion as unique uses.
Authenticated GET `/api/usage` returns the WebConsole-only summary.
