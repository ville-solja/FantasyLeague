"""Shared slowapi Limiter instance.

Kept in its own module (rather than defined directly in main.py) to avoid a
circular import: main.py imports the routers (including routers/auth.py),
and routers/auth.py needs to import the limiter back to decorate its routes.
Both main.py and routers/auth.py import `limiter` from here instead.

RATE_LIMIT_GLOBAL is read at module-import time (a plain module-level
constant), matching how the rest of the app reads its env-based config
(e.g. main.py's TOKEN_NAME/INITIAL_TOKENS). Tests that need a different
value must set the env var before this module is (re)imported.
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

RATE_LIMIT_GLOBAL = os.getenv("RATE_LIMIT_GLOBAL", "200/minute")

limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_GLOBAL])


def key_by_user_or_ip(request: Request) -> str:
    """Rate-limit key for authenticated routes: the session user's id if present,
    otherwise fall back to source IP (defensive — these routes require login, so this
    branch should not normally be reached). The id is set on request.state by
    deps.get_current_user, which FastAPI resolves before the limit is checked; the
    session cookie itself carries only a session ID (issue #117)."""
    user_id = getattr(getattr(request, "state", None), "session_user_id", None)
    return f"user:{user_id}" if user_id else get_remote_address(request)


def key_by_twitch_viewer_or_ip(request: Request) -> str:
    """Rate-limit key for the Twitch panel's game routes (issue #157): the viewer's
    opaque Twitch id, set on request.state by twitch.verify_twitch_jwt (resolved before
    the limit is checked), else the source IP."""
    opaque_id = getattr(getattr(request, "state", None), "twitch_opaque_id", None)
    return f"twitch:{opaque_id}" if opaque_id else get_remote_address(request)
