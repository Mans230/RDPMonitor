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

## TEST pairing milestone — 0.2.0

- Final Gradle build / seven JVM tests / Android lint: passed; zero lint errors,
  nineteen advisory warnings.
- Python suite: 331 passed. Browser Passkey tests: eight passed.
- Actual loopback TEST runner smoke: passed real read-only metrics, signed
  fixture authentication, explicit app consent, exchange, command denial and
  logout. Its generated fixture key was revoked afterward.
- APK v2 signature verification: passed.
- Artifact: `artifacts/RDPMonitor-Android-0.2.0-test-pairing.apk`.
- SHA-256: `bd5917c98f0d68fbf665fcd028ad685cfb72758d6ef4f7f5557faa3326273be5`.

Production capability remains unavailable; the supplied private URL was checked
read-only. The isolated TEST runner was stopped after validation. Native phone
Passkey/OS callback acceptance and production rollout are still outstanding.
See [the TEST plan and evidence](TEST_PAIRING.md).

## Native management milestone — 0.3.0

- Python suite: 332 passed, including administration grant isolation, CSRF,
  confirmation argument binding, replay rejection and mobile self-approval denial.
- Browser helper suite: 38 passed.
- Android JVM tests: eleven passed (seven core, four management/accounting).
- Final Gradle build and lint: passed, zero lint errors.
- APK signature: v2 verification passed.
- Artifact: `artifacts/RDPMonitor-Android-0.3.0-management.apk`.
- SHA-256: `ab7a359f6d41c5f019ee4291e865f075d12ce53704a7c9894d64d182c6625a80`.
- Physical-device interaction acceptance remains owner testing; the separate
  requested UX audit will report its method and findings against this version.
