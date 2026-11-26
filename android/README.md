# RDPMonitor for Android

Native Kotlin / Jetpack Compose companion, developed separately from the Windows
runtime. Version 0.3.0 adds native management sections, scoped owner consent,
reviewed actions and live bandwidth/activity. See [native management](docs/MANAGEMENT.md).

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

The panel supports browser Passkey pairing with a matching code and PKCE.
Monitoring and administration are distinct grants. Existing monitoring sessions
remain restricted until the owner approves a fresh administration request.
Native sections use the existing validated server operations and execution gates.
See [management permissions and coverage](docs/MANAGEMENT.md) and
[the original TEST setup](docs/TEST_PAIRING.md).

Tailscale remains a separate prerequisite. This app does not install it, expose
the server publicly, or replace it with a shared token. Production deployment is
performed after automated checks under the owner's standing authorization.

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
