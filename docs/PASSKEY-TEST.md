# Private panel + Passkey: isolated TEST

This branch contains an isolated test runner and normal-panel integration.
Production rollout must follow validation: main automatically publishes suite
updates. Runtime data and test credentials must never be included in releases.

## Normal-panel deployment sequence

Use the installation's Python executable to install `requirements-passkey.txt`
before enabling Passkeys. The existing runtime lockfile stays unchanged; this
is an optional, explicitly installed authentication dependency. The new updater
requires all authentication helpers and this dependency file in its release.
The TEST runner itself is excluded from update assets.

Run locally as Administrator, from the installation's webconsole directory:

```powershell
python RDPWebConsole.py private-enable https://machine.tailnet.ts.net
```

This persists loopback binding and exact HTTPS origin and protects the local
public-key store. It does not restart services or change firewall rules. Restart
the normal panel and configure Serve for its actual loopback port (normally
8399). Then register a real device in the browser and use local commands:

```powershell
python RDPWebConsole.py passkey-pending
python RDPWebConsole.py passkey-approve <matched_request_id>
python RDPWebConsole.py passkey-revoke <fingerprint>
```

These operations never issue chat login tokens. Confirm the private route before
disabling the old public panel firewall rule; preserve RDP access for recovery.
The updater now checks the HTTPS private health endpoint and the ACL-protected
local monitor mailbox without adding a token or HTTP authentication bypass.

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
Use Serve, not Funnel. A later check found Tailscale installed and connected on
the host. A temporary Serve proxy was tested with verified HTTPS, actual Host
and forwarding headers, real signed WebAuthn registration/assertions, local approval,
Secure login cookies, blocked token fallback and session revocation, then removed.

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

### Telegram link behavior in this TEST branch

`/panel` now offers only **Open private panel** and **Panel status**. It requires
an exact HTTPS `.ts.net` origin, matching Passkey origin and a loopback backend.
Missing or inconsistent configuration produces setup instructions without an IP,
localhost, token or signed-login fallback. The old `/paneltoken`, `/token` and
`panel:token` callback cannot read/decrypt/send a panel token. These commands are
hidden from the menu; old buttons remain safe. The `setup_token` backend request
is also retired. `/panelremote` cannot enable public access, even with `confirm`.
It reports private access instructions; `status` reports configuration, without
claiming the client is connected or the service is reachable.

The runner writes a **non-secret** descriptor at
`test-runtime/panel-auth/access.json` after binding its TEST port. For a separate
TEST bot only, set its `panel_private_access_file` config value to that absolute
path. Otherwise the bot validates the corresponding fields in its existing
`webconsole_state.json`. A local-only runner descriptor does not advertise a
tailnet link. This implementation starts no Telegram bot and sends no live chat
messages. Do not point the production bot at this prototype.

In Passkey mode, HTTP setup requests cannot reveal a panel token or change
access back to a public bind. Existing firewall rules on the production host
have not been changed or removed by this branch.

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

Local result: 314 Python tests and 35 Node tests passed; all 31 locked runtime
versions matched. A real TEST-runner smoke check also served the login UI and
Passkey configuration and denied token login and host-management actions.

Not yet verified: an actual browser + Windows Hello/phone passkey, and end-to-end host commands against a
disposable server. The runner deliberately cannot perform those commands. This
has not yet migrated current public access.
Before rollout, verify those acceptance checks and plan local recovery, a second
approved authenticator, service installation and production credential migration.

Protocol references: [WebAuthn](https://www.w3.org/TR/webauthn-3/),
[python-fido2](https://developers.yubico.com/python-fido2/),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).

## Complete private-only setup

The sign-in page has no token form. Setup has no Local/Public IP selector, IP
allow-list editor or token reveal control. Old setup requests cannot invoke the
remote-enable CLI. Normal panel startup refuses unconfigured legacy mode, and
the installer validates private configuration/dependencies before replacing tasks.
The suite's open/status commands resolve the exact private HTTPS URL.

During the controlled host migration, automatic installation was paused and the
prior enabled state was saved under ignored test-runtime/. Restore its prior
setting only after the migrated bot, private route and loopback listener pass
health checks. The public 8399 listener and its panel firewall rule must be
verified closed as part of rollout. This source change alone does not close them.
