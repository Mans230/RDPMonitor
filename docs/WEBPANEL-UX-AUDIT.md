# Web panel UX audit

Reviewed source at f85784d (not a live Windows deployment). Existing Node user-flow suite: 19/19 passing. Findings below are source-confirmed unless explicitly recommendations. No production settings were changed.

## Overall

The panel already has substantial functionality: responsive navigation, live health, backups and isolated restores, cloud setup, security controls, automation, personal operator authentication, CSRF and server confirmation nonces. The biggest opportunity is workflow clarity and operational feedback, not adding more command buttons.

## P1: Fix before expanding

1. **Direct links do not initialize many sections.** `webconsole_ui.html:939–1031,1586–1598`: initial hash selection changes visibility, but does not run `activateTab` loaders. Starting at `#users`, `#settings`, `#tools`, `#docs`, or `#rdpsec` can leave the section unpopulated until selected again. Initialize the selected route after authentication through one route entry function. Test refresh and login on every route.
2. **Security monitoring flags render blank regardless of state.** `webconsole_ui.html:1563`: both branches for `rdp_watch` and `net_watch` return empty strings. Render explicit Enabled/Disabled/Unknown labels; test true, false and missing data.
3. **Password reset uses a visible native prompt.** `webconsole_ui.html:1175–1179`: replace `prompt` with a masked password form, deliberate reveal control, validation and success-only clearing. Do not echo the password in confirmations or logs.
4. **Some read requests turn failures into apparently empty results.** `loadServices`, `loadNetstat`, `loadSec`, and `loadBackup` parse JSON without consistently checking HTTP status. For example, services can render an empty table from an error payload. Centralize authenticated fetch, preserve last successful data, label it stale, and provide inline Retry. Keep 401 handling consistent with action requests.
5. **Cloud selectors can stay stale after creating/removing a remote.** `setup.js:loadSetup`: remote cards refresh every load, but destination/client selectors refresh only on first load or explicit reset. Update selector options while preserving valid unsaved selections; avoid resetting unrelated edits.
6. **Panic-off confirmation describes the opposite effect.** `webconsole_ui.html:1123`: both on and off say the action closes RDP for everyone. Give each operation an accurate summary and expected post-action state.

## P2: Improve daily operation

- **Persistent operation center:** setup has jobs, but other actions mainly use transient toasts. Show requested/running/succeeded/failed/unknown, timestamps, initiating actor and relevant result links. Never equate request acceptance with completion. Reconcile after reconnect; do not automatically retry destructive requests.
- **Permission-aware controls:** `enterSession` shows actor identity but does not drive a capability-based interface. Disable unavailable controls with the reason and a route to settings where appropriate. Keep server authorization authoritative. Distinguish panel operators from Windows local users in navigation and copy.
- **Table usability:** processes show 25, apps 80, blocked IPs 100; services is labeled first 80. Add search, sort, pagination and visible shown/total counts rather than silent limits. Live refresh replaces process rows every two seconds: add pause updates and preserve focus/selection before destructive actions.
- **Service recovery:** service rows offer Restart and Stop, not Start. Add state-aware Start/Stop/Restart and refresh until the observed state changes or a clear timeout occurs.
- **Navigation:** route changes use `history.replaceState`, with no hash/popstate navigation handler. Support useful Back/Forward navigation. Consolidate overlapping Protection/RDP Security and Tools/Control workflows. Keep destructive actions in a clearly separated danger area.
- **Accessible dialogs:** process detail overlay lacks a full dialog lifecycle. Add dialog semantics, accessible title, initial focus, focus containment, Escape close and focus restoration. Apply the same discipline to the mobile drawer. Replace command prompts with consistent forms.
- **Charts:** provide keyboard/touch-readable values and a table/summary alternative; do not rely only on hover or color. Label timestamps and server timezone consistently.
- **Form protection:** show unsaved changes, warn before explicit reset/navigation, add per-field errors, and retain user input on failures. Setup already intentionally preserves many values during background refresh; retain that behavior.
- **Copy polish:** replace slash-command labels with task language while retaining command equivalents as optional help. Explain secure-default limitations beside disabled controls, not only after a failed request.

## Missing web-panel features worth building

1. **Actionable overview:** combine health with last backup success, next backup time, current access posture, active alerts and failed operations. Every warning should link to a relevant fix.
2. **Alert inbox:** active/resolved incidents, severity, acknowledgement, mute-until visibility, filterable history and notification delivery results. Existing settings/test messages are not a substitute for an incident workflow.
3. **Operator/access management:** owner-only operator listing, creation/revocation, explicit capabilities and active-session management. Operator CLI support already exists; this is a missing web workflow, not a missing backend concept.
4. **Audit explorer:** expose structured usage records with actor, outcome, date/action filters and export. `/api/usage` exists, while the current security view displays only the latest 50 legacy audit entries with Time/Action/Details.
5. **Backup confidence and restore wizard:** next run, per-destination outcome, verification age, drill result, source selection and restore-output location. Preview source/destination and disk-space requirements before starting; show verified completion afterward.
6. **Safer remote-access changes:** show current client IP, proposed allow-list impact, exact reconnect URL, certificate information and provider-firewall checklist. Consider a timed rollback with explicit connectivity confirmation for risky changes; implementation must preserve security rather than silently reopening access.
7. **First-run checklist:** permissions → backup sources → cloud account → connection test → schedule → first backup → restore drill → notification test. Mark missing prerequisites and allow resuming.
8. **Web-native diagnostics export:** offer redacted download/copy results where authorized, rather than requiring Telegram for export/file workflows. Keep download permissions explicit.

## Recommended delivery order

- Phase 1: route initialization, status-rendering bugs, masked passwords, reliable HTTP/error states, stale cloud selectors, accurate confirmations; add regression tests.
- Phase 2: operation feedback, permission-aware UI, searchable/state-aware tables, accessible dialogs and unsaved-change protection.
- Phase 3: overview/alerts, access management, audit explorer and guided backup/restore/onboarding.

## Validation still required

This audit did not launch the Windows panel, execute administrative actions, or visually verify responsive layouts. Run browser tests at desktop and narrow-mobile widths, keyboard-only/screen-reader checks, and simulated offline/401/403/500/slow-response cases. On a disposable Windows VM, verify backup/restore, service changes, access-mode restart/reconnect, port changes and rollback behavior. Existing 19 Node tests pass, but they do not establish end-to-end Windows or visual correctness.
