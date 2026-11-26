# Welcome, Google account and connectors (0.6.0)

The first page offers Google sign-in, an explicit private workspace, and the labelled offline demo. A successful Google sign-in opens the RDP connector page. Each connector continues to authorize independently through the existing Tailscale/Passkey browser and PKCE flow. A Google account never grants server administration.

## OAuth configuration

Set the public **Web application** OAuth client ID as `googleWebClientId` in `android/gradle.properties`, or override it with `-PgoogleWebClientId=...`. An Android client ID is not interchangeable with the Web audience. No client secret is required or embedded. A blank value keeps Google sign-in explicitly unavailable rather than pretending that it works.

Create a separate **Android OAuth client** in the same Google Cloud project as that Web client. Keep the existing Interval client (`com.zekohost.interval`) unchanged.

- Package of the test APK: `io.github.mans230.rdpmonitor.dev`
- SHA-1 of this machine's debug signing certificate: `C6:DE:96:B0:AC:1A:3D:7C:21:11:33:E9:7F:1D:9A:6C:CB:18:19:1F`
- If consent is in Testing mode, add the intended Google account to Test users.
- Release builds use `io.github.mans230.rdpmonitor` and need an Android OAuth client registered for the actual release/Play signing certificate. A CI-generated debug certificate is different and must not be presented as this local APK's certificate.

## Identity boundary and storage

Credential Manager performs the Google account chooser. The app generates a fresh random nonce and validates the returned ID token's RSA signature against Google's fixed HTTPS JWKS endpoint, issuer, exact Web-client audience, nonce, expiry, issuance time and verified email. Tokens and private Google credentials are never logged, persisted or sent to an RDP connector. Only the resulting local display profile is cached in app-private storage. This is a local app identity, not a backend login session or connector authorization.

Connectors and encrypted server sessions are partitioned by stable Google subject. The previous private workspace retains its original local connector store. Switching account cancels old reads and clears the old active session credentials; sign-out attempts server logout and clears Credential Manager state. Remote logout may fail when offline; server sessions retain their existing expiry/revocation policy. Operations in progress prevent account changes. Saved addresses are retained in their own workspace; they are not silently copied to another Google account.

## Motion

Google verification and private connection use an actual busy-state loading screen with an animated indeterminate indicator. No fake timed loading page or invented progress percentage is added. Main action buttons and dock presses have a short scale response. Workspace changes fade and rise 8dp over 180ms with only one destination mounted; animation does not duplicate data-load effects. Compose uses the system animation-duration setting. Existing Material control feedback remains.

## Checks before future delivery

On Windows: `powershell -File android/scripts/check-app.ps1`. Other platforms: run `bash gradlew --no-daemon :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` inside `android`.

Robolectric runs real Compose navigation, all section routes, server chooser recovery, disabled demo actions, workspace isolation and rendered text contrast. Provider-return tests also check that Google success opens connectors without granting server access, and cancellation returns to a retryable welcome page without caching identity. These two tests inject a simulated credential provider; they do not claim to exercise Google's real account chooser. Native screenshots at 320/390/768dp, welcome/connectors, the loading screen and appearance dialog are generated under `app/build/reports/app-journeys`. CI runs these checks and uploads the reports/screenshots; suite releases depend on the Android check as well as server tests. Screenshots need visual review; this is not pixel-perfect golden-image comparison.

The screenshot checks caught and fixed default black text on transparent dark surfaces. Native screenshot rendering is a local approximation, not hardware acceptance. Google chooser/client registration, real biometrics, Tailscale connectivity, GPU-specific blur and the system photo picker still need device testing. No live server commands run in the journey tests.

Primary integration guide: https://developer.android.com/identity/sign-in/credential-manager-siwg-implementation
