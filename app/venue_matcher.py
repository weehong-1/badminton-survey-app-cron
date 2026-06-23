"""AI-assisted venue matching for organizer free-text venue input."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
import re

import httpx

from app.config import get_settings


class VenueMatchError(Exception):
    """Raised when venue matching cannot return usable candidates."""


def narrow_venues(query: str, venues: list[dict], limit: int = 30) -> list[dict]:
    query_norm = normalize(query)
    query_tokens = set(tokens(query_norm))
    scored = []
    for venue in venues:
        haystack = " ".join(
            str(part or "")
            for part in [
                venue.get("name"),
                venue.get("address"),
                venue.get("postalCode"),
            ]
        )
        haystack_norm = normalize(haystack)
        haystack_tokens = set(tokens(haystack_norm))
        score = SequenceMatcher(None, query_norm, haystack_norm).ratio()
        if query_tokens:
            score += len(query_tokens & haystack_tokens) / len(query_tokens)
        if query_norm and query_norm in haystack_norm:
            score += 0.5
        if venue.get("name") and query_norm in normalize(venue["name"]):
            score += 0.4
        scored.append((score, venue))

    return [venue for _, venue in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def tokens(value: str) -> list[str]:
    return [token[:-1] if token.endswith("s") else token for token in value.split()]


async def match_venues(query: str, venues: list[dict]) -> list[dict]:
    candidates = narrow_venues(query, venues)
    if not candidates:
        return []

    settings = get_settings()
    if not settings.openai_api_key:
        return deterministic_matches(query, candidates)

    try:
        return await openai_rank_venues(query, candidates[: settings.openai_venue_candidate_limit])
    except Exception:
        return deterministic_matches(query, candidates)


def deterministic_matches(query: str, candidates: list[dict]) -> list[dict]:
    query_norm = normalize(query)
    matches = []
    for venue in candidates[:3]:
        text = normalize(f"{venue.get('name', '')} {venue.get('address', '')}")
        confidence = max(0.2, min(0.95, SequenceMatcher(None, query_norm, text).ratio()))
        matches.append(format_match(venue, confidence, "Best text match without AI ranking."))
    return matches


async def openai_rank_venues(query: str, candidates: list[dict]) -> list[dict]:
    settings = get_settings()
    candidate_payload = [
        {
            "id": venue.get("id"),
            "name": venue.get("name"),
            "address": venue.get("address"),
            "postalCode": venue.get("postalCode"),
        }
        for venue in candidates
    ]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["matches"],
        "properties": {
            "matches": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["venueId", "confidence", "reason"],
                    "properties": {
                        "venueId": {"type": "integer"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }
    payload = {
        "model": settings.openai_venue_match_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Match a Singapore badminton venue query to known venue records. "
                    "Return only venue IDs from the provided candidates, ranked best first. "
                    "Use names, abbreviations, addresses, and postal codes. If uncertain, "
                    "still return the best plausible candidates with lower confidence."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"query": query, "candidates": candidate_payload},
                    ensure_ascii=True,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "venue_matches",
                "schema": schema,
                "strict": True,
            }
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/responses",
            json=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise VenueMatchError(f"OpenAI returned non-JSON HTTP {resp.status_code}.") from exc
    if resp.status_code >= 400:
        message = data.get("error", {}).get("message") or resp.reason_phrase
        raise VenueMatchError(f"OpenAI API error HTTP {resp.status_code}: {message}")

    raw_text = extract_response_text(data)
    parsed = json.loads(raw_text)
    by_id = {int(venue["id"]): venue for venue in candidates if venue.get("id") is not None}
    matches = []
    for item in parsed.get("matches", []):
        venue = by_id.get(int(item["venueId"]))
        if venue:
            matches.append(format_match(venue, float(item["confidence"]), item["reason"]))
    return matches[:3] or deterministic_matches(query, candidates)


def extract_response_text(data: dict) -> str:
    if data.get("output_text"):
        return data["output_text"]
    for output in data.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return content["text"]
    raise VenueMatchError("OpenAI response did not include output text.")


def format_match(venue: dict, confidence: float, reason: str) -> dict:
    return {
        "id": int(venue["id"]),
        "name": venue.get("name") or f"Venue {venue['id']}",
        "address": venue.get("address") or "",
        "postalCode": venue.get("postalCode"),
        "confidence": confidence,
        "reason": reason,
    }
