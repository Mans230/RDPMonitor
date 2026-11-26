# Native integration roadmap

## Security baseline

Keep Tailscale Serve HTTPS in front of the loopback panel. Keep Passkey sign-in
and explicit primary-owner Telegram approval for new keys. Never put panel or
Telegram tokens into a chat link, app package, QR fixture or committed config.
The native app cannot read a browser's HTTPOnly cookies. Browser authorization
must explicitly grant a separate, revocable native session.

This milestone changes Android files only. The protocol below is proposed and
must be implemented and integration-tested in an isolated Windows TEST instance
before enabling its advertised capability or updating production.

## Proposed browser-to-app pairing contract

1. `GET /health` continues to return `ok` and `auth: passkey`. Advertise
   `mobile_pairing: true` only when the complete flow is implemented.
2. `POST /api/mobile/v1/pairings` receives `code_challenge`,
   `code_challenge_method: S256`, random `state`, and the fixed callback
   `io.github.mans230.rdpmonitor://auth/callback`. Return a same-origin
   `authorization_url`. No native session is issued at this step.
3. The external browser signs in using the normal Passkey flow. New Passkeys
   still require owner approval. Show a distinct consent screen identifying the
   Android app and the permissions of its session. Require a deliberate action;
   an existing browser login alone must not authorize app pairing.
4. Redirect only to the fixed callback, with `code` and the original `state`.
   The code is random, short lived, single use and tied to the challenge,
   approved actor and originating panel. Do not include a cookie or long-lived
   credential in the callback. Redact callback codes from request logs.
5. `POST /api/mobile/v1/exchange` receives `code`, `code_verifier` and the exact
   `redirect_uri`. Consume the code atomically only after validating PKCE,
   expiry and origin binding. Return a new `Secure; HttpOnly; SameSite=Strict`
   `rdpwc_session` cookie plus JSON `csrf`, `actor` and
   `idle_timeout_seconds` (60–1800). Enforce server expiry and revocation.
6. The client stores its own session encrypted with Android Keystore, binds it
   to the exact profile origin, and rejects unexpected callback destinations,
   duplicate parameters, mismatched states and expired pending requests.

The client currently supports this contract but the server does not. A custom
scheme can be intercepted by another app; PKCE prevents an interceptor from
redeeming the code without the verifier. Consider verified App Links for a
future distributable app if a controlled HTTPS association domain is available.

Before enabling: test two-device owner approval/rejection, wrong verifier,
replayed/expired code, changed profile origin, cancellation, process death,
server restart, session revocation and hostile redirects. Bound pending request
counts, rate-limit creation/exchange, and apply CSRF protections on browser
consent. Do not enable CORS globally to accommodate the native client.

## Delivery milestones

1. **Foundation (this change):** buildable native app, explicit demo, profiles,
   health checks, read-only screens, API decoding and authentication boundaries.
2. **TEST authentication:** implement the server pairing contract; verify on an
   actual Android phone with Tailscale and Passkeys. Add session listing and
   local/native logout with server revocation before release.
3. **Live read-only monitoring:** wire history, reliable bandwidth ledger and
   incidents. Display ledger coverage, counter resets, adapter selection,
   missing samples and billing period; never claim billing-grade accounting.
4. **Administration parity:** add protection, RDP/users, backups/sources/schedules,
   cloud/rclone, system images, command categories and updates in small groups.
   Use explicit confirmation, server-side permission checks and audit entries.
   Never execute destructive actions from previews or connection checks.
5. **Release:** real device accessibility/rotation/large-text checks, session
   recovery, offline/reconnect tests, signed APK and documented update channel.

## References

- [Native app authorization and external user agents (RFC 8252)](https://www.rfc-editor.org/rfc/rfc8252.html)
- [PKCE, including the S256 test vector (RFC 7636)](https://www.rfc-editor.org/rfc/rfc7636.html)
- [Android Passkey architecture](https://developer.android.com/identity/passkeys/architecture)
- [Credential Manager prerequisites and website association](https://developer.android.com/identity/credential-manager/prerequisites)

Direct native Credential Manager authentication is another possible future
design. It needs explicit Android origin verification and a tested association
with the private server; it is not enabled by copying a web Passkey request.
