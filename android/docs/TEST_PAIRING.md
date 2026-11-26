# Android pairing: plan, implementation and TEST evidence

## Goal and scope

Private server address → external browser → approved Passkey → explicit app
consent → app callback → independent read-only session → real monitoring data.
No Telegram/chat login token and no browser-cookie extraction. Production is
unchanged. The existing owner approval policy remains mandatory for new real
Passkeys. Automatically approved keys in tests are generated fixtures only.

## Delivered steps

1. `mobile_pairing.py`: ephemeral, locked and bounded PKCE request/code stores;
   exact callback, S256, random state, 10-minute pending TTL, 60-second code TTL,
   one-use atomic exchange, matching codes and request throttling.
2. Panel routes: opt-in capability, HTTPS/trusted Serve checks, owner browser
   consent, CSRF validation, separate mobile cookies and immediate key-revocation
   checks. Mobile sessions cannot change the host or grant additional sessions.
3. Consent page: Passkey login, separate Approve/Deny, matching-code checkbox,
   explicit read permissions, session list and revocation. Existing browser login
   alone never approves a request.
4. Android: validates the code shown by the server, displays the matching code,
   validates the callback, exchanges PKCE, stores its session under Keystore,
   reads real stats/history and polls only in the foreground. Disconnect revokes
   the session when reachable and always clears the local credential.
5. Independent TEST runner: real read-only psutil readings without starting the
   bot, invoking host commands, reading production runtime config or changing
   firewall/Serve rules. Initial CPU/network samples remain unavailable until a
   rate can be measured; history gaps stay gaps.

## Run isolated TEST

From the development clone, with the pinned Python dependencies installed:

```powershell
python panel_auth_test.py --mobile-pairing run
```

Open `http://localhost:18499/mobile/authorize` locally. This is an explicit
loopback TEST exception. The Android app still accepts only private HTTPS
`.ts.net` origins, never loopback HTTP or public IP login.

The runner uses its own SQLite credential database under ignored
`test-runtime/panel-auth/`. It starts **no Telegram bot**. For a human TEST key,
match its displayed request ID using the runner's `pending` command and have the
local TEST administrator approve that exact request with `approve`. Production
keys and approvals are not copied. The UI labels this distinction.

```powershell
python panel_auth_test.py pending
python panel_auth_test.py approve <matching-TEST-request-id>
python tests/mobile_live_smoke.py
```

The optional smoke test refuses any origin except the fixed localhost runner
and requires its `test_mode` marker. It generates and approves its own TEST
authenticator, performs real signature verification, approves an app, exchanges
the code, reads actual host CPU/RAM/disks/processes, checks command denial,
logs out and revokes the generated fixture key in `finally`.

For a phone test, the isolated runner needs its **own private HTTPS TEST
endpoint** matching `--origin`, plus an explicitly configured Tailscale Serve
route. Do not redirect the existing production root URL as a test shortcut.
No such route was created in this task.

## Validation

- Python suite: 331 tests passed, including nine new pairing/HTTP tests.
- Existing browser Passkey tests: eight passed.
- Android build, seven JVM tests and lint: see the final validation entry.
- Loopback smoke: PASS; real RAM 38.6%, one disk and forty process rows were
  returned during verification. App host-management requests were denied, and
  its cookie stopped working after logout.
- TEST browser login page loaded with the expected unauthenticated session 401
  and no JavaScript exception. The browser resize failed because the desktop
  did not draw the requested viewport, so phone layout is not claimed verified.
  Production URL health
  returned HTTP 200 with `auth: passkey` but no native pairing advertisement;
  its unauthenticated pairing-page request returned HTTP 401.

## Remaining acceptance and rollout

The supplied production URL is still running its current version. Automated
loopback tests do **not** prove Android OS/browser handoff or phone networking.
Test the following on the phone against an isolated private TEST endpoint:
existing-key login, new-key approval/rejection, code matching, explicit consent,
automatic return, app restart, real readings, offline recovery and logout.

After approval for a production rollout: deploy the reviewed code and required
assets, keep the panel on loopback/Tailscale, enable `mobile_pairing_enabled`
explicitly, restart the panel, verify HTTPS health/capability and repeat phone
acceptance. Existing Passkeys remain in their existing credential store. Disable
the capability and restart to roll back; pending handoffs and app sessions are
memory-only and do not survive restart. No update or enablement was performed.
