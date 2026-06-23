# Badminton Telegram Cron

A FastAPI endpoint that posts a message to a Telegram channel using a
**Telegram Bot** (from [@BotFather](https://t.me/BotFather)). An external cron
job calls the endpoint on a schedule. Because a bot — not a personal account —
does the posting, there is no `api_id`/`api_hash`, no login flow, and no session
string to manage or refresh.

All sensitive details live in `.env` (git-ignored). See `.env.example`.

## Layout

```
app/config.py           # loads secrets from .env / env vars
app/game_post_form.py   # /post form state and create-game payload rendering
app/telegram_sender.py  # Bot API send logic (httpx -> api.telegram.org)
app/telegram_welcome.py # builds the welcome message for new group members
app/upmatches_api.py    # Upmatches API client for /post game creation
app/venue_matcher.py    # venue text matching using OpenAI + venue records
app/youform.py          # fetches the live survey submission count
app/main.py             # FastAPI app + POST /telegram/send + POST /telegram/webhook
set_webhook.py          # one-time helper to register/delete the Telegram webhook
render.yaml             # Render free-tier Blueprint
.python-version         # Python runtime for FastAPI Cloud
.env / .env.example     # configuration
survey_message.txt      # reference survey message
payload.json            # empty body that triggers a random survey template
```

## 1. Create the bot and add it to the channel

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow the prompts.
   Copy the **bot token** it gives you (looks like `123456:ABC-DEF...`).
2. Open your channel → **Administrators** → **Add Admin** → add your bot and
   grant it **Post Messages**.
3. Find the channel chat id. For a private channel it has the form
   `-100…` (e.g. `-1004341050758`); a public channel can use `@username`.

## 2. Configure

```bash
cp .env.example .env     # then fill in real values
```

Generate a strong cron secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # -> CRON_SECRET
```

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | bot token from @BotFather |
| `TELEGRAM_TARGET_GROUP` | channel chat id (`-100…`) or public `@username` |
| `CRON_SECRET` | Bearer token the endpoint requires |
| `TELEGRAM_DEFAULT_MESSAGE` | fallback if no built-in survey template exists |
| `YOUFORM_API_TOKEN` | fetches the live submission count appended to messages |
| `TELEGRAM_WEBHOOK_SECRET` | secret for `/telegram/webhook` (welcome-on-join); empty disables it |
| `TELEGRAM_WELCOME_MESSAGE` | *(optional)* override the built-in welcome text; `{name}` = mention |
| `TELEGRAM_HUB_GROUP` | group where `/post` publishes created games, e.g. `@upmatcheshub` |
| `TELEGRAM_GAME_POST_TOPIC_ID` | topic id for `Organizers & Find Players` |
| `UPMATCHES_API_BASE_URL` | Upmatches API base URL, default `https://api.upmatches.com` |
| `UPMATCHES_BOT_SERVICE_CLIENT_ID` | bot service-client id for creating games |
| `UPMATCHES_BOT_SERVICE_CLIENT_SECRET` | bot service-client secret |
| `UPMATCHES_BOT_SERVICE_TOTP_SECRET` | bot service-client TOTP secret |
| `OPENAI_API_KEY` | optional but recommended for AI venue matching |
| `OPENAI_VENUE_MATCH_MODEL` | model used to rank venue matches |

## 3. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 5. Test

```bash
curl -X POST http://localhost:8000/telegram/send \
  -H "Authorization: Bearer <CRON_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Test message from FastAPI"}'
```

- Missing/invalid token → `401` / `403`.
- Empty message → `400`.
- Bot not admin / wrong chat id → `502` with the Telegram error description.
- Success → `{"sent": true, "message_id": ..., "target": "..."}`.

## 6. External cron service

The schedule is driven by an external cron service (e.g. cron-job.org, EasyCron,
GitHub Actions). Configure it to send an HTTP request:

- **Method:** `POST`
- **URL:** `https://<your-host>/telegram/send`
- **Headers:** `Authorization: Bearer <CRON_SECRET>`, `Content-Type: application/json`
- **Body:** the contents of `payload.json` (`{}` triggers a random survey template)

To send one random survey template from the command line:

```bash
curl -X POST http://localhost:8000/telegram/send \
  -H "Authorization: Bearer <CRON_SECRET>" \
  -H "Content-Type: application/json" \
  --data @payload.json
```

To override the random templates and send one exact message:

```bash
curl -X POST http://localhost:8000/telegram/send \
  -H "Authorization: Bearer <CRON_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"message":"One exact message"}'
```

## 7. Change the target channel

Change only this line in `.env`, then restart the service:

```env
TELEGRAM_TARGET_GROUP=-1004341050758
```

Make sure the bot is an admin of whatever channel you point it at. Send one
manual test before enabling the cron schedule.

## 8. Deploy to FastAPI Cloud

FastAPI Cloud can auto-detect this app at `app/main.py`. The project includes:

- `requirements.txt` with `fastapi[standard]` for the FastAPI Cloud CLI.
- `.python-version` pinned to Python 3.12.
- `.gitignore` entries that keep `.env` and `.venv/` out of uploads.

### 8.1 Set FastAPI Cloud environment variables

In the FastAPI Cloud dashboard for this app, add these environment variables.
Mark sensitive values as secrets.

| Env var | Secret? | Source |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes | from @BotFather |
| `TELEGRAM_TARGET_GROUP` | No | e.g. `-1004341050758` |
| `CRON_SECRET` | Yes | your long random secret |
| `TELEGRAM_DEFAULT_MESSAGE` | No | fallback message text |
| `YOUFORM_API_TOKEN` | Yes | YouForm API token |
| `TELEGRAM_WEBHOOK_SECRET` | Yes | welcome-on-join webhook secret (Section 10) |

You can also set them from the CLI:

```bash
fastapi cloud env set --secret TELEGRAM_BOT_TOKEN "<value>"
fastapi cloud env set TELEGRAM_TARGET_GROUP "-1004341050758"
fastapi cloud env set --secret CRON_SECRET "<value>"
fastapi cloud env set TELEGRAM_DEFAULT_MESSAGE "Fallback badminton survey message"
fastapi cloud env set --secret YOUFORM_API_TOKEN "<value>"
```

> Note: `env set` on an existing key returns HTTP 400 — `env delete <KEY> --yes`
> first, then `set`. Values starting with `-` (e.g. the channel id) are parsed as
> CLI flags, so pass them via stdin: `printf '%s' "-1004341050758" | fastapi cloud
> env set TELEGRAM_TARGET_GROUP --value-stdin`. Env changes take effect only after
> a redeploy.

### 8.2 Deploy

From the project root:

```bash
fastapi login
fastapi deploy
```

If FastAPI Cloud asks which app to use, choose the app you registered. After the
first successful deploy, the CLI writes a local `.fastapicloud/` link so future
deploys can use `fastapi deploy` directly.

### 8.3 Test the deployed URL

```bash
curl -X POST https://<app>.fastapicloud.dev/telegram/send \
  -H "Authorization: Bearer <CRON_SECRET>" \
  -H "Content-Type: application/json" \
  --data @payload.json
```

Then point your external cron service (Section 6) at that HTTPS URL.

## 9. Deploy to Render (free tier)

The free Web Service has an ephemeral filesystem, but the bot needs no local
state — only environment variables.

### 9.1 Push the project to GitHub

`.gitignore` already excludes `.env`, so no secrets are pushed.

```bash
git init && git add -A && git commit -m "Telegram survey sender"
gh repo create badminton-survey-app --private --source=. --push
```

### 9.2 Create the service on Render

New → **Blueprint** → connect the repo. Render reads `render.yaml` and creates a
free Web Service, prompting for these secret env vars (marked `sync: false`):

| Env var | Source |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_TARGET_GROUP` | e.g. `-1004341050758` |
| `CRON_SECRET` | your long random secret |
| `TELEGRAM_DEFAULT_MESSAGE` | fallback message text |
| `YOUFORM_API_TOKEN` | YouForm API token |
| `TELEGRAM_WEBHOOK_SECRET` | welcome-on-join webhook secret (Section 10) |

### 9.3 Test the deployed URL

```bash
curl -X POST https://<service>.onrender.com/telegram/send \
  -H "Authorization: Bearer <CRON_SECRET>" \
  -H "Content-Type: application/json" \
  --data @payload.json
```

Then point your external cron service (Section 6) at that HTTPS URL.

### Free-tier notes

- **Cold starts:** the service sleeps after ~15 min idle; the next request takes
  ~50s. Set the cron request timeout to ≥60s, or hit `/health` a minute earlier
  to pre-warm.
- **Render Cron Jobs are paid** — but scheduling is handled by an *external* cron
  service, so only the free Web Service is needed.
- Rotate `CRON_SECRET` if it has ever been shared (update the env var on Render).

## 10. Welcome new members (discussion group)

`POST /telegram/webhook` greets each person who joins, with a clickable mention.
Telegram **does not** deliver join events for *channels* and bots cannot DM
channel subscribers — so this works only in a **group**: either a standalone
group or the **discussion group** linked to the channel for comments.

### 10.1 One-time Telegram setup (do this in the mobile/desktop app)

Linking a discussion group is reliable in the Telegram apps but flaky on
`web.telegram.org`, so use the app:

1. Open `@upmatcheshub` → **Edit** (pencil) → **Discussion** → create or link a
   group.
2. Add your bot to that group. **Member** is enough to receive join events; admin
   also works.

### 10.2 Configure and register the webhook

1. Set a secret (same value in your env and at Telegram):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"   # -> TELEGRAM_WEBHOOK_SECRET
   ```

   Add `TELEGRAM_WEBHOOK_SECRET` to your host (Render/FastAPI Cloud) and redeploy.

2. Register the webhook once (the public URL of your deployed service):

   ```bash
   python set_webhook.py https://<your-host>          # register
   python set_webhook.py --info                        # show current status
   python set_webhook.py --delete                      # remove it
   ```

   `set_webhook.py` reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` from
   the environment / `.env` and registers `https://<your-host>/telegram/webhook`
   with `allowed_updates: ["message"]`.

### 10.3 How it behaves

- Telegram echoes the secret in the `X-Telegram-Bot-Api-Secret-Token` header;
  calls without the correct value get `403`. An **empty** secret disables the
  endpoint (every call is rejected).
- Each non-bot in a join event gets one welcome; bots (including this one being
  added) are skipped. The route always returns `200` so Telegram does not retry
  and re-welcome.
- Organizers can send `/post` in the group to start a guided game-creation form.
  The bot matches their free-text venue against live Upmatches venues, asks them
  to pick one of the top matches, collects the Create Game fields, previews the
  payload, then creates the game after they reply `confirm`.
- `/post` needs `UPMATCHES_BOT_SERVICE_CLIENT_ID`,
  `UPMATCHES_BOT_SERVICE_CLIENT_SECRET`, and
  `UPMATCHES_BOT_SERVICE_TOTP_SECRET` to create the game. Without
  `OPENAI_API_KEY`, venue matching falls back to deterministic text matching.
- The welcome **auto-deletes after `TELEGRAM_WELCOME_TTL_SECONDS` (default 60)**
  so it doesn't clutter the group — the joiner still gets the notification. The
  delete runs as a background task, so the webhook still returns immediately. A
  bot can delete its own messages without admin rights (within 48h). Set the TTL
  to `0` to keep welcomes permanently.
- Customise the text with `TELEGRAM_WELCOME_MESSAGE`; `{name}` becomes a clickable
  mention. Keep other text free of unescaped `<`, `>`, `&` (it is sent as HTML).

### 10.4 Free-tier caveat

On Render free tier the service sleeps after ~15 min idle. A join then triggers a
cold start (~50s); Telegram may time out and retry, so the first welcome after
idle can be delayed or, rarely, missed. An always-on (paid) plan removes this.

If normal joins fire welcomes but invite-link/comment joins in a large group do
not, switch from `new_chat_members` to `chat_member` updates (needs the bot to be
**admin** and `allowed_updates: ["chat_member"]`).

## Production hardening

- Run behind HTTPS.
- Use a long random `CRON_SECRET`; restrict by source IP if the cron host is stable.
- Keep `.env` out of version control.
- Treat `TELEGRAM_BOT_TOKEN` like a password; rotate it in @BotFather (`/revoke`)
  if it leaks.
- Logs record successful and failed sends (`logging` at INFO).
- Avoid triggering more frequently than needed to respect Telegram rate limits.
