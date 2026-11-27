# Motion Studio review build: 0.10.0

## Design intent

Keep the approved neutral coss surfaces, typography and contextual actions. Add a coherent motion identity through a slowly dimensional server illustration, connected signal movement, a unified responsive easing and a compact shape/orbit loading motif. Decorative geometry never represents server readings. The overview stays limited to its existing real resource/status content.

Use all five selected repositories according to their actual strengths. Four are asset-generation tools, not APK runtimes; Lottie renders natively. Exact contributions and regeneration are documented in ../motion-tools/README.md. No WebView, embedded scripting engine, game activity, new network permissions or authentication changes are introduced.

## Review journey

Review controls are present only in debug/review builds. Use the play-circle icon on the Welcome/sign-in header, or Appearance -> Motion previews when connected. Pause/play the artwork, inspect the combined loader and tap the miniature bottom bar. Preview navigation modifies only its local state, not app routes or server sessions. Done and Android Back close the preview. The welcome artwork and real page/bar transitions also use the generated assets outside the preview.

## Boundaries and acceptance

- Native button spring feedback remains the common click implementation; actions are not delayed to match animation.
- Android reduced motion preserves static art and immediate navigation. Ambient animation stops when the host lifecycle falls below STARTED.
- Existing identity/profile, pairing, capabilities and confirmation behavior are preserved.
- Required checks: assembleDebug, testDebugUnitTest including native journeys and asset/lifecycle/reduced-motion tests, lintDebug; inspect phone/tablet and both themes.
- Actual test outcomes are recorded at delivery. Physical-device frame pacing, wallpaper GPU blur and real identity/private-network acceptance remain separate. No fixture or screenshot proves those.
- This is a review APK. The app-builder skill is unchanged and no universal animation-library choice is inferred from this product trial.
