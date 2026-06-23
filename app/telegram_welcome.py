"""Build the welcome message sent when a user joins the discussion group."""

import html


def build_welcome(member: dict, template: str) -> str:
    """Return an HTML welcome string for a new chat member.

    `member` is a Telegram User object (from `new_chat_members`). The template's
    `{name}` slot is replaced with a clickable mention of the member; the rest of
    the template is sent verbatim as HTML, so keep it free of unescaped < & >.
    """
    user_id = member.get("id")
    raw_name = member.get("first_name") or member.get("username") or "there"
    safe_name = html.escape(raw_name)

    # tg://user?id= mentions only render for users the bot can see (i.e. group
    # members), which is exactly the case here. Fall back to a plain name if the
    # id is somehow missing.
    if user_id:
        mention = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    else:
        mention = safe_name

    return template.format(name=mention)
