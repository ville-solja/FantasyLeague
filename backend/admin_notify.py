"""Admin notifications outside the site (issue #215).

Tells admins that Twitch channels are waiting for MVP approval, by email (the SMTP
settings used for password resets) and/or a Discord webhook. twitch_channels.notify_pending
decides when to send; this module knows the channels, the recipients and the text.

The webhook URL and the recipient addresses are secrets: they are never logged,
returned, audited or shown in Admin › Twitch status (only "set" and a count). Failures
are reported as a kind ("http 404", "timeout", "smtp"). A Shoutrrr channel (#97) would
be one more entry in CHANNELS.
"""
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests
from sqlalchemy.orm import Session

import email_utils
from models import User
from text_safety import clean_display_text, looks_like_url

logger = logging.getLogger(__name__)

DISCORD_ENV = "ADMIN_NOTIFY_DISCORD_WEBHOOK_URL"
EMAILS_ENV = "ADMIN_NOTIFY_EMAILS"
CHANNELS = ("discord", "email")
DISCORD_HOSTS = ("discord.com", "discordapp.com")
DISCORD_TIMEOUT = 5          # seconds
DISCORD_USERNAME = "Kana Cards"
NAME_MAX_LEN = 50
OK, OFF = "ok", "off"

_DISCORD_MARKDOWN_RE = re.compile(r"([\\*_~`|>#])")

_lock = threading.Lock()
_LAST: dict = {}


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def _discord_url() -> tuple[str | None, str]:
    """(webhook URL or None, reason). Only https://discord.com|discordapp.com/api/webhooks/…
    addresses count; anything else is off."""
    raw = os.getenv(DISCORD_ENV, "").strip()
    if not raw:
        return None, "not set"
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None, "set, but not a Discord webhook address"
    if (parts.scheme != "https" or parts.hostname not in DISCORD_HOSTS or port is not None
            or parts.username or parts.password
            or not parts.path.startswith("/api/webhooks/") or len(parts.path) <= len("/api/webhooks/")):
        return None, "set, but not a Discord webhook address"
    return raw, "set"


def _email_recipients(db: Session) -> tuple[list[str], str]:
    """(addresses, reason). ADMIN_NOTIFY_EMAILS replaces the admin list; "off" turns
    email off. Without SMTP nothing is sent."""
    raw = os.getenv(EMAILS_ENV, "").strip()
    if raw.lower() == "off":
        return [], f"off ({EMAILS_ENV}=off)"
    if not email_utils.email_configured():
        return [], "SMTP is not configured"
    if raw:
        addresses = [a.strip() for a in raw.split(",") if a.strip()]
    else:
        addresses = [e.strip() for (e,) in db.query(User.email)
                     .filter(User.is_admin.is_(True), User.email.isnot(None)).all() if e and e.strip()]
    addresses = list(dict.fromkeys(addresses))
    if not addresses:
        return [], ("no address in " + EMAILS_ENV) if raw else "no admin has an email address"
    return addresses, "set"


def channels(db: Session) -> dict:
    """{"discord": {ready, reason}, "email": {ready, recipients, reason}}. No URL, no addresses."""
    url, d_reason = _discord_url()
    addresses, e_reason = _email_recipients(db)
    return {
        "discord": {"ready": url is not None, "reason": d_reason},
        "email": {"ready": bool(addresses), "recipients": len(addresses), "reason": e_reason},
    }


def any_ready(db: Session) -> bool:
    return any(c["ready"] for c in channels(db).values())


# ---------------------------------------------------------------------------
# Names and text
# ---------------------------------------------------------------------------

def escape_discord(text: str) -> str:
    return _DISCORD_MARKDOWN_RE.sub(r"\\\1", text)


def safe_name(value, discord: bool = False) -> str:
    """A channel name cleaned of control and hidden characters, Discord markdown escaped
    when it goes to Discord."""
    text = clean_display_text(value, NAME_MAX_LEN)
    return escape_discord(text) if discord else text


def channel_label(channel_id: str, display_name, login, discord: bool = False) -> str:
    """"Display (login)", or "channel <id>" when Helix had no name or the name looks like a link."""
    display = clean_display_text(display_name, NAME_MAX_LEN)
    handle = clean_display_text(login, NAME_MAX_LEN)
    if not display or looks_like_url(display) or (handle and looks_like_url(handle)):
        return f"channel {channel_id}"
    label = safe_name(display, discord)
    return f"{label} ({safe_name(handle, discord)})" if handle else label


def approval_message(rows: list, total: int, name_limit: int) -> tuple[str, str, str]:
    """(subject, plain text, Discord text) for the pending rows not yet announced, oldest
    first. Names the first name_limit, then "and N more"; links Admin when APP_BASE_URL is set."""
    count = len(rows)
    base = os.getenv("APP_BASE_URL", "").strip().rstrip("/")

    def body(discord: bool) -> str:
        names = [channel_label(r.channel_id, r.display_name, r.login, discord) for r in rows[:name_limit]]
        listed = ", ".join(names)
        if count > name_limit:
            listed += f" and {count - name_limit} more"
        plural = count != 1
        if total > count:
            head = (f"{count} new Twitch channel{'s' if plural else ''} asked for MVP approval: "
                    f"{listed}. {total} are waiting in all.")
        else:
            head = (f"{count} Twitch channel{'s are' if plural else ' is'} waiting for MVP "
                    f"approval: {listed}.")
        tail = " Approve or reject them in Admin › Twitch › Approved streamers"
        return head + tail + (f": {base}" if base else ".")

    subject = f"{app_name()}: {total} streamer{'s' if total != 1 else ''} waiting for approval"
    return subject, body(False), body(True)


def delivered(result: dict) -> list[str]:
    """The channels that reached someone."""
    return [ch for ch in CHANNELS if result.get(ch) == OK]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def _send_discord(url: str, text: str) -> str:
    try:
        resp = requests.post(url, json={"content": text[:2000],
                                        "allowed_mentions": {"parse": []},
                                        "username": DISCORD_USERNAME},
                             timeout=DISCORD_TIMEOUT, allow_redirects=False)
    except requests.Timeout:
        return "error: timeout"
    except requests.ConnectionError:
        return "error: connection"
    except Exception as exc:
        return f"error: {type(exc).__name__}"
    if 200 <= resp.status_code < 300:
        return OK
    return f"error: http {resp.status_code}"


def _send_email(addresses: list[str], subject: str, text: str) -> tuple[str, int]:
    """One message per recipient, no CC. "ok" when at least one went out."""
    sent = 0
    for address in addresses:
        try:
            if email_utils.send_email(address, subject, text):
                sent += 1
        except Exception as exc:
            logger.warning("Admin notification: email raised %s", type(exc).__name__)
    if sent == 0:
        return "error: smtp", 0
    if sent < len(addresses):
        logger.warning("Admin notification: email failed for %d of %d recipient(s)",
                       len(addresses) - sent, len(addresses))
    return OK, sent


def targets(db: Session) -> tuple[str | None, list[str]]:
    """(webhook URL or None, email addresses): where send() would go. Read this, end the
    caller's transaction, then call deliver(), so no database lock is held over network I/O."""
    url, _ = _discord_url()
    addresses, _ = _email_recipients(db)
    return url, addresses


def deliver(dest: tuple[str | None, list[str]], subject: str, text: str,
            discord_text: str | None = None) -> dict:
    """Send to the targets() channels: {"discord": "ok" | "off" | "error: <kind>", "email": …,
    "email_sent": n}. Never touches the database, never raises for a channel failure;
    records last_result()."""
    url, addresses = dest
    result = {"discord": OFF, "email": OFF, "email_sent": 0}
    if url:
        result["discord"] = _send_discord(url, discord_text if discord_text is not None else text)
    if addresses:
        result["email"], result["email_sent"] = _send_email(addresses, subject, text)
    for ch in CHANNELS:
        if result[ch].startswith("error"):
            logger.warning("Admin notification: %s failed (%s)", ch, result[ch][len("error: "):])
    with _lock:
        _LAST.clear()
        _LAST.update(at=int(time.time()), discord=result["discord"], email=result["email"])
    return result


def send(subject: str, text: str, db: Session, discord_text: str | None = None) -> dict:
    """targets() + deliver(). Commits the session first so no transaction stays open
    while sending; callers with pending changes should use targets/deliver themselves."""
    dest = targets(db)
    db.commit()
    return deliver(dest, subject, text, discord_text)


def last_result() -> dict:
    """In memory, since the last restart: {at, discord, email}, or {} when nothing was sent."""
    with _lock:
        return dict(_LAST)


def _reset_for_tests() -> None:
    with _lock:
        _LAST.clear()


# ---------------------------------------------------------------------------
# Test message (Admin › Twitch › Send test notification)
# ---------------------------------------------------------------------------

def app_name() -> str:
    """APP_NAME, the email subject prefix the password emails use too (commands.md)."""
    return os.getenv("APP_NAME", "Kana Cards").strip() or "Kana Cards"


def test_subject() -> str:
    return f"{app_name()}: test notification"


def test_text() -> str:
    return (f"Test message from {app_name()}: streamer approval notifications reach this "
            "channel.")


def send_test(db: Session, admin: dict) -> dict:
    """POST /admin/twitch/notify-test: a fixed test message to every configured channel,
    audited as admin_twitch_notify_test (outcomes only, never the URL or addresses)."""
    from deps import _audit
    result = send(test_subject(), test_text(), db)
    _audit(db, "admin_twitch_notify_test", actor_id=admin["user_id"],
           actor_username=admin.get("username"),
           detail=f"discord={result['discord']} email={result['email']} email_sent={result['email_sent']}")
    db.commit()
    return result
