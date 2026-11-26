# Native coss edition - 0.7.0

This is a Kotlin/Compose translation of the approved coss / Base UI design. React and sample server values are not embedded. The coss source license is retained in COSS-LICENSE.txt. The existing Inter font, Android package, signing key, encrypted connector storage, Google sign-in, Passkey/PKCE flow and server review protocol stay in place.

## Shared system

All existing function pages, connectors, settings, diagnostics, setup forms, operation results and dialogs use the neutral dark/light theme and shared coss-style controls. Frame groups have 16dp outer corners, a 4dp tray inset, separate 12dp bordered panels, inset header/footer trays and 16dp panel padding. Buttons and fields use 6dp corners with native focus, keyboard, disabled states and at least 44dp touch targets. The saved theme changes native ink, panels, meters, charts and dialog surfaces together. Text remains sharp over the optional local wallpaper.

Only bottom navigation uses glass: a centered capsule, translucent surface, fine highlight rim and neutral selected segment. On Android 12+ the optional backdrop image is repainted at the matching position and blurred behind sharp navigation content. Older devices use a stronger translucent fallback. This is not a WebView or a promise of arbitrary cross-window blur. Scaffold reserves the complete bar and gesture-inset height, so no controls or final rows sit underneath it.

## Real workflows

Overview contains only CPU, memory, storage, CPU/RAM recorded history, server uptime and latest backup health. The existing 30-minute history window and missing-data semantics remain. It does not include the prototype's scheduled-work or session fixtures.

Backups groups schedule policy, sources, archives and latest-run health in frames. Draft enable/mode/time edits go through the existing setup/prepare/confirm action; validation matches the server's HH:MM and 1-168 hour limits. Source selection must be reviewed and saved before a manual backup can use the new selection. Manual backup still uses configured sources. Retention is a read-only server limit because the current API exposes no retention-write action. Archive bytes, last-run files, current archive count, retention maximum and archive last-modified/device-time labels remain distinct. Unknown values are not fabricated.

Processes supports name/PID search, high-CPU filtering, empty-result recovery, exact-PID inspection, selection and reviewed stopping. Filtering clears hidden selections; refresh removes vanished identities; core PIDs cannot be selected. Up to 50 processes may be reviewed, matching the backend limit. Live actions require a connected administration session and preserve nonce preparation and final confirmation. Server-side protection remains authoritative. Demo actions stay disabled.

## Verification and limits

Run scripts/check-app.ps1 for assembleDebug, testDebugUnitTest and lintDebug. AppJourneyTest covers every function in both themes and Overview/Backups/Processes at 320/390/768dp. Its geometry assertions verify that the scroll viewport and final process action end above fixed navigation. CossInteractionTest exercises exact PID selection and details, hidden-selection clearing, protected PID controls, schedule boundaries and reviewed saved-source payloads using local callback capture only.

Inspect screenshots under app/build/reports/app-journeys. Offline native rendering does not validate real Google account selection, Passkey/biometric prompts, Tailscale transport, photo-picker permissions or physical-device GPU blur. No live server changes are executed by these journeys.
