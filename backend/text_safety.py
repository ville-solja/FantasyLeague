"""Clean outside text before the league repeats it in a trusted channel (issue #166).

Player names come from OpenDota and Steam, where every player picks their own and
can change it at any time. Twitch chat announcements and admin notifications carry
the league's name, so a link inside them reads as an official instruction. These
helpers strip invisible characters and spot link-like text so callers can refuse or
replace it.
"""
import re
import unicodedata

# A scheme, a www. prefix, or a dot followed by two or more letters at a word end
# ("free-skins.gg", "steam-gift.example", "a.b.ru").
_URL_LIKE_RE = re.compile(r"://|\bwww\.|\.[A-Za-z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b[^\s<>\"']*",
                     re.IGNORECASE)


def clean_display_text(value, max_len: int) -> str:
    """Drop control and format characters (Unicode Cc/Cf: control, zero-width and
    bidi overrides), collapse whitespace and cap the length."""
    text = "".join(ch for ch in str(value or "") if unicodedata.category(ch) not in ("Cc", "Cf"))
    text = " ".join(text.split())
    return text[:max_len].rstrip()


def strip_invisible(value) -> str:
    """Like clean_display_text for longer text: drops control and format characters
    but keeps line breaks and tabs, and does not cap or re-space the text."""
    return "".join(ch for ch in str(value or "")
                   if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf")).strip()


def looks_like_url(value) -> bool:
    """True when the text contains anything that could be read as a link."""
    return bool(_URL_LIKE_RE.search(str(value or "")))


def _host(url: str) -> str:
    rest = url.split("://", 1)[1] if "://" in url else url
    return re.split(r"[/?#]", rest, maxsplit=1)[0].lower()


def foreign_urls(text, allowed_base: str) -> list[str]:
    """The link-like parts of `text` whose host is not the host of `allowed_base`
    (for example APP_BASE_URL). An empty `allowed_base` allows no links."""
    allowed_host = _host(allowed_base.strip()) if allowed_base and allowed_base.strip() else ""
    found = []
    for match in _URL_RE.finditer(str(text or "")):
        url = match.group(0).rstrip(".,;:!?)")
        if allowed_host and _host(url) == allowed_host:
            continue
        found.append(url)
    return found
