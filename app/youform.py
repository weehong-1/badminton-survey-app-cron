"""YouForm API access — fetch the survey submission count."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class YouformError(Exception):
    """Raised when the submission count could not be retrieved."""


async def get_submission_count() -> int:
    """Return the total number of submissions for the configured form.

    Calls the YouForm submissions endpoint and reads the paginator's `data.total`,
    which counts all submissions (complete and partial). Raises YouformError on any
    network, HTTP, or unexpected-payload failure.
    """
    settings = get_settings()
    url = f"{settings.youform_api_base}/forms/{settings.youform_form_id}/submissions"
    headers = {
        "Authorization": f"Bearer {settings.youform_api_token}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            total = resp.json()["data"]["total"]
            return int(total)
    except httpx.HTTPError as exc:
        raise YouformError(f"YouForm request failed: {exc}") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise YouformError(f"Unexpected YouForm response: {exc}") from exc
