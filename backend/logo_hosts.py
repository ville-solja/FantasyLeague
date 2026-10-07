"""Allowlist of image hosts a team logo URL may point at (issue #171).

A team's `logo_url` comes from ingested OpenDota data. Viewers' browsers load it
directly (Kana Cards, the Twitch panel) and the card-image route fetches it
server-side, so an arbitrary host would see viewers' IP addresses or receive
requests from the server. Only https URLs on LOGO_HOST_ALLOWLIST hosts (default:
Steam's CDNs, which OpenDota team logos use) are stored at ingest or returned.
"""
import os
from urllib.parse import urlsplit

DEFAULT_LOGO_HOSTS = (
    "steamcdn-a.akamaihd.net",
    "steamusercontent-a.akamaihd.net",
    "cdn.steamusercontent.com",
    "cdn.cloudflare.steamstatic.com",
    "shared.cloudflare.steamstatic.com",
)


def logo_hosts() -> frozenset[str]:
    """Allowed hosts from LOGO_HOST_ALLOWLIST (comma-separated, case-insensitive),
    read on each call; an empty value means the default Steam CDN list."""
    raw = os.getenv("LOGO_HOST_ALLOWLIST", "")
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return frozenset(hosts) if hosts else frozenset(DEFAULT_LOGO_HOSTS)


def safe_logo_url(url) -> str | None:
    """The URL (stripped) when it is https, has no port or userinfo, and its host is
    allowlisted; otherwise None (the client then shows the team monogram)."""
    if not isinstance(url, str):
        return None
    candidate = url.strip()
    if not candidate:
        return None
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or port is not None:
        return None
    netloc = parsed.netloc
    if "@" in netloc or ":" in netloc:
        return None
    host = (parsed.hostname or "").lower()
    return candidate if host and host in logo_hosts() else None
