"""Which ways in the website accepts (issue #150), from the LOGIN_METHOD env var.

  password      password sign-in and registration; every Steam route answers 404 (default)
  both          password or Steam sign-in; password registration or Steam sign-up
  steam_signup  password sign-in for existing accounts or Steam; new accounts only via Steam

LOGIN_METHOD is read on every call, so tests and operators can switch modes without
a reload. An unknown value is logged once and treated as `password`. The value
`steam` is reserved for issue #172 (Steam-only sign-in, not built yet): it is logged
as not available and treated as `steam_signup`, so it never reopens registration.
"""
import logging
import os

from fastapi import HTTPException

logger = logging.getLogger(__name__)

LOCAL_LOGIN = "password"  # username and password accounts
BOTH = "both"
STEAM_SIGNUP = "steam_signup"
MODES = (LOCAL_LOGIN, BOTH, STEAM_SIGNUP)
STEAM_MODES = (BOTH, STEAM_SIGNUP)

# Issue #172's future mode, accepted early so setting it never reopens registration.
_FUTURE_STEAM_ONLY = "steam"

_warned: set[str] = set()


def _warn_once(value: str, message: str, *args) -> None:
    if value not in _warned:
        _warned.add(value)
        logger.warning(message, *args)


def current() -> str:
    """The active mode (one of MODES)."""
    raw = os.getenv("LOGIN_METHOD")
    value = (raw or "").strip().lower()
    if not value:
        return LOCAL_LOGIN
    if value in MODES:
        return value
    if value == _FUTURE_STEAM_ONLY:
        _warn_once(value, "LOGIN_METHOD=steam is not available yet (issue #172); "
                          "using steam_signup")
        return STEAM_SIGNUP
    _warn_once(value, "LOGIN_METHOD=%r is not a known login method (password, both, "
                      "steam_signup); using password", raw)
    return LOCAL_LOGIN


def steam_enabled() -> bool:
    return current() in STEAM_MODES


def require_login_methods(*modes: str):
    """A route dependency: the route answers 404 outside the given modes."""
    allowed = frozenset(modes)

    def _check():
        if current() not in allowed:
            raise HTTPException(status_code=404, detail="Not Found")
    return _check


require_steam = require_login_methods(*STEAM_MODES)
require_password_registration = require_login_methods(LOCAL_LOGIN, BOTH)


def app_base_url() -> str | None:
    """APP_BASE_URL without a trailing slash, or None when unset."""
    base = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    return base or None


def log_startup() -> None:
    """Start-up checks: an unknown mode is logged by current(); Steam modes need
    APP_BASE_URL to build the OpenID return address."""
    mode = current()
    logger.info("Login method: %s", mode)
    if mode in STEAM_MODES and app_base_url() is None:
        logger.warning("LOGIN_METHOD=%s but APP_BASE_URL is not set: Steam sign-in answers "
                       "503 steam_unavailable until it is", mode)
