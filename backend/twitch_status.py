"""Twitch integration status (issue #180).

build_status() answers GET /admin/twitch/status: a checklist built from this
server's own Twitch settings, the approved-streamers table and the panel traffic
counters in twitch.py, plus the checks only the Twitch developer console can show.
Nothing returned holds a secret, its length, a token or a viewer's Twitch id.

RefusedOriginMiddleware records the host of each cross-origin /twitch/* request
whose origin CORS will refuse. It never blocks: CORSMiddleware stays the only
gate, and this one is given the same allow list.
"""
import base64
import binascii
import importlib.util
import os
import re
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

import steam_live
import twitch
import twitch_channels
import twitch_oauth
from models import TwitchChannelApproval

OK, WARNING, PROBLEM = "ok", "warning", "problem"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _is_production() -> bool:
    return _env("ENV").lower() == "production"


def _check(key: str, state: str, label: str, detail: str) -> dict:
    return {"key": key, "state": state, "label": label, "detail": detail}


def _secret_decodes(raw: str) -> bool:
    """Whether the extension secret is base64 (standard or URL-safe alphabet), as
    verify_twitch_jwt decodes it. Only the outcome leaves this function."""
    value = raw.strip().strip('"').strip("'")
    if not value:
        return False
    padded = value.translate(str.maketrans("-_", "+/")) + "=" * (-len(value) % 4)
    try:
        return len(base64.b64decode(padded, validate=True)) > 0
    except (binascii.Error, ValueError):
        return False


def _client_id_check() -> dict:
    client_id = _env("TWITCH_EXTENSION_CLIENT_ID")
    label = "TWITCH_EXTENSION_CLIENT_ID"
    if not client_id:
        return _check("extension_client_id", PROBLEM, label,
                      "Not set: CORS allows no extension origin, so the panel can't reach this "
                      "server. Set it to the extension's Client ID from the Twitch console.")
    return _check("extension_client_id", OK, label,
                  f"Set. CORS allows the extension origin https://{client_id}.ext-twitch.tv; "
                  "it must match the Client ID of the installed extension.")


def _secret_check() -> dict:
    raw = os.getenv("TWITCH_EXTENSION_SECRET", "")
    label = "TWITCH_EXTENSION_SECRET"
    if not raw.strip().strip('"').strip("'"):
        return _check("extension_secret", PROBLEM, label,
                      "Not set: every panel request fails with a server error. Copy the key from "
                      "Extension Secrets in the Twitch console.")
    if not _secret_decodes(raw):
        return _check("extension_secret", PROBLEM, label,
                      "Set but not valid base64: every panel request fails. Copy the key from "
                      "Extension Secrets in the Twitch console again.")
    return _check("extension_secret", OK, label,
                  "Set and decodes as base64. If panel tokens are still refused, the key belongs "
                  "to another extension.")


def _version_check() -> dict:
    label = "TWITCH_EXTENSION_VERSION"
    if not _env("TWITCH_EXTENSION_VERSION"):
        return _check("extension_version", WARNING, label,
                      "Not set: MVP chat announcements are skipped. Set it to the installed "
                      "extension version.")
    return _check("extension_version", OK, label,
                  "Set. It must match the installed version for chat announcements.")


def _local_dev_check() -> dict:
    label = "TWITCH_LOCAL_DEV"
    if _env("TWITCH_LOCAL_DEV") != "true":
        return _check("local_dev", OK, label, "Off: Twitch tokens are checked.")
    if _is_production():
        return _check("local_dev", PROBLEM, label,
                      "On with ENV=production: every panel request is refused. Turn it off.")
    return _check("local_dev", WARNING, label,
                  "On: Twitch tokens are not checked and every request acts as one test "
                  "broadcaster. Turn it off on any server Twitch calls.")


def _mvp_channels_check(db: Session) -> dict:
    env_count = len(twitch_channels.env_channels())
    approved = len(twitch_channels.portal_approved(db))
    pending = (db.query(TwitchChannelApproval)
               .filter(TwitchChannelApproval.status == twitch_channels.PENDING).count())
    label = "MVP channels"
    counts = (f"{env_count} from TWITCH_MVP_CHANNEL_IDS, {approved} approved in the portal, "
              f"{pending} waiting.")
    if env_count or approved:
        return _check("mvp_channels", OK, label, counts)
    if not _is_production():
        return _check("mvp_channels", OK, label,
                      f"{counts} Outside production any channel may set MVPs.")
    if pending:
        return _check("mvp_channels", WARNING, label,
                      f"{counts} No channel can set MVPs: approve one under Approved streamers.")
    return _check("mvp_channels", PROBLEM, label,
                  f"{counts} With ENV=production no channel can set MVPs. Open the MVP tool on "
                  "the channel, then approve it under Approved streamers.")


def _connect_twitch_check() -> dict:
    label = "Connect Twitch (TWITCH_OAUTH_*)"
    keys = ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI")
    set_count = sum(1 for k in keys if _env(k))
    if twitch_oauth.oauth_config() is None:
        if set_count:
            return _check("connect_twitch", WARNING, label,
                          "Only some of the three TWITCH_OAUTH_* settings are set, so Connect "
                          "Twitch is off. Set all three or none.")
        return _check("connect_twitch", WARNING, label,
                      "Off: website accounts can't connect Twitch, and channel names are not "
                      "looked up.")
    if importlib.util.find_spec("cryptography") is None:
        return _check("connect_twitch", PROBLEM, label,
                      "Set, but the cryptography package is missing, so Twitch sign-in fails. "
                      "Install the backend requirements.")
    return _check("connect_twitch", OK, label, "All three set; the cryptography package is installed.")


def _app_base_url_check() -> dict:
    if not _env("APP_BASE_URL"):
        return _check("app_base_url", WARNING, "APP_BASE_URL",
                      "Not set: the expected console values below can't be shown, and sign-in "
                      "redirects may fail. Set it to this server's public URL.")
    return _check("app_base_url", OK, "APP_BASE_URL", "Set.")


def _steam_key_check() -> dict:
    if not steam_live.STEAM_API_KEY:
        return _check("steam_api_key", WARNING, "STEAM_API_KEY",
                      "Not set: live games are not listed in the MVP tool until their stats "
                      "arrive.")
    return _check("steam_api_key", OK, "STEAM_API_KEY", "Set: live games are listed.")


def _backend_origin() -> str | None:
    base = _env("APP_BASE_URL").rstrip("/")
    if not base:
        return None
    try:
        parts = urlsplit(base)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _console() -> list[dict]:
    base = _env("APP_BASE_URL").rstrip("/")
    origin = _backend_origin()
    unknown = "This server's public origin (set APP_BASE_URL to show it here)"
    return [
        {"label": "Version › Capabilities › Allowlist for URL Fetching Domains contains the backend origin",
         "expected": origin or unknown},
        {"label": "The global configuration's ebs_url is the backend URL (set-ebs-url.sh)",
         "expected": base or "This server's public URL (set APP_BASE_URL to show it here)"},
        {"label": "The installed version was packaged with this backend's origin "
                  "(its configuration page lists the packaged origins)",
         "expected": (f"package.sh <version> --ebs-origin {origin}" if origin
                      else "package.sh <version> --ebs-origin <this server's origin>")},
    ]


def build_status(db: Session) -> dict:
    return {
        "checks": [
            _client_id_check(),
            _secret_check(),
            _version_check(),
            _local_dev_check(),
            _mvp_channels_check(db),
            _connect_twitch_check(),
            _app_base_url_check(),
            _steam_key_check(),
        ],
        "traffic": twitch.traffic_snapshot(),
        "console": _console(),
    }


# ---------------------------------------------------------------------------
# Refused cross-origin hosts on /twitch/*
# ---------------------------------------------------------------------------

def _origin_netloc(origin: str) -> str | None:
    try:
        return urlsplit(origin).netloc.lower() or None
    except ValueError:
        return None


class RefusedOriginMiddleware:
    """Record (never block) the host of a cross-origin /twitch/* request whose Origin
    is neither allowed by CORS (same `allow_origins` / `allow_origin_regex`) nor the
    request's own host or APP_BASE_URL's (the main site's cookie routes are same-origin)."""

    def __init__(self, app, allow_origins=(), allow_origin_regex: str | None = None):
        self.app = app
        self.allow_origins = set(allow_origins)
        self.allow_origin_regex = re.compile(allow_origin_regex) if allow_origin_regex else None

    def _allowed(self, origin: str) -> bool:
        if "*" in self.allow_origins or origin in self.allow_origins:
            return True
        return bool(self.allow_origin_regex and self.allow_origin_regex.fullmatch(origin))

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path", "").startswith("/twitch/"):
            headers = {k.decode("latin-1"): v.decode("latin-1")
                       for k, v in scope.get("headers") or [] if k in (b"origin", b"host")}
            origin = headers.get("origin")
            if origin and not self._allowed(origin):
                same_site = {headers.get("host", "").lower(), _origin_netloc(_env("APP_BASE_URL"))}
                netloc = _origin_netloc(origin)
                if netloc is None or netloc not in same_site:
                    twitch.record_refused_origin(origin)
        await self.app(scope, receive, send)
