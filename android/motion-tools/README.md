# Reproducible motion assets

This is a build-time content pipeline. The Android runtime stays Kotlin/Compose with Lottie; it does not embed Godot, Three.js, Anime.js or Manim engines. Their actual generated output is shipped and used by native rendering.

| Producer | Output | App use |
| --- | --- | --- |
| Three.js 0.187.0 | 49 projected server-stack frames in motion_scene.json | Welcome and motion preview vector artwork |
| Anime.js 4.5.0 | 101 sampled easing values in motion_scene.json | Real page entrances and moving bottom-bar capsule |
| Godot 4.7.2 | 61 Tween samples in motion_pulse.json | Moving signals in the server illustration |
| Manim 0.22.1 | 31 sampled shape-transform paths in motion_morph.json | Native morphing center glyph inside the loader |
| Lottie Compose 6.7.1 | Existing original connection_pulse.json | Native loading orbit, combined with the Manim paths |

## Regeneration

From this folder, install the pinned JavaScript dependencies with `npm ci --ignore-scripts`, then run `npm run generate`.
Use an isolated Python environment with `pip install -r requirements.txt`, then `python generate_manim.py`.
Use the official Godot 4.7.2 portable executable: `godot --headless --path . --script generate.gd`.

The three generated JSON resources are committed under app/src/main/res/raw. Regular Gradle builds do not need these content tools or internet access for animation assets. No stock/vendor artwork was copied. Node packages retain their own license metadata; the generated geometry and scene composition were authored for RDPMonitor.

The native player interpolates geometry/path keyframes during drawing, rather than stepping the generated frame index. It honors the Android animation setting, stops ambient timelines when the activity is not started, and keeps static artwork/controls functional with reduced motion. These animations do not drive telemetry or imply an operation succeeded. Previews use local UI state only and cannot invoke server commands.
