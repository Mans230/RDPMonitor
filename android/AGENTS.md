# Android companion

Build a native Kotlin/Compose companion. Keep sample data clearly labelled.
Never copy production configuration, passkeys, cookies or Telegram credentials.
The user authorizes production rollout after automated checks and will do device
acceptance themselves. Preserve Passkeys/configuration, checkpoint changes and
verify private access. Do not ask again for routine deployment approval.
Require exact private HTTPS origins and default certificate verification.
Use external-browser Passkey authorization plus PKCE for native pairing; never
extract browser cookies or introduce a shared bot token or insecure WebView.
Until the server pairing protocol is implemented and approved, show its absence
clearly. Preview operations must never execute real server changes.

Before delivering future Android changes, run assembleDebug, testDebugUnitTest
and lintDebug, including AppJourneyTest. Inspect generated native screenshots
under app/build/reports/app-journeys at phone and tablet widths. Fix failures
before release. Do not ask the user to install each intermediate build for basic
navigation, layout or form checks. Report separately what still needs hardware
(real Passkeys/biometrics, Tailscale connectivity, system photo picker, device GPU).
Keep journeys offline or on isolated fixtures; never use production credentials
or execute host-management actions to test controls.
