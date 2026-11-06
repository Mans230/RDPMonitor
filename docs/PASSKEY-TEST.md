# Private panel + Passkey: isolated TEST

This branch is a local prototype. Production remains unchanged. Do not merge it
into main or publish a release: main automatically publishes suite updates.

## What this tests

- Discoverable WebAuthn credentials, device user verification required for
  registration and login, verified by pinned python-fido2.
- No chat token, password or OTP-link fallback in Passkey mode. The random
  internal HMAC key is not accepted by the login endpoint.
- Registering a device creates a public-key approval request, not a session.
  A local Windows administrator must match its ID and approve it within ten
  minutes. Browser requests cannot choose their role or approve themselves.
- SQLite stores public credentials, counters, short-lived challenges and pending
  requests. Private keys and biometric data are not sent to the server.
- HttpOnly, SameSite=Strict session cookies, CSRF tokens and existing action
  permissions/confirmations remain in force. Revocation rejects that key's
  sessions on their next request. Idle timeout is 30 minutes.
- Serve mode accepts only the exact configured HTTPS `.ts.net` Host, a loopback
  proxy, HTTPS forwarding and a single tailnet client IP. Unsafe requests require
  the exact Origin. Forwarding headers never grant a user identity or role.
- The TEST runner binds only 127.0.0.1:18499. It starts no bot, polling workers or
  production tasks. Host-management actions and live integrations are disabled.

## Install and run locally

Use an elevated PowerShell terminal **inside this TEST checkout**:

```powershell
python -m venv test-runtime\venv
.\test-runtime\venv\Scripts\python.exe -m pip install -r requirements.lock.txt -r requirements-auth-test.txt
.\test-runtime\venv\Scripts\python.exe panel_auth_test.py run
```

Open `http://localhost:18499` on the server, select **Register this device**, name
it, and confirm using the device lock. Keep the terminal running. In another
elevated terminal in this checkout:

```powershell
.\test-runtime\venv\Scripts\python.exe panel_auth_test.py pending
.\test-runtime\venv\Scripts\python.exe panel_auth_test.py approve <request_id>
```

Match the request ID to the one displayed in your browser before approving.
The ID identifies a pending public key; it is not a login secret. The CLI grants
owner access. Then select **Sign in with passkey**. No approval HTTP endpoint
exists. Do not approve an unsolicited device.

To remove a key, use the fingerprint printed by approval:

```powershell
.\test-runtime\venv\Scripts\python.exe panel_auth_test.py revoke <fingerprint>
```

Runtime data is ignored by Git and restricted to local Administrators and SYSTEM
on Windows. Linux tests use a private runtime directory. Protect these files:
someone who can edit the credential database can authorize another public key.

## Test with Tailscale Serve

This requires Tailscale installed and authenticated on the server and client.
It has **not** been installed/configured by this change. Tailscale was not found
on PATH during the local implementation check. Use Serve, not Funnel.

After obtaining the server's real MagicDNS name, stop the local runner and use
that exact origin (substitute the actual name below):

```powershell
.\test-runtime\venv\Scripts\python.exe panel_auth_test.py --origin https://machine.tailnet.ts.net run
tailscale serve --bg http://127.0.0.1:18499
```

Check existing Serve configuration before setting it: HTTPS port 443 may already
be used. Configure tailnet grants/ACLs so only the intended administrators can
reach this service. Open the HTTPS URL from an authorized tailnet device.
The backend port stays on loopback and needs no public inbound rule.

Use the same `--origin https://machine.tailnet.ts.net` before `pending`, `approve`
and `revoke`. Each origin has its own credential database. A passkey enrolled on
localhost must be enrolled again for the HTTPS hostname; changing origins does
not migrate credentials automatically.

## Verification and remaining acceptance work

```powershell
.\test-runtime\venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --test tests/test_webconsole_user_flow.js tests/test_passkeys.js
.\test-runtime\venv\Scripts\python.exe -B scripts/lock_dependencies.py
```

Tests exercise real ES256 assertion signatures and WebAuthn registration data,
HTTP enrollment/login/CSRF, token and OTP bypass rejection, local approval,
replay/expiry, wrong Origin, missing verification, bad signatures, counters,
operator permissions, owner/operator revocation and simulated Serve headers.
Node tests cover the browser codec and registration/login/error flows.

Local result: 306 Python tests and 34 Node tests passed; all 31 locked runtime
versions matched. A real TEST-runner smoke check also served the login UI and
Passkey configuration and denied token login and host-management actions.

Not yet verified: real Tailscale proxy headers/connectivity/certificate, an actual
browser + Windows Hello/phone passkey, and end-to-end host commands against a
disposable server. The runner deliberately cannot perform those commands. This
is not a production-ready rollout or a migration of current public access.
Before rollout, verify those acceptance checks and plan local recovery, a second
approved authenticator, service installation and production credential migration.

Protocol references: [WebAuthn](https://www.w3.org/TR/webauthn-3/),
[python-fido2](https://developers.yubico.com/python-fido2/),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).
