"""One-time helper to register (or delete) the Telegram webhook.

The bot must be a member of the discussion group for join events to arrive.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in the environment / .env.

Usage:
    python set_webhook.py https://your-app.onrender.com   # register
    python set_webhook.py --delete                        # remove
    python set_webhook.py --info                           # show current status
"""

import sys

import httpx

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--info":
        resp = httpx.get(f"{base}/getWebhookInfo", timeout=15)
        print(resp.json())
        return

    if arg == "--delete":
        resp = httpx.post(
            f"{base}/deleteWebhook", json={"drop_pending_updates": True}, timeout=15
        )
        print(resp.json())
        return

    if not settings.telegram_webhook_secret:
        print("TELEGRAM_WEBHOOK_SECRET is not set; refusing to register an "
              "unauthenticated webhook.")
        sys.exit(1)

    url = arg.rstrip("/") + "/telegram/webhook"
    payload = {
        "url": url,
        "secret_token": settings.telegram_webhook_secret,
        # We only act on new_chat_members service messages, which arrive as
        # ordinary "message" updates. Limiting allowed_updates avoids noise.
        "allowed_updates": ["message"],
    }
    resp = httpx.post(f"{base}/setWebhook", json=payload, timeout=15)
    print(resp.json())


if __name__ == "__main__":
    main()
