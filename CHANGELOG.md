# Changelog

## Rebuild review pass

- Added a Discord gateway supervisor so startup/login failures are logged and retried instead of leaving a healthy-looking web process with an offline bot.
- Expanded `/health` with `discord_task_running` and a sanitized `discord_last_error` diagnostic.
- Made `/anket` defer the interaction before posting its channel message, avoiding Discord interaction timeouts during slower requests.
- Added validation for blank poll questions.
- Preserved all 11 original slash command names and persistent event/poll views.
