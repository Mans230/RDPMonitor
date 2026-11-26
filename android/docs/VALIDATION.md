# Foundation validation — 2026-11-25

Branch: `feature/android-companion`. Scope: Android companion only.

- `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug`: BUILD SUCCESSFUL.
- Six JVM boundary/data tests, zero failures or errors.
- Android lint: zero errors, twenty advisory warnings (dependency versions and
  storage/style recommendations). No lint baseline hides findings.
- APK signature verification: passed, APK Signature Scheme v2.
- APK package: `io.github.mans230.rdpmonitor.dev`, version `0.1.0-foundation`,
  minimum API 26, target API 36.
- `git diff --cached --check`: passed.

Local artifact (ignored): `artifacts/RDPMonitor-Android-0.1.0-debug.apk`.
SHA-256:
`383e1472f8ff8ee47bb35b3aea3e53d68b0ad615f08c517067b4e413aba9c0e9`.

## Not verified yet

No Android phone is attached. Headless API 36 and API 26 emulator attempts did
not produce a usable device on this Windows host. Its acceleration check reports
that Windows Hypervisor Platform must be enabled. The API 26 software fallback
remained offline and was stopped. UI appearance, navigation, large text,
Keystore/browser behavior and actual device networking therefore still need a
phone or working emulator. Build success is not a substitute for these checks.

The server-side native pairing endpoints have not been implemented. No real
native Passkey exchange, live monitoring session or administrative action is
claimed as validated. The fixtures and workflow previews remain clearly marked.
No production bot, panel, firewall configuration or credentials were changed.
