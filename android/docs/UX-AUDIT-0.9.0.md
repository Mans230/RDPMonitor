# Native UI/UX audit and contextual actions â€” 0.9.0

This audit follows the approved CONTEXTUAL-ACTIONS-SPEC.md from the design thread. It applies pstack's Experience First, Model the Domain, Fix Root Causes and Prove It Works principles. The implementation is native Compose; the HTML is a reference, not a replacement for authentication or server APIs.

## Findings corrected

1. **Back could display Google sign-in while already signed in.** Explicit Welcome, SignIn, Servers, Account and Connection routes replace the independent inside/page flags. Cold launch starts at Welcome; a valid cached account continues to its saved servers. Back does not sign out or invoke Google again. Pending browser callbacks and restored activity routes retain their existing handling.
2. **Saved servers were hidden behind a form icon.** Account has Server connections; the header host selector opens the same directory. Your servers has an attached Add control. Each server's sheet contains Reconnect and confirmed Remove; the selected connection owns Disconnect. Sign out belongs to Account ? App access and has a separate confirmation.
3. **Disconnect retained server-scoped data.** The transport now cancels its refresh/document/diagnostic work and clears selected profile, observations, cached documents/errors, results, open operation/review, form/diagnostic inputs and pairing data. Google sign-in and persisted profiles remain. Navigation is controlled by workspace context, not by keeping a snapshot alive. Monitoring routes after disconnect show an honest disconnected state.
4. **Cached identity could disagree with profile ownership.** A cached Google subject is accepted only if it matches connector_owner. A mismatch requires the existing real authentication flow. No owner is reassigned to reconcile it and no database is reset. Profiles remain isolated by the existing hashed account namespace on this device; this is not cross-device cloud synchronization.
5. **Reconnect could be unclear about scope.** Saved reconnect reuses only an unexpired session bound to the exact saved profile and private origin, preserving an already-approved scope. Missing, expired or foreign sessions fall back to monitoring and the existing browser approval flow. New server setup does not silently grant administration.
6. **Long collections expanded entire pages.** Processes, saved servers, archive/source collections, recorded events and large contextual inventories have bounded native scrolling. Process selection uses exact PID/name identities; search/filter changes clear hidden selections. Review controls remain attached to their collection and bottom navigation retains reserved clearance.
7. **Page ends contained generic Actions and repeated raw Show disclosures.** Every catalog control now has a named owning section. Recognized response schemas use contextual fields. Unknown returned fields remain available once from Diagnostics ? Report details with original response paths, server and available timestamps/errors; existing secret redaction applies. The sheet closes on server changes and its source documents clear on disconnect/sign-out. Detailed operation results stay in their result sheet.
8. **More duplicated navigation as oversized loose buttons.** More is now a searchable grouped directory with labeled chevrons. Account, Network & bandwidth and Activity are rows in their groups. There is no page-end Server connections/Bandwidth/Activity/Sign-out board.
9. **Activity collapsed distinct records and omitted useful context.** Real audit records retain individual details, available actor and full device-local date/time. Operation usage belongs to Activity summary, not unrelated Settings/Maintenance footers. The server still determines retention and returned history.
10. **Bandwidth could describe a real unknown window as a sample window.** Recorded usage and Billing window are separate sections. Missing dates stay unavailable. Existing ledger totals, billing bounds, scope and binary units remain unchanged; no missing records are invented as measured zero.
11. **Long values and large text could crowd controls.** Metric rows reserve label/value columns; coss buttons can grow vertically instead of fixing their height. Onboarding Back/theme actions have 44dp targets. Narrow and larger-text journeys exercise last-row access and form/page scrolling.

## Page and control inventory

| Page | Data/control owner and disposition |
| --- | --- |
| Welcome / Google | Separate pages, real Google provider, cancellation/late-result guard; no demo/private bypass |
| Add server | Validated private HTTPS form; browser approval code/scope and existing Passkey/PKCE; Back returns to saved connections |
| Account | Your account ? Server connections/Appearance; App access ? confirmed account sign-out |
| Server connections | Your servers header Add; per-server sheet Reconnect/confirmed Remove; Selected connection Disconnect |
| Overview | CPU, memory, storage, uptime and latest backup health only; no feature content appended beneath it |
| Protection | Addresses owns block/unblock/subnet; Access policy owns lockdown/panic; Account traps owns trap management |
| RDP & users | Connection policy owns port/allowlist; Remote sessions owns logoff/message; Windows accounts owns user changes |
| Local users | Windows accounts inventory and reviewed account management |
| Backups | Backup policy footer saves schedule/retention; Source folders owns selection/edit/manual backup; selected archive sheet owns exact-name restore; Latest backup result owns the server-configured verification drill; cloud destination navigation stays in Cloud destinations |
| Cloud & images | Cloud storage owns sign-in/remotes/credentials; uncommon controls collapse locally; System image owns create/upload/stop/link; Cloud destinations owns targets/test |
| Processes | Search/filter/list with bounded scrolling; exact-PID details; selection review inside collection; protected processes and capability checks retained |
| Resource history | Existing recorded observations and gaps retained; separate route |
| Command center | Command input/execution remains; service/program/process/recovery/maintenance duplicates become navigation to their dedicated owners |
| System tools | Services owns service management; Programs owns program start; host facts stay in System information |
| Automation | Recovery rules owns existing process/service rule inventory and add/remove form |
| Updates | Suite updates owns check/install; Update policy owns automatic update configuration |
| Settings & alerts | Monitoring policy owns server-labeled editable settings; Alert delivery owns mute/resume/test; Advanced settings owns key/value editing |
| Private access | Private panel facts and authorized app sessions; revocation remains attached to its session record and reviewed |
| Diagnostics | Report selection form owns run/report controls; redacted Report details is the fallback for unrecognized response fields |
| Maintenance | Cleanup owns temporary-file cleanup; Logs & files owns export/send; Power controls owns restart/shutdown/cancel |
| Command reference | Server-returned command documentation; no invented controls |
| Network & bandwidth | Recorded usage, Billing window, Daily transfer/ledger and measurement quality use actual records |
| Activity | Individual recorded events and local date/time; optional operation summary belongs here |
| More | Searchable Monitor/Protect/Store & recover/Manage/Account directory; no loose footer buttons |

## Verification and limits

Run `powershell -NoProfile -File android/scripts/check-app.ps1` for assembleDebug, unit/native journeys and lintDebug. Test outputs are under app/build/reports/tests and native PNGs under app/build/reports/app-journeys. AppJourneyTest traverses every Feature at 320/390/768dp in dark/light, including return navigation and fixed dock clearance. GoogleEntryJourneyTest uses an injected provider boundary to check startup/Back, saved profile ownership, account switching, mismatch handling and confirmed removal. AccountStateTest checks reconnect binding/scope, complete disconnected-state cleanup and an explicit owner for every catalog control. Long-list and 1.5x text tests use offline fixtures, including the final PID and saved server; the report test checks unknown fields/redaction and closes the sheet on a server change.

These checks do not claim real Google chooser, actual saved-session transport/Passkey acceptance, Tailscale reachability, hardware keyboard/IME, system photo picker or GPU glass/blur acceptance. No live host actions are used by the tests. No production data, credentials, passkeys, database migration or destructive reset is part of this change. APK package/signing continuity is checked separately before delivery.

## Verified artifact

Local final check: assembleDebug, all 77 tests and lintDebug passed; lint reports 0 errors and 38 advisory warnings. Screenshots were regenerated for all 16 feature destinations at 320/390/768dp in dark/light, plus onboarding, account/server routes, archive details and 1.5x text/long-list cases. The audit covers the 25 routes including entry and workspace pages. Native contact sheets are generated review artifacts, not live server screenshots.

APK: artifacts/RDPMonitor-Android-0.9.0-contextual.apk, versionCode 12, package io.github.mans230.rdpmonitor.dev. SHA-256: D0AB788002C173F64FF12CDF7186887B9A32C2466BB755BF2FF910ABA9DBCEB0. Signing SHA-1 remains C6:DE:96:B0:AC:1A:3D:7C:21:11:33:E9:7F:1D:9A:6C:CB:18:19:1F. GitHub CI/merge status is reported separately; these are local verification results.
