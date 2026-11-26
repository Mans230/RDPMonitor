# Android 0.5.0 selected design

Implements the approved neutral dark priority layout in the native Compose app.
The approved HTML is a sample-data design reference, not a data source or an embedded WebView.

## Layout and coverage

- Black `#080808`, white `#f5f5f5`, muted `#b5b5b5`, border `#343434`.
- Local Inter variable font, converted from the approved reference's WOFF2 to an Android TTF. SIL OFL in `Inter-LICENSE.txt`.
- Transparent processor/history, memory and storage cards above the centered, in-flow Overview / Protect / Backups / Processes / More dock.
- Next backup lead, outlined Protection / Processes pair, wide RDP access, remote sessions.
- Overview, Protection, Backups, Processes, RDP & users, Local users, Settings, Command center, Resource history, System tools, Automation, Diagnostics, Command reference and Maintenance all have native routes. Cloud & images, Updates, Private access, Bandwidth and Activity remain available.
- Shared 16dp gaps, 20dp padding, 28dp group/dock spacing. Narrow phones use 16dp outer/card padding; very narrow resource/support pairs stack. Wide resource rows share their processor card's measured lower edge.
- There is no fixed bottom bar covering controls. Route scroll state, Android Back, server chooser recovery, operation progress, form review, and diagnostic jobs remain in place.

## Materials and local appearance

Appearance opens from the header. A user may choose a JPG, PNG or WebP up to 15 MB. Decode is off the main thread and sampled to at most 1600 pixels per side. The image is session-only, never uploaded, saved to server profiles, or committed. Blur is 0–40dp and the black overlay is 70–95%.

On Android 12+, dock and lead repaint the matching wallpaper region with 24dp / 18dp blur, respectively, then apply a dark scrim and subtle white fill. Foreground text and controls are separate sharp layers. Older Android uses opaque neutral glass surfaces and a stronger dark image overlay. No custom motion is introduced.

## Data and permissions

Resources and remote sessions use the recorded `/api/stats` snapshot; no prototype telemetry is used outside the labelled existing offline demo. Processes are labelled as reported, since the server returns a bounded list. CPU history retains the actual supported 30-minute window and missing-sample gaps.

The backup card reads the server's setup and backup endpoints only in an administration session. It shows configured time and server timezone, and explicitly says the next run time is not reported. It never invents “tomorrow” using the phone's clock. Last success is distinct from explicit archive verification. Missing, disabled, loading and failed reads retain written states.

All section actions reuse the existing catalog, server permission gates, nonce review and confirmations. Processes still use the existing reviewed stop action. Diagnostics preserve required arguments from PR #47. Pairing, Passkeys, PKCE, encrypted session storage, private HTTPS validation, and server code are unchanged.

## Validation

Run `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug` with JDK 21. `DashboardDataTest` checks server timezone, schedule variants, unknown data, verification evidence and real session/resource decoding. Existing authorization, billing, diagnostic and confirmation tests remain.

The reference screenshots were inspected before implementation. No Android device is attached in this environment; device screenshots, blur appearance, large-font/touch acceptance and the 320/390/768px visual pass on the actual APK remain unverified. The HTML inspector cannot validate native Compose. Do not treat reference-design validation as app validation.

Device acceptance: preview mode -> each dock tab -> every More section -> Back -> Servers -> return to monitor; test 320dp and large text, background add/remove, loading/error/zero data, monitored versus administrative sessions, diagnostics, and cancel/confirm dialogs. No server mutation should happen merely by opening a view.

This release changes only the Android client. Production bot/panel files and credentials need no replacement or restart.
