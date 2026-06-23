"""FastAPI app exposing the cron-triggered Telegram send endpoint."""

import asyncio
import logging
import random
import re
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.game_post_form import (
    DEFAULT_SKILL_LEVELS,
    GamePostFormError,
    GamePostSession,
    build_game_payload,
    current_prompt,
    format_created_post,
    record_answer,
    select_venue,
    set_venue_matches,
    start_game_post_session,
)
from app.telegram_sender import (
    TelegramSendError,
    delete_chat_message,
    send_chat_message,
    send_message,
)
from app.telegram_welcome import build_welcome
from app.upmatches_api import UpmatchesApiClient, UpmatchesApiError
from app.venue_matcher import VenueMatchError, match_venues
from app.youform import YouformError, get_submission_count

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Badminton Telegram Cron")

# Keep strong references to in-flight delete tasks so the event loop does not
# garbage-collect them before they run; they remove themselves when done.
_pending_deletes: set[asyncio.Task] = set()
_game_post_sessions: dict[tuple[int, int], GamePostSession] = {}


def _message_thread_id(message: dict) -> int | None:
    thread_id = message.get("message_thread_id")
    return thread_id if isinstance(thread_id, int) else None


def _telegram_name(user: dict) -> str:
    if user.get("username"):
        return f"@{user['username']}"

    name_parts = [
        user.get("first_name") or "",
        user.get("last_name") or "",
    ]
    return " ".join(part for part in name_parts if part).strip() or "Organizer"


async def _send_game_form_prompt(
    chat_id: int,
    text: str,
    message_thread_id: int | None,
) -> None:
    await send_chat_message(
        chat_id,
        text,
        message_thread_id=message_thread_id,
    )


async def _handle_game_post_form(message: dict, settings: Settings) -> None:
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    sender = message.get("from") or {}
    user_id = sender.get("id")
    thread_id = _message_thread_id(message)

    if not text or chat_id is None or user_id is None or sender.get("is_bot"):
        return

    session_key = (chat_id, user_id)
    command = text.split()[0].split("@")[0].lower()

    if command == "/cancel" and session_key in _game_post_sessions:
        _game_post_sessions.pop(session_key, None)
        await _send_game_form_prompt(chat_id, "Game post form cancelled.", thread_id)
        return

    if command == "/post":
        session = start_game_post_session(_telegram_name(sender))
        _game_post_sessions[session_key] = session
        await _send_game_form_prompt(
            chat_id,
            "🏸 Game post form started.\n"
            "Answer each question in a new message. Send `/cancel` anytime to stop.\n\n"
            f"{current_prompt(session)}",
            thread_id,
        )
        return

    session = _game_post_sessions.get(session_key)
    if session is None:
        return

    api = UpmatchesApiClient()

    if session.state == "venue":
        await _handle_venue_answer(session, text, chat_id, thread_id, api)
        return

    if session.state == "venue_choice":
        try:
            select_venue(session, text)
        except GamePostFormError as exc:
            await _send_game_form_prompt(chat_id, str(exc), thread_id)
            await _send_game_form_prompt(chat_id, current_prompt(session), thread_id)
            return
        await _send_game_form_prompt(chat_id, current_prompt(session), thread_id)
        return

    if session.state == "confirm":
        await _handle_confirmation(
            session_key,
            session,
            text,
            chat_id,
            thread_id,
            settings,
            api,
        )
        return

    try:
        skill_levels = await _skill_levels(api)
        record_answer(session, text, skill_levels)
    except (GamePostFormError, UpmatchesApiError) as exc:
        await _send_game_form_prompt(chat_id, str(exc), thread_id)
        await _send_game_form_prompt(chat_id, current_prompt(session), thread_id)
        return

    await _send_game_form_prompt(chat_id, current_prompt(session), thread_id)


async def _handle_venue_answer(
    session: GamePostSession,
    text: str,
    chat_id: int,
    thread_id: int | None,
    api: UpmatchesApiClient,
) -> None:
    try:
        venues = await api.list_venues()
        matches = await match_venues(text, venues)
    except (UpmatchesApiError, VenueMatchError) as exc:
        logger.warning("Venue matching failed: %s", exc)
        await _send_game_form_prompt(
            chat_id,
            "I could not search venues right now. Please try again later.",
            thread_id,
        )
        return

    set_venue_matches(session, text, matches)
    await _send_game_form_prompt(chat_id, current_prompt(session), thread_id)


async def _skill_levels(api: UpmatchesApiClient) -> list[dict]:
    try:
        levels = await api.list_skill_levels()
    except UpmatchesApiError as exc:
        logger.warning("Could not fetch skill levels; using fallback labels: %s", exc)
        return list(DEFAULT_SKILL_LEVELS)
    return levels or list(DEFAULT_SKILL_LEVELS)


async def _handle_confirmation(
    session_key: tuple[int, int],
    session: GamePostSession,
    text: str,
    chat_id: int,
    thread_id: int | None,
    settings: Settings,
    api: UpmatchesApiClient,
) -> None:
    normalized = text.strip().lower()
    if normalized not in {"confirm", "yes", "y"}:
        await _send_game_form_prompt(
            chat_id,
            "Reply `confirm` to create this game, or `/cancel` to stop.",
            thread_id,
        )
        return

    try:
        payload = build_game_payload(session)
        game = await api.create_game(payload)
        game_id = str(game.get("id") or "")
        share_link = {}
        if game_id:
            try:
                share_link = await api.create_share_link(game_id)
            except UpmatchesApiError as exc:
                logger.warning("Game created but share-link creation failed: %s", exc)
        share_url = api.game_url(game, share_link)
        post = format_created_post(session, share_url)
        result = await send_chat_message(
            settings.telegram_hub_group,
            post,
            message_thread_id=settings.telegram_game_post_topic_id,
            disable_web_page_preview=False,
        )
    except (GamePostFormError, UpmatchesApiError, TelegramSendError) as exc:
        logger.error("Failed to create game from /post form: %s", exc)
        await _send_game_form_prompt(
            chat_id,
            "I could not create the game. Please check the details or try again later.",
            thread_id,
        )
        return

    _game_post_sessions.pop(session_key, None)
    await _send_game_form_prompt(
        chat_id,
        "Game created and posted to Organizers & Find Players. "
        f"Message ID: {result['message_id']}",
        thread_id,
    )


async def _delete_after(chat_id: int, message_id: int, delay: int) -> None:
    """Wait `delay` seconds, then delete the welcome message. Best-effort."""
    try:
        await asyncio.sleep(delay)
        await delete_chat_message(chat_id, message_id)
    except TelegramSendError as exc:
        logger.warning("Could not delete welcome message %s: %s", message_id, exc)


SURVEY_MESSAGE_TEMPLATES = (
    """Hi badminton organisers,

Upmatches is collecting feedback from people who organise badminton games in Singapore. The survey has 3-5 short questions and is about the common problems organisers face when setting up games, finding players, and managing attendance.

Survey: https://app.youform.com/forms/idbukum2

{count} organisers have responded so far.

The survey closes on 30 June 2026, 23:59:59.

Join our channel to share more feedback and follow updates: https://t.me/upmatcheshub

Thank you for sharing your feedback.""",
    """Hi everyone,

If you organise badminton games in Singapore, Upmatches would appreciate your input. We are running a short 3-5 question survey about organising games, filling slots, and managing attendance.

Survey: https://app.youform.com/forms/idbukum2

{count} organisers have responded so far.

The survey closes on 30 June 2026, 23:59:59.

Join our channel to share more feedback and follow updates: https://t.me/upmatcheshub

Thanks for helping us understand what organisers need.""",
    """Hi badminton organisers,

We are gathering feedback from Singapore badminton organisers for Upmatches. The survey is short and focuses on the pain points around setting up games, finding enough players, and handling attendance changes.

Survey: https://app.youform.com/forms/idbukum2

{count} organisers have responded so far.

The survey closes on 30 June 2026, 23:59:59.

Join our channel to share more feedback and follow updates: https://t.me/upmatcheshub

Your feedback would be helpful. Thank you.""",
    """Hi all,

Upmatches is learning from people who organise badminton sessions in Singapore. If you have a few minutes, please share what usually makes organising games difficult, from player availability to last-minute dropouts.

Survey: https://app.youform.com/forms/idbukum2

{count} organisers have responded so far.

The survey closes on 30 June 2026, 23:59:59.

Join our channel to share more feedback and follow updates: https://t.me/upmatcheshub

Thank you for taking the time to respond.""",
)


class SendRequest(BaseModel):
    # Optional: when omitted, a random built-in survey template is used.
    message: str | None = Field(default=None)


class SendResponse(BaseModel):
    sent: bool
    message_id: int | None = None
    target: str | None = None


def select_message(body_message: str | None, settings: Settings) -> str:
    """Return the explicit message or a random default survey template."""
    if body_message is not None:
        return body_message.strip()

    if SURVEY_MESSAGE_TEMPLATES:
        return random.choice(SURVEY_MESSAGE_TEMPLATES).strip()

    return settings.telegram_default_message.strip()


def render_submission_count(
    message: str,
    count: int | None,
    settings: Settings,
) -> str:
    if "{count}" in message:
        if count is None:
            message = "\n".join(
                line for line in message.splitlines() if "{count}" not in line
            )
            return re.sub(r"\n{3,}", "\n\n", message).strip()

        return message.replace("{count}", str(count))

    if count is not None:
        return message + settings.youform_count_template.format(count=count)

    return message


def require_cron_secret(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate the `Authorization: Bearer <CRON_SECRET>` header."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
        )
    # Constant-time comparison to avoid leaking the secret via timing.
    if not secrets.compare_digest(token, settings.cron_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token.",
        )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Receive Telegram updates and welcome users who join the discussion group.

    Telegram echoes our configured secret in the X-Telegram-Bot-Api-Secret-Token
    header; we reject any call that does not carry it. An unset secret disables
    the endpoint entirely so it can never accept unauthenticated updates.
    """
    secret = settings.telegram_webhook_secret
    header = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not secret or not secrets.compare_digest(header, secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook token.",
        )

    update = await request.json()
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    new_members = message.get("new_chat_members") or []

    for member in new_members:
        # Never welcome bots — that includes ourselves being added to the group.
        if member.get("is_bot"):
            continue
        if chat_id is None:
            continue
        text = build_welcome(member, settings.telegram_welcome_message)
        try:
            result = await send_chat_message(chat_id, text, parse_mode="HTML")
        except TelegramSendError as exc:
            # Don't fail the webhook: a 200 stops Telegram from retrying the
            # same update (which would re-welcome on every retry).
            logger.error("Failed to send welcome message: %s", exc)
            continue

        # Auto-delete the welcome after a delay so it doesn't clutter the group.
        # Run it as a background task so the webhook still returns immediately.
        ttl = settings.telegram_welcome_ttl_seconds
        if ttl > 0:
            task = asyncio.create_task(
                _delete_after(chat_id, result["message_id"], ttl)
            )
            _pending_deletes.add(task)
            task.add_done_callback(_pending_deletes.discard)

    await _handle_game_post_form(message, settings)

    return {"ok": True}


@app.post(
    "/telegram/send",
    response_model=SendResponse,
    dependencies=[Depends(require_cron_secret)],
)
async def telegram_send(
    body: SendRequest,
    settings: Settings = Depends(get_settings),
) -> SendResponse:
    message = select_message(body.message, settings)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message must not be empty.",
        )

    # Embed the live YouForm submission count. Failing to fetch it must not
    # block the message, so degrade gracefully and send without the count.
    try:
        count: int | None = await get_submission_count()
    except YouformError as exc:
        logger.warning("Could not fetch YouForm count, sending without it: %s", exc)
        count = None

    # The message body controls where the count appears. If it could not be
    # fetched, drop the line(s) referencing it so no placeholder leaks out.
    message = render_submission_count(message, count, settings)

    try:
        result = await send_message(message)
    except TelegramSendError as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SendResponse(**result)
