# Fedya · Mahzen

Minimal dark-green/black Discord community bot with `discord.py`, FastAPI, SQLite and OpenRouter.

## Included slash commands

- `/yardim` — command guide
- `/saat` — next planned event
- `/etkinlikler` — upcoming events
- `/duyuru` — create an event with RSVP buttons (owner/admin)
- `/iptal` — cancel a planned event (owner/admin)
- `/anket` — create a poll (owner/admin)
- `/anket_sonucu` — show poll results
- `/roller` — self-assign game-interest roles
- `/yoklama` — record attendance and points (owner/admin)
- `/profil` — member profile, attendance points and achievements
- `/siralama` — top attendance points

Fedya AI responds when mentioned in a server or when sent a DM. It does not read and answer every message.

## Required Render environment variables

| Variable | Required | Notes |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal. Keep secret. |
| `OPENROUTER_API_KEY` | For AI | OpenRouter key. Keep secret. |
| `OWNER_ID` | Recommended | Your Discord user ID. Server administrators can also use management commands. |
| `GUILD_ID` | Optional | Mahzen server ID. Set this for near-immediate slash command updates during setup. |
| `AI_MODEL` | No | Defaults to `openrouter/auto`; choose a model available to your OpenRouter account if needed. |
| `TIMEZONE` | No | Defaults to `Europe/Istanbul`. |
| `DATABASE_PATH` | No | Defaults to `data/mahzen.db`. |

Do not paste your bot token or OpenRouter key into chat or commit them to GitHub.

## Deploy to Render

1. Put these files in the GitHub repository's root.
2. In Render, create or update a **Web Service** connected to the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app:web --host 0.0.0.0 --port $PORT`
5. Add the environment variables above in Render's Environment page, then deploy.
6. Open `/health`. `status: ok` means the web service is running; `discord_connected: true` means the Discord gateway has connected.

`render.yaml` is a Blueprint reference. If you already have a live Render service, update its commands/environment instead of creating a second service unintentionally.

## Discord Developer Portal checklist

- Invite with the `bot` and `applications.commands` scopes.
- Grant only the permissions required by the channels/roles you use. For self-assign roles, enable **Manage Roles** and move Fedya's role above the game roles.
- Enable **Message Content Intent** in the bot settings for mention/DM AI replies.
- Ensure Fedya can view/send messages and embed links in the event/poll channels.

## Persistence note

SQLite works without a separate database service, but Render's ordinary filesystem may be reset during redeploys/restarts. If you need the database to survive, use a Render persistent disk (if available on your plan) and set `DATABASE_PATH` to a path on that disk, for example `/var/data/mahzen.db`, or migrate to a managed database. Back up the current database before replacing an existing deployment.

## Local run

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set environment variables (see .env.example); then:
uvicorn app:web --host 0.0.0.0 --port 10000
```

## Health check

- `GET /` — small status page
- `GET /health` — machine-readable status for Render

The health endpoint reports web-process health separately from Discord connection status, so a green Render health check cannot be mistaken for a connected bot.
