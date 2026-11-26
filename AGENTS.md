# Private-panel authentication development

Develop and test Tailscale Serve and Passkeys in this clone. The user has given
standing authorization to ship future features to production after automated
checks and will perform device acceptance themselves. Do not ask again for
routine production rollout approval. Keep rollback checkpoints and verify health.
Main releases may be consumed automatically by
production. Never commit production secrets or runtime data. Keep test data under
ignored test-runtime/. Verify private access before closing the public route.
The runner must never execute host-management actions or start the Telegram bot.
