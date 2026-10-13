# Deploy checklist

- [ ] Back up the old SQLite database if it contains data you need.
- [ ] Confirm `DISCORD_TOKEN` is set in Render (not in GitHub).
- [ ] Confirm `OPENROUTER_API_KEY` is set in Render.
- [ ] Set `OWNER_ID` to the Discord user ID that manages events/polls.
- [ ] Optional: set `GUILD_ID` to Mahzen's server ID while testing.
- [ ] Enable Message Content Intent in Discord Developer Portal.
- [ ] Give the bot role permission to manage roles and place it above self-assignable roles.
- [ ] Set the correct Render start command: `uvicorn app:web --host 0.0.0.0 --port $PORT`.
- [ ] After deploy, inspect `/health`; look for `discord_connected: true`.
- [ ] Test `/yardim`, `/duyuru`, `/anket`, `/roller`, and `/profil` in a private test channel.
