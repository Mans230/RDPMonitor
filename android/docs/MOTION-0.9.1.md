# Android 0.9.1 motion trial

## Scope and library choice

This trial changes native interaction feedback while preserving the approved coss geometry, colors, route ownership and real authentication/backend flows. The Android app-builder skill is deliberately unchanged until the APK trial is evaluated.

Evaluated reference families:
- Airbnb Lottie Android / Compose: used for the bundled loading orbit. Version 6.7.1. Original asset `app/src/main/res/raw/connection_pulse.json`, authored for this project; no downloaded artwork or network animation dependency.
- Motion for React: interaction reference only. Its browser/React runtime is not embedded in the native APK.
- AndroidX Compose animation: native springs, interpolated colors/position and drawing-layer transforms for gestures, navigation and transitions.

Sources: https://github.com/airbnb/lottie-android ; https://motion.dev/docs/react ; https://developer.android.com/develop/ui/compose/animation/quick-guide . No claim that JavaScript engines from the supplied list were installed or benchmarked.

## Motion coverage

| Interaction | Behavior | Boundary |
| --- | --- | --- |
| Primary/outline/text/icon buttons | 0.965 press scale with damped spring return | Original click handlers and enabled states; no delayed invocation |
| Clickable directory/profile/source/function rows | Shared press feedback plus existing indication | Existing labels, roles and permissions preserved |
| Bottom glass navigation | One sliding selection capsule, icon lift, tint interpolation, press feedback | Capsule is decorative; tabs retain selection semantics and 44dp content minimum |
| Scrolling | Native fling plus subtle dock compression/return and fading top edge | Bar remains fixed; reserved viewport clearance is unchanged |
| Page changes | Single mounted destination, 220ms fade/10dp entrance | No outgoing duplicate effects or synthetic data loads |
| Dialogs/onboarding | Shared entrance; controls use shared feedback | No authentication shortcuts or altered confirmation handlers |
| Segmented filters | Interpolated selection fill and press feedback | Existing filter callbacks |
| Connection/sign-in loading | Bundled monochrome Lottie orbit with progress semantics and native fallback | Existing real state controls display; no artificial completion |
| Reduced motion | Observe Android animator-duration setting; snap transitions/static loader at scale zero | System speed also applies through Compose; no extra user setup |

Material switches/checkboxes retain their native selection animations. Drawing-layer transforms avoid changing layout size. Selection/callback correctness and layout clearance are tested offline; physical-device frame pacing, wallpaper blur/GPU and live Google/Passkey/network behavior are separate acceptance items.

## Verification record

See current test/build reports under `app/build/reports/` and screenshots under `app/build/reports/app-journeys/`. Required checks: assembleDebug, testDebugUnitTest (including AppJourneyTest, LoadingScreenTest and MotionInteractionTest), lintDebug. The final delivery message records actual outcomes; this document is not a claim that a queued check passed.
