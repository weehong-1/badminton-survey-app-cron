"""Runtime configuration loaded from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All sensitive details live in .env and are read here."""

    # Bot token from @BotFather. The bot must be an admin (with "Post Messages")
    # of the target channel.
    telegram_bot_token: str
    # Channel chat id (e.g. "-1004341050758") or a public "@username".
    telegram_target_group: str
    cron_secret: str
    telegram_default_message: str = "Hourly badminton group message"

    # Welcome-on-join for the discussion group linked to the channel. The bot
    # must be a member of that group. {name} becomes a clickable mention of the
    # new member; keep other text free of < & > since it is sent as HTML.
    telegram_welcome_message: str = (
        "🚀 Welcome to the Upmatches Community, {name}! "
        "We are thrilled to have you here.\n\n"
        "This is your space to network, share feedback, or get support."
    )
    # Shared secret echoed by Telegram in the X-Telegram-Bot-Api-Secret-Token
    # header on every webhook call. Set the same value when calling setWebhook.
    # Empty disables the webhook endpoint (all calls are rejected).
    telegram_webhook_secret: str = ""
    # Seconds after which a welcome message is auto-deleted so it does not clutter
    # the group (the joiner still gets the notification). 0 keeps it permanently.
    # A bot may delete its own messages without admin rights, within 48 hours.
    telegram_welcome_ttl_seconds: int = 60

    # Group/topic where completed organizer game posts are published.
    telegram_hub_group: str = "@upmatcheshub"
    telegram_game_post_topic_id: int = 5

    # Upmatches API access for creating games from the Telegram `/post` form.
    upmatches_api_base_url: str = "https://api.upmatches.com"
    upmatches_bot_service_client_id: str = ""
    upmatches_bot_service_client_secret: str = ""
    upmatches_bot_service_totp_secret: str = ""
    upmatches_venue_cache_seconds: int = 3600

    # OpenAI structured output venue matcher. If the key is unset, the bot falls
    # back to deterministic text matching and still asks the organizer to confirm.
    openai_api_key: str = ""
    openai_venue_match_model: str = "gpt-4o-mini"
    openai_venue_candidate_limit: int = 30

    # YouForm survey whose submission count is appended to outgoing messages.
    youform_api_token: str
    youform_form_id: str = "idbukum2"
    youform_api_base: str = "https://app.youform.com/api"
    # Appended to the message; {count} is substituted with the submission total.
    youform_count_template: str = "\n\n📊 {count} people have responded so far!"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
