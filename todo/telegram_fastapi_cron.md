# FastAPI Telegram Cron Plan

## Goal

Create a FastAPI endpoint that sends a message to a public Telegram group using a Telegram user account with `api_id` and `api_hash`. Start with a public dummy group, then switch to the real Singapore Badminton group after validation. A cron job will trigger the endpoint every hour.

## Assumptions

- The dummy Telegram group is public and has a username, for example `@badminton_test_group`.
- The Telegram account used by the app is a member of the target group.
- The target group allows that account to send messages.
- The implementation will use Telethon because it supports Telegram user login with `api_id` and `api_hash`.
- The hourly cron job will call the FastAPI endpoint over HTTP.

## Step 1: Prepare Telegram Credentials

1. Create or confirm Telegram API credentials at `https://my.telegram.org`.
2. Collect the following values:
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`
   - `TELEGRAM_TARGET_GROUP`
   - `CRON_SECRET`
3. Use the dummy public group username first:

```env
TELEGRAM_TARGET_GROUP=@badminton_test_group
```

## Step 2: Add Runtime Configuration

1. Add environment variable support.
2. Store secrets in `.env` or deployment environment variables.
3. Ensure `.env` and Telegram session files are ignored by version control.

Example values:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_NAME=telegram_session
TELEGRAM_TARGET_GROUP=@badminton_test_group
CRON_SECRET=replace_with_long_random_secret
```

## Step 3: Install Dependencies

1. Add FastAPI dependencies if missing.
2. Add Telethon for Telegram user-account messaging.
3. Add dotenv support if the project does not already load environment variables.

Expected packages:

```bash
pip install fastapi uvicorn telethon python-dotenv
```

## Step 4: Create One-Time Telegram Login Script

1. Create a script to initialize a Telethon session.
2. Run the script manually once.
3. Enter the Telegram phone number, login code, and 2FA password if required.
4. Persist the generated `.session` file on the server.
5. Do not commit the `.session` file.

Expected result:

```text
telegram_session.session
```

## Step 5: Create Telegram Sender Module

1. Create a small module responsible for Telegram communication.
2. Load `api_id`, `api_hash`, session name, and target group from environment variables.
3. Connect with Telethon using the saved session.
4. Send the message to `TELEGRAM_TARGET_GROUP`.
5. Return a clear success or error result.

## Step 6: Create FastAPI Endpoint

1. Add a `POST /telegram/send` endpoint.
2. Accept a JSON body with a `message` field.
3. Require an authorization header:

```http
Authorization: Bearer your_cron_secret
```

4. Reject requests with missing or invalid tokens.
5. Reject empty messages.
6. Call the Telegram sender module.
7. Return a response indicating whether the message was sent.

Example request body:

```json
{
  "message": "Test message from FastAPI to dummy badminton group"
}
```

## Step 7: Test Manually

1. Start the FastAPI app locally.
2. Send a manual test request with `curl`.
3. Confirm the message appears in the dummy Telegram group.
4. Check API logs for any Telethon connection or permission issues.

Example request:

```bash
curl -X POST http://localhost:8000/telegram/send \
  -H "Authorization: Bearer your_cron_secret" \
  -H "Content-Type: application/json" \
  -d '{"message":"Test message from FastAPI to dummy group"}'
```

## Step 8: Add Hourly Cron Trigger

1. Add a cron entry that calls the endpoint every hour.
2. Use the same secret token as the API expects.
3. Keep the message text configurable if it may change later.

Example cron entry:

```cron
0 * * * * curl -X POST http://localhost:8000/telegram/send -H "Authorization: Bearer your_cron_secret" -H "Content-Type: application/json" -d '{"message":"Hourly badminton group message"}'
```

## Step 9: Move From Dummy Group To Real Group

1. Confirm the dummy group test works reliably.
2. Confirm the Telegram account can post in the real Singapore Badminton group.
3. Replace only this environment variable:

```env
TELEGRAM_TARGET_GROUP=@real_singapore_badminton_group
```

4. Restart the FastAPI service if required.
5. Send one manual test request before enabling the real hourly cron.

## Step 10: Production Hardening

1. Run FastAPI behind HTTPS in production.
2. Use a strong `CRON_SECRET`.
3. Restrict endpoint access by IP if the cron server has a stable IP.
4. Keep Telegram credentials and session files outside version control.
5. Persist the `.session` file across deployments.
6. Add logs for successful sends and failed sends.
7. Consider rate limits and avoid triggering the endpoint too frequently.

## Verification Checklist

1. Dummy public group exists and has a username.
2. Telegram account is a member of the dummy group.
3. One-time Telethon login generated a session file.
4. FastAPI starts without configuration errors.
5. Unauthorized requests are rejected.
6. Empty messages are rejected.
7. Valid requests send a Telegram message.
8. Cron triggers the endpoint every hour.
9. Switching `TELEGRAM_TARGET_GROUP` sends to the real group without code changes.
