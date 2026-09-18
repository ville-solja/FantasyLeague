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

RATE_LIMIT_GLOBAL = os.getenv("RATE_LIMIT_GLOBAL", "200/minute")

limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_GLOBAL])
