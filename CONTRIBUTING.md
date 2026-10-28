# Contributing

Use a topic branch and a pull request for every new change, including follow-up
fixes and documentation. Do not commit directly to the default branch. Keep the
active installed suite separate from development.

Start from the current default branch in an isolated checkout. Write regression
tests that reproduce defects before changing behavior. Do not run live account,
firewall, power or installation actions as tests on the working server. Never
commit runtime state, tokens, Telegram session files, local snapshots or journals.

PRs should state behavior changes, compatibility requirements, checks run and
remaining VM/deployment validation. Update related docs and generated command
reference. Follow [validation and rollback](docs/VALIDATION.md); passing unit tests
does not replace Windows VM verification. Keep deployment/merge decisions visible.
