# UX corrections — Android 0.4.0

Addresses the source-traced review of 0.3.0. Physical phone acceptance remains
with the owner; the review did not involve a connected Android device.

- **Page switching:** each route gets a fresh scroll position; a section's title
  and Back control remain in the fixed header. Rotation retains the current
  route's saved list position.
- **System Back:** sections return to tools, root tabs return to Overview, and
  Back on Overview follows Android's normal exit behavior. Server selection
  still provides Back to monitor without signing out.
- **Operation feedback:** preparation, execution and outcome use a visible
  native dialog identifying the server. Users can continue in the background;
  a fixed progress/result control remains available across tabs. No writes retry
  automatically.
- **Pairing:** monitoring-only and administration are explicit choices. Their
  wording matches browser consent. The pairing code is shown and copyable before
  the user selects Continue in browser. Pending handoffs have Cancel and expiry,
  and are stored encrypted for process recovery.
- **Permission upgrade/recovery:** the current server is reused for management
  approval or Sign in again; the connection form prefills its address. Selecting
  another saved profile highlights it and returns to the form.
- **Diagnostics:** independent read jobs survive unrelated page reloads. The
  selected report, argument and results remain available across page switches;
  progress is visible and report names/parameter hints are readable.
- **Session expiry:** readings are explicitly marked stale, management is
  disabled, and a fixed Sign in again action is provided. Network failures show
  Retry without pretending an old reading is live.
- **Form retention:** active drafts live in the ViewModel across rotation. They
  are cleared on dismissal and are never serialized as private form data.
  Dangerous choices require an explicit selection; risky actions are marked.
- **Data presentation:** health/install booleans have meaningful labels; byte
  sizes and timestamps are human-readable. Setup data is projected into Backups,
  Cloud, or Access rather than repeated wholesale. Deep details have a working
  expand control.
- **Demo:** every management section has explicitly labelled sample data, while
  its network and mutation controls remain disabled.
- **Sign out:** a confirmation explains the effect and that an existing
  approved Passkey can be reused. A new Telegram key approval is not implied.
- **Other corrections:** process search, explanations for protected system
  processes, accurate file-picker labels, consistent destination field labels
  and a labelled Servers control.

The report's suggested cross-server cache leak was not reproducible through the
normal server selector because it already cleared caches. Connection start now
also explicitly clears cached documents, errors, results and pending reviews as
defense in depth.

Automated coverage includes root Back policy, expired-session state, permission
wording, size/date formatting, deliberately unselected destructive choices,
section projection and demo coverage, in addition to the existing authentication,
confirmation, provider-input and billing tests. These checks do not replace
physical Android navigation, keyboard and authenticator acceptance.
