# RDPMonitor for Android

Native Kotlin / Jetpack Compose companion, developed separately from the Windows
runtime. This first milestone is a runnable foundation, not a replacement for
the full web panel.

## Run it

Requires JDK 21, Android SDK platform 36 and build tools 36.0.0. Set `JAVA_HOME`
and put `sdk.dir` in an untracked `local.properties`, or set `ANDROID_HOME`.

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

Install `app/build/outputs/apk/debug/app-debug.apk`. Android 8.0 / API 26 or newer
is required. The debug application ID ends in `.dev`, so it can coexist with a
future release build. Release signing credentials do not belong in this repo.

Choose **Explore offline demo** to inspect every native destination without a
server. All demo screens are explicitly marked; none execute Windows commands.

To check a server, enable Tailscale on the phone, then enter its HTTPS address,
for example `https://server.example.ts.net`. Only canonical `.ts.net` HTTPS
origins on port 443 are accepted in this milestone. The real `/health` endpoint
is checked with normal certificate validation. Saved addresses contain no bot
tokens. **Open secure web panel** uses the external browser and the existing
Passkey / Telegram owner approval flow.

## Implemented

- Private server profiles, health checks, connection feedback and deletion.
- Native overview: CPU, memory, disks, rates, sessions, and bounded history chart.
- Native bandwidth preview: daily totals, download/upload and quota accounting.
- Activity and process views; grouped Protection, Backups, RDP access, Cloud,
  Commands, Updates and Access workflow outlines.
- Foreground-only polling and retention of previous readings on refresh failure.
- Keystore-encrypted native session storage and a tested PKCE callback boundary.

## Current limits

This branch implements **opt-in TEST native pairing** with browser Passkey
sign-in, explicit owner consent, a matching code, PKCE and a separate read-only
app session. Live resource readings and history are wired once pairing succeeds.
The running production server does not yet advertise this capability. Until it
is deployed and enabled there, the app reports that pairing is unavailable.
Live bandwidth totals/incidents and native administration remain future work.
See [TEST setup and evidence](docs/TEST_PAIRING.md).

Tailscale remains a separate prerequisite. This app does not install it, expose
the server publicly, or replace it with a shared token. No production source,
configuration, firewall rules or running services are modified by the app.

## Structure

```text
app/src/main/java/io/github/mans230/rdpmonitor/
  MainActivity.kt           external-browser handoff and lifecycle
  RdpViewModel.kt           profiles, connection and foreground polling
  core/model/              immutable application models
  core/network/            bounded HTTPS API client
  core/security/           private origins, PKCE and callback validation
  core/storage/            Android Keystore-backed session persistence
  data/                    API decoder and explicit offline fixtures
  feature/connect/         server onboarding
  feature/overview/        resource monitoring
  feature/bandwidth/       traffic and quota preview
  feature/activity/        incidents and processes
  feature/more/            grouped workflows
  ui/                      navigation, shared chart/components and theme
```

See [the integration plan](docs/INTEGRATION.md) before implementing server support.

## Design

Preserves the panel's neutral black and light blue identity. System typography,
monospaced readings, 48dp controls, scrollable content and fixed-height charts
address the readability and mobile layout issues raised in the conversation.
Unknown readings remain absent; a history gap is not rendered as zero traffic.

Validation covers origin isolation, RFC 7636 PKCE, callback expiry/state,
ambiguous callback rejection, decoding missing versus zero readings, and
reconciliation of fixture traffic totals. It does not establish production
WebAuthn interoperability or validate a server pairing endpoint that does not
exist yet.
