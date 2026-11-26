# Reference fidelity corrections - 0.7.1

The approved coss source and its design-thread measurements were compared with 0.7.0 native screenshots. Missing behaviors and visual differences were real: native time fields were plain input, retention was read-only, archive rows were expanded metadata blocks, and popups were centered cards on phones.

Corrections include quiet alpha-equivalent borders, reference typography, 20dp frame panel/header/footer insets, compact input/button geometry, source-folder icons, compact archive rows with the original Lucide paths, reference policy footer alignment and the native time chooser. Advanced schedule modes, folder editing and actual destination information remain behind Schedule options; these capabilities were not deleted for visual matching.

Phone popups are edge-to-edge, bottom-aligned, square-cornered modal dialogs with a 48dp top reserve, top-right close button and separate scrolling middle/footer. Tablet popups retain a 512dp maximum and 16dp corners. They are not draggable drawers. Android Back, close, outside dismiss and Done preserve cancellation. The native window requests 32% dim and Android 12+ blur-behind; actual GPU/system support requires device acceptance. Foreground text stays sharp.

Archive details show Size, Exact bytes, Modified and Time display in divided two-column rows. Exact bytes come from the real integer size. Modification time remains device time, distinct from completion/schedule time. No per-archive file count is invented. The full-width outline Done action matches the phone reference.

The local-retention feature is a real extension of the existing setup schedule operation, guarded by the server capability. It validates all policy values before saving; invalid time or retention causes no write. Existing sources and retry settings are preserved. Source-selection review and manual backup still use saved server configuration rather than pretending to support ad hoc folder payloads.

Validation uses offline native journeys in both themes at phone/tablet widths, archive-sheet screenshot inspection, callback-only selector/cancellation tests, Python setup policy tests and web-console nonce/permission tests. No live backup, deletion or retention change is executed by these tests.

Final verification: 56 native tests and all 333 server tests passed. assembleDebug, testDebugUnitTest, lintDebug, APK signature verification and git diff --check passed. Lint reported 0 errors and 34 advisory warnings. Native screenshots were inspected at 320/390/768dp in dark/light modes, including the archive sheet.
