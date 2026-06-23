"""HTTP client for the Upmatches API used by the Telegram bot."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import struct
import time
from typing import Any

import httpx

from app.config import get_settings
from app.game_post_form import BADMINTON_ACTIVITY_ID


class UpmatchesApiError(Exception):
    """Raised when the Upmatches API cannot complete a bot operation."""


@dataclass
class ServiceToken:
    access_token: str
    expires_at: float


_service_token: ServiceToken | None = None
_venue_cache: tuple[float, list[dict]] | None = None
_skill_level_cache: tuple[float, list[dict]] | None = None


def generate_totp(secret: str, now: int | None = None) -> str:
    key = base64.b32decode(secret.upper(), casefold=True)
    counter = int((now if now is not None else time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


class UpmatchesApiClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.upmatches_api_base_url.rstrip("/")

    async def list_venues(self) -> list[dict]:
        global _venue_cache
        if _venue_cache and _venue_cache[0] > time.time():
            return _venue_cache[1]

        venues: list[dict] = []
        page = 0
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                resp = await client.get(
                    f"{self.base_url}/api/v1/venues",
                    params={"page": page, "size": 500},
                )
                data = self._decode_response(resp)
                payload = data.get("data", {})
                venues.extend(payload.get("content", []))
                page_info = payload.get("page", {})
                if not page_info.get("hasNext"):
                    break
                page += 1

        badminton_venues = [
            venue for venue in venues
            if (venue.get("activity") or {}).get("id") == BADMINTON_ACTIVITY_ID
        ]
        _venue_cache = (time.time() + self.settings.upmatches_venue_cache_seconds, badminton_venues)
        return badminton_venues

    async def list_skill_levels(self) -> list[dict]:
        global _skill_level_cache
        if _skill_level_cache and _skill_level_cache[0] > time.time():
            return _skill_level_cache[1]

        token = await self.service_token()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/skill-levels",
                params={"activityId": BADMINTON_ACTIVITY_ID},
                headers={"Authorization": f"Bearer {token}"},
            )
        data = self._decode_response(resp)
        levels = data.get("data", [])
        _skill_level_cache = (time.time() + self.settings.upmatches_venue_cache_seconds, levels)
        return levels

    async def create_game(self, payload: dict) -> dict:
        token = await self.service_token()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/games",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        return self._decode_response(resp).get("data", {})

    async def create_share_link(self, game_id: str) -> dict:
        token = await self.service_token()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/share-links",
                json={"resourceType": "GAME", "resourceId": game_id},
                headers={"Authorization": f"Bearer {token}"},
            )
        return self._decode_response(resp).get("data", {})

    async def service_token(self) -> str:
        global _service_token
        if _service_token and _service_token.expires_at > time.time() + 60:
            return _service_token.access_token

        settings = self.settings
        required = {
            "UPMATCHES_BOT_SERVICE_CLIENT_ID": settings.upmatches_bot_service_client_id,
            "UPMATCHES_BOT_SERVICE_CLIENT_SECRET": settings.upmatches_bot_service_client_secret,
            "UPMATCHES_BOT_SERVICE_TOTP_SECRET": settings.upmatches_bot_service_totp_secret,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise UpmatchesApiError("Missing required env vars: " + ", ".join(missing))

        otp = generate_totp(settings.upmatches_bot_service_totp_secret)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/auth/tokens/service",
                json={
                    "clientId": settings.upmatches_bot_service_client_id,
                    "clientSecret": settings.upmatches_bot_service_client_secret,
                    "otp": otp,
                },
            )
        data = self._decode_response(resp).get("data", {})
        access_token = data.get("accessToken")
        if not access_token:
            raise UpmatchesApiError("Service token response did not include accessToken.")

        expires_in = int(data.get("expiresIn") or 900)
        _service_token = ServiceToken(access_token=access_token, expires_at=time.time() + expires_in)
        return access_token

    def game_url(self, game: dict, share_link: dict | None = None) -> str | None:
        code = (share_link or {}).get("code")
        if code:
            return f"{self.base_url}/share/{code}"
        game_id = game.get("id")
        if game_id:
            return f"{self.base_url}/games/{game_id}"
        return None

    def _decode_response(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise UpmatchesApiError(f"Upmatches returned non-JSON HTTP {resp.status_code}.") from exc
        if resp.status_code >= 400 or data.get("success") is False:
            message = data.get("message") or data.get("error") or resp.reason_phrase
            raise UpmatchesApiError(f"Upmatches API error HTTP {resp.status_code}: {message}")
        return data
