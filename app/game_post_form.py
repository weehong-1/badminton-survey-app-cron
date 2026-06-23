"""State and validation for the Telegram `/post` game creation flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo


BADMINTON_ACTIVITY_ID = "644b18d1-e0c3-4570-8ffe-470726218cf8"
CURRENCY = "SGD"
DEFAULT_SKILL_LEVELS = (
    {"id": 1, "name": "B", "sortOrder": 1},
    {"id": 2, "name": "MB", "sortOrder": 2},
    {"id": 3, "name": "HB", "sortOrder": 3},
    {"id": 4, "name": "LI", "sortOrder": 4},
    {"id": 5, "name": "MI", "sortOrder": 5},
    {"id": 6, "name": "HI", "sortOrder": 6},
    {"id": 7, "name": "A", "sortOrder": 7},
)


class GamePostFormError(ValueError):
    """Raised when a user reply cannot be accepted for the current step."""


@dataclass
class GamePostSession:
    state: str = "venue"
    organizer_name: str = "Organizer"
    venue_text: str = ""
    venue_matches: list[dict] = field(default_factory=list)
    selected_venue: dict | None = None
    game_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    skill_level_from_id: int | None = None
    skill_level_to_id: int | None = None
    skill_level_label: str = ""
    slots: int | None = None
    game_type: str = "DOUBLE"
    visibility: str = "PUBLIC"
    pricing_mode: str = "FLAT"
    pricing_values: dict[str, Decimal] = field(default_factory=dict)
    remark: str = ""


def start_game_post_session(organizer_name: str = "Organizer") -> GamePostSession:
    return GamePostSession(organizer_name=organizer_name)


def current_prompt(session: GamePostSession) -> str:
    prompts = {
        "venue": (
            "1/9 Venue?\n"
            "Example: Clementi Sports Hall, Bukit Canberra, OCBC Arena"
        ),
        "venue_choice": venue_choices_prompt(session.venue_matches),
        "date": "2/9 Date? Use `DD Mon YYYY` or `YYYY-MM-DD`. Example: `25 Jun 2026`",
        "time": "3/9 Time range? Example: `7pm-9pm` or `19:00-21:00`",
        "level": (
            "4/9 Player level range?\n"
            "Examples: `MB-HB`, `LI-MI`, `B-A`"
        ),
        "slots": "5/9 How many open slots? Example: `6`",
        "game_type": "6/9 Game type? Reply `single` or `double`.",
        "visibility": "7/9 Visibility? Reply `public` or `private`.",
        "pricing_mode": (
            "8/9 Pricing mode?\n"
            "`flat` = same fee for everyone\n"
            "`gendered` = male/female prices\n"
            "`shuttlecock` = base price + per-shuttle rate"
        ),
        "flat_price": "Flat price per player in SGD? Example: `10`",
        "male_price": "Male price in SGD? Example: `10`",
        "female_price": "Female price in SGD? Example: `8`",
        "base_price": "Base price in SGD? Example: `5`",
        "shuttle_price": "Price per shuttle in SGD? Example: `3`",
        "remark": (
            "9/9 Any remarks? Example: `Bring your own shuttlecocks.`\n"
            "Send `skip` if none."
        ),
        "confirm": (
            f"{format_preview(session)}\n\n"
            "Reply `confirm` to create this game, or `/cancel` to stop."
        ),
    }
    return prompts[session.state]


def venue_choices_prompt(matches: list[dict]) -> str:
    if not matches:
        return (
            "I could not match that venue. Please send a more specific venue name "
            "or nearby address."
        )

    lines = ["I found these venue matches. Reply `1`, `2`, `3`, or `none`:"]
    for index, match in enumerate(matches[:3], start=1):
        address = match.get("address") or "No address"
        confidence = match.get("confidence")
        confidence_text = f" ({confidence:.0%})" if isinstance(confidence, float) else ""
        lines.append(f"{index}. {match['name']}{confidence_text}\n   {address}")
    return "\n".join(lines)


def set_venue_matches(session: GamePostSession, venue_text: str, matches: list[dict]) -> None:
    session.venue_text = venue_text.strip()
    session.venue_matches = matches[:3]
    session.state = "venue_choice"


def select_venue(session: GamePostSession, text: str) -> None:
    normalized = text.strip().lower()
    if normalized in {"none", "no", "n"}:
        session.venue_matches = []
        session.state = "venue"
        raise GamePostFormError("Please send a more specific venue name.")

    try:
        index = int(normalized)
    except ValueError as exc:
        raise GamePostFormError("Reply with `1`, `2`, `3`, or `none`.") from exc

    if index < 1 or index > len(session.venue_matches):
        raise GamePostFormError("That choice is not in the venue list.")

    session.selected_venue = session.venue_matches[index - 1]
    session.state = "date"


def record_answer(session: GamePostSession, text: str, skill_levels: list[dict]) -> None:
    value = text.strip()
    if not value:
        raise GamePostFormError("Please send a value.")

    if session.state == "date":
        session.game_date = parse_game_date(value)
        session.state = "time"
    elif session.state == "time":
        session.start_time, session.end_time = parse_time_range(value)
        session.state = "level"
    elif session.state == "level":
        from_id, to_id, label = parse_skill_range(value, skill_levels)
        session.skill_level_from_id = from_id
        session.skill_level_to_id = to_id
        session.skill_level_label = label
        session.state = "slots"
    elif session.state == "slots":
        session.slots = parse_slots(value)
        session.state = "game_type"
    elif session.state == "game_type":
        session.game_type = parse_game_type(value)
        session.state = "visibility"
    elif session.state == "visibility":
        session.visibility = parse_visibility(value)
        session.state = "pricing_mode"
    elif session.state == "pricing_mode":
        session.pricing_mode = parse_pricing_mode(value)
        if session.pricing_mode == "FLAT":
            session.state = "flat_price"
        elif session.pricing_mode == "GENDERED":
            session.state = "male_price"
        else:
            session.state = "base_price"
    elif session.state == "flat_price":
        session.pricing_values["flatPrice"] = parse_money(value)
        session.state = "remark"
    elif session.state == "male_price":
        session.pricing_values["malePrice"] = parse_money(value)
        session.state = "female_price"
    elif session.state == "female_price":
        session.pricing_values["femalePrice"] = parse_money(value)
        session.state = "remark"
    elif session.state == "base_price":
        session.pricing_values["basePrice"] = parse_money(value)
        session.state = "shuttle_price"
    elif session.state == "shuttle_price":
        session.pricing_values["pricePerShuttle"] = parse_money(value)
        session.state = "remark"
    elif session.state == "remark":
        session.remark = "" if value.lower() in {"skip", "-", "none", "n/a"} else value
        session.state = "confirm"
    else:
        raise GamePostFormError("This form step cannot accept that answer.")


def parse_game_date(raw: str) -> date:
    normalized = raw.strip()
    today = datetime.now(ZoneInfo("Asia/Singapore")).date()
    if normalized.lower() == "today":
        return today
    if normalized.lower() == "tomorrow":
        return date.fromordinal(today.toordinal() + 1)

    formats = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y")
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass

    short_formats = ("%d %b", "%d %B", "%d/%m", "%d-%m")
    for fmt in short_formats:
        try:
            parsed = datetime.strptime(normalized, fmt).date().replace(year=today.year)
        except ValueError:
            continue
        if parsed < today:
            parsed = parsed.replace(year=today.year + 1)
        return parsed

    raise GamePostFormError("Use a date like `25 Jun 2026` or `2026-06-25`.")


def parse_time_range(raw: str) -> tuple[time, time]:
    parts = re.split(r"\s*(?:-|to|–|—)\s*", raw.strip(), flags=re.IGNORECASE)
    if len(parts) != 2:
        raise GamePostFormError("Use a time range like `7pm-9pm` or `19:00-21:00`.")

    start = parse_time(parts[0])
    end = parse_time(parts[1])
    if end <= start:
        raise GamePostFormError("End time must be after start time on the same day.")
    return start, end


def parse_time(raw: str) -> time:
    normalized = raw.strip().lower().replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", normalized)
    if not match:
        raise GamePostFormError("Use times like `7pm`, `7:30pm`, or `19:00`.")

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(3)
    if minute > 59:
        raise GamePostFormError("Minutes must be between 00 and 59.")

    if suffix:
        if hour < 1 or hour > 12:
            raise GamePostFormError("12-hour time must use hours 1-12.")
        if suffix == "pm" and hour != 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        raise GamePostFormError("24-hour time must use hours 0-23.")

    return time(hour, minute)


def parse_skill_range(raw: str, skill_levels: list[dict]) -> tuple[int, int, str]:
    levels = skill_levels or list(DEFAULT_SKILL_LEVELS)
    by_name = {normalize_token(level["name"]): level for level in levels}
    by_id = {str(level["id"]): level for level in levels}
    default_aliases = {
        normalize_token(level["name"]): str(level["id"])
        for level in DEFAULT_SKILL_LEVELS
    }

    parts = re.split(r"\s*(?:-|to|–|—)\s*", raw.strip(), flags=re.IGNORECASE)
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    if len(parts) != 2:
        raise GamePostFormError("Use a skill range like `MB-HB`.")

    matched = []
    for part in parts:
        token = normalize_token(part)
        level = by_name.get(token) or by_id.get(token)
        if level is None and token in default_aliases:
            level = by_id.get(default_aliases[token])
        if level is None:
            raise GamePostFormError(
                "Unknown skill level. Try one of: "
                + ", ".join(level["name"] for level in levels)
            )
        matched.append(level)

    first, second = matched
    if int(first.get("sortOrder", first["id"])) > int(second.get("sortOrder", second["id"])):
        first, second = second, first

    label = f"{first['name']}-{second['name']}"
    return int(first["id"]), int(second["id"]), label


def normalize_token(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", raw.lower())


def parse_slots(raw: str) -> int:
    match = re.search(r"\d+", raw)
    if not match:
        raise GamePostFormError("Send the number of open slots, for example `6`.")
    slots = int(match.group(0))
    if slots < 1 or slots > 100:
        raise GamePostFormError("Slots must be between 1 and 100.")
    return slots


def parse_game_type(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized in {"single", "singles", "s"}:
        return "SINGLE"
    if normalized in {"double", "doubles", "d"}:
        return "DOUBLE"
    raise GamePostFormError("Reply `single` or `double`.")


def parse_visibility(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized in {"public", "pub"}:
        return "PUBLIC"
    if normalized in {"private", "priv"}:
        return "PRIVATE"
    raise GamePostFormError("Reply `public` or `private`.")


def parse_pricing_mode(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized in {"flat", "same"}:
        return "FLAT"
    if normalized in {"gendered", "gender", "male/female", "male female"}:
        return "GENDERED"
    if normalized in {"shuttlecock", "shuttle", "shuttles"}:
        return "SHUTTLECOCK"
    raise GamePostFormError("Reply `flat`, `gendered`, or `shuttlecock`.")


def parse_money(raw: str) -> Decimal:
    normalized = raw.strip().replace("$", "").replace("sgd", "").replace("SGD", "")
    try:
        value = Decimal(normalized).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise GamePostFormError("Send a price like `10` or `8.50`.") from exc
    if value < 0 or value > Decimal("10000"):
        raise GamePostFormError("Price must be between 0 and 10000.")
    return value


def build_game_payload(session: GamePostSession) -> dict:
    if not session.selected_venue:
        raise GamePostFormError("Venue has not been selected.")
    if not all(
        [
            session.game_date,
            session.start_time,
            session.end_time,
            session.skill_level_from_id,
            session.skill_level_to_id,
            session.slots,
        ]
    ):
        raise GamePostFormError("The game form is incomplete.")

    start_time = to_utc_iso(session.game_date, session.start_time)
    end_time = to_utc_iso(session.game_date, session.end_time)
    pricing = build_pricing(session)
    legacy_price = representative_price(pricing)

    return {
        "activityId": BADMINTON_ACTIVITY_ID,
        "venueId": int(session.selected_venue["id"]),
        "skillLevelFromId": session.skill_level_from_id,
        "skillLevelToId": session.skill_level_to_id,
        "currency": CURRENCY,
        "price": float(legacy_price),
        "pricing": decimal_to_json(pricing),
        "slots": session.slots,
        "startTime": start_time,
        "endTime": end_time,
        "visibility": session.visibility,
        "gameType": session.game_type,
        "joinAsOrganizer": True,
        "remark": session.remark,
    }


def to_utc_iso(game_date: date, game_time: time) -> str:
    local_dt = datetime.combine(game_date, game_time, tzinfo=ZoneInfo("Asia/Singapore"))
    return local_dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def build_pricing(session: GamePostSession) -> dict:
    values = session.pricing_values
    if session.pricing_mode == "FLAT":
        return {"mode": "FLAT", "currency": CURRENCY, "flatPrice": values["flatPrice"]}
    if session.pricing_mode == "GENDERED":
        return {
            "mode": "GENDERED",
            "currency": CURRENCY,
            "malePrice": values["malePrice"],
            "femalePrice": values["femalePrice"],
        }
    return {
        "mode": "SHUTTLECOCK",
        "currency": CURRENCY,
        "basePrice": values["basePrice"],
        "pricePerShuttle": values["pricePerShuttle"],
    }


def representative_price(pricing: dict) -> Decimal:
    if pricing["mode"] == "FLAT":
        return pricing["flatPrice"]
    if pricing["mode"] == "GENDERED":
        return min(pricing["malePrice"], pricing["femalePrice"])
    return pricing["basePrice"]


def decimal_to_json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: decimal_to_json(item) for key, item in value.items()}
    return value


def format_preview(session: GamePostSession) -> str:
    pricing = build_pricing(session) if session.pricing_values else {"mode": session.pricing_mode}
    venue = session.selected_venue or {}
    lines = [
        "Preview game post",
        "",
        f"Venue: {venue.get('name', session.venue_text)}",
        f"Address: {venue.get('address', 'Unknown')}",
        f"Date: {session.game_date.isoformat() if session.game_date else '-'}",
        f"Time: {format_time(session.start_time)}-{format_time(session.end_time)}",
        f"Level: {session.skill_level_label or '-'}",
        f"Slots: {session.slots or '-'}",
        f"Type: {session.game_type}",
        f"Visibility: {session.visibility}",
        f"Pricing: {format_pricing(pricing)}",
        f"Remark: {session.remark or '-'}",
    ]
    return "\n".join(lines)


def format_time(value: time | None) -> str:
    return value.strftime("%H:%M") if value else "-"


def format_pricing(pricing: dict) -> str:
    mode = pricing["mode"]
    if mode == "FLAT":
        return f"Flat SGD {pricing['flatPrice']}"
    if mode == "GENDERED":
        return f"Male SGD {pricing['malePrice']}, Female SGD {pricing['femalePrice']}"
    if mode == "SHUTTLECOCK":
        return f"Base SGD {pricing['basePrice']} + SGD {pricing['pricePerShuttle']}/shuttle"
    return mode


def format_created_post(session: GamePostSession, share_url: str | None) -> str:
    lines = [
        "🏸 Game Open for Players",
        "",
        f"Organiser: {session.organizer_name}",
        f"Venue: {session.selected_venue['name'] if session.selected_venue else session.venue_text}",
        f"Date: {session.game_date.isoformat() if session.game_date else '-'}",
        f"Time: {format_time(session.start_time)}-{format_time(session.end_time)}",
        f"Level: {session.skill_level_label}",
        f"Open slots: {session.slots}",
        f"Pricing: {format_pricing(build_pricing(session))}",
    ]
    if session.remark:
        lines.append(f"Remark: {session.remark}")
    if share_url:
        lines.extend(["", f"Join here: {share_url}"])
    else:
        lines.extend(["", "The game has been created on Upmatches."])
    return "\n".join(lines)
