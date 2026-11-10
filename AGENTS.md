# Private-panel authentication development

Develop and test Tailscale Serve and Passkeys in this clone. Production rollout
requires an explicit user request; the current user has requested tests, a PR,
and an update after validation. Main releases may be consumed automatically by
production. Never commit production secrets or runtime data. Keep test data under
ignored test-runtime/. Verify private access before closing the public route.
The runner must never execute host-management actions or start the Telegram bot.
