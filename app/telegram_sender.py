"""Telegram message sending via the Bot API (HTTP)."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramSendError(Exception):
    """Raised when a message could not be delivered."""


async def send_chat_message(
    chat_id: str | int,
    text: str,
    parse_mode: str | None = None,
    message_thread_id: int | None = None,
    disable_web_page_preview: bool = True,
) -> dict:
    """Send `text` to `chat_id` using the Telegram Bot API.

    `chat_id` may be a numeric id (channel/group/user) or a public "@username".
    `parse_mode` is "HTML"/"MarkdownV2" or None for plain text. Returns a dict
    describing the outcome, or raises TelegramSendError.
    """
    settings = get_settings()

    # The bot token is a secret and lives only in this URL. Keep it out of all
    # log/error text: httpx exception messages and tracebacks can embed the
    # request URL, so on failure we surface the exception *type*, never `exc`.
    url = f"{API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
        data = resp.json()
    except httpx.HTTPError as exc:
        raise TelegramSendError(
            f"Telegram request failed ({type(exc).__name__})"
        ) from None
    except ValueError:
        raise TelegramSendError(
            f"Telegram returned a non-JSON response (HTTP {resp.status_code})"
        ) from None

    # The Bot API always returns {"ok": bool, ...}. On failure it carries
    # error_code/description instead of result, so report that cleanly rather
    # than letting a missing "result" key become a 500.
    if not data.get("ok"):
        raise TelegramSendError(
            f"Telegram API error {data.get('error_code')}: {data.get('description')}"
        )

    message_id = data["result"]["message_id"]
    logger.info("Sent message id=%s to %s", message_id, chat_id)
    return {"sent": True, "message_id": message_id, "target": str(chat_id)}


async def delete_chat_message(chat_id: str | int, message_id: int) -> bool:
    """Delete a previously sent message. Returns True, or raises TelegramSendError.

    A bot can delete its own messages in groups/supergroups without admin rights,
    but only within 48 hours of sending.
    """
    settings = get_settings()

    url = f"{API_BASE}/bot{settings.telegram_bot_token}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
        data = resp.json()
    except httpx.HTTPError as exc:
        raise TelegramSendError(
            f"Telegram request failed ({type(exc).__name__})"
        ) from None
    except ValueError:
        raise TelegramSendError(
            f"Telegram returned a non-JSON response (HTTP {resp.status_code})"
        ) from None

    if not data.get("ok"):
        raise TelegramSendError(
            f"Telegram API error {data.get('error_code')}: {data.get('description')}"
        )

    logger.info("Deleted message id=%s from %s", message_id, chat_id)
    return True


async def send_message(message: str) -> dict:
    """Send `message` to the configured channel using the Telegram Bot API.

    The bot (from @BotFather) must be an admin of the target channel with the
    "Post Messages" permission. The target is a channel chat id like
    "-1004341050758" or a public "@username".
    """
    return await send_chat_message(get_settings().telegram_target_group, message)
