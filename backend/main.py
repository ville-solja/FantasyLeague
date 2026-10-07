import logging
import os
import re
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from twitch import router as twitch_router
import twitch as twitch_module
import twitch_oauth
import steam_openid
import login_mode
import card_points
import database
import sessions
import soft_accounts
from database import SessionLocal, engine, Base, DATABASE_URL, get_db, backup_sqlite_db, cleanup_old_backups, backup_retention_days
from rate_limit import limiter
from models import League, LiveMatch, PlayerMatchStats, Week, Weight
from migrate import run_migrations
from ingest import ingest_league, store_live_matches, retry_unparsed_matches, INGEST_LOCK
import steam_live
from enrich import run_enrichment, run_profile_enrichment
from seed import seed_users, seed_admin_from_env, seed_weights, seed_tags
from weeks import auto_lock_weeks, due_substitutions, generate_weekly_summaries
from toornament import sync_toornament_results
from image import _ASSETS_DIR
from routers import players as players_router
from routers import auth as auth_router
from routers import profile as profile_router
from routers import leaderboard as leaderboard_router
from routers import cards as cards_router
from routers import admin_users as admin_users_router
from routers import admin_twitch as admin_twitch_router
from routers import admin_ingest as admin_ingest_router
from routers import admin_weeks as admin_weeks_router
from routers import admin_notifications as admin_notifications_router
from routers import admin_tags as admin_tags_router
from routers import admin_players as admin_players_router
from routers import admin_leagues as admin_leagues_router
from routers import admin_season as admin_season_router
from routers import admin_backups as admin_backups_router
from routers import admin_matches as admin_matches_router
from routers import admin_demo as admin_demo_router
from routers import weekly_summary as weekly_summary_router

logger = logging.getLogger(__name__)
# API keys travel in query strings (STEAM_API_KEY, OPENDOTA_API_KEY), and urllib3's
# DEBUG line logs the full request URL. Keep it at INFO even when DEBUG=true sets the
# root logger to DEBUG; a logger's own level wins over the root's.
logging.getLogger("urllib3").setLevel(logging.INFO)
# Issue #160: the Twitch sign-in callback URL carries a one-time code and state; keep
# them out of uvicorn's access log. Issue #150: the same for the Steam OpenID assertion.
logging.getLogger("uvicorn.access").addFilter(twitch_oauth.RedactSignInQuery())

_stop_event = threading.Event()

TOKEN_NAME     = os.getenv("TOKEN_NAME", "Tokens")
INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))
_APP_VERSION   = os.getenv("APP_VERSION", "APP_VERSION")
_APP_RELEASE   = os.getenv("APP_RELEASE", "")
_DEMO_MODE     = os.getenv("DEMO_MODE", "").lower() == "true"

_WEEK_CHECK_INTERVAL       = int(os.getenv("WEEK_CHECK_INTERVAL",        "300"))
_INGEST_POLL_INTERVAL      = int(os.getenv("INGEST_POLL_INTERVAL",       "900"))
_INGEST_LIVE_POLL_INTERVAL = int(os.getenv("INGEST_LIVE_POLL_INTERVAL",  "120"))
_INGEST_LIVE_MATCH_POLL_INTERVAL = int(os.getenv("INGEST_LIVE_MATCH_POLL_INTERVAL", "30"))
_LIVE_POLL_INTERVAL        = int(os.getenv("LIVE_POLL_INTERVAL",         "60"))
# A stored live match not ended and seen within this long counts as live for the ingest loop.
_LIVE_MATCH_FRESH_SECONDS  = 15 * 60
_INGEST_POST_MATCH_FAST_POLL_MINUTES = int(os.getenv("INGEST_POST_MATCH_FAST_POLL_MINUTES", "20"))
_INGEST_PARSE_RETRY_HOURS  = int(os.getenv("INGEST_PARSE_RETRY_HOURS",   "48"))
_ENRICHMENT_INTERVAL       = int(os.getenv("ENRICHMENT_CHECK_INTERVAL",  "300"))
_ENRICHMENT_BATCH_SIZE     = int(os.getenv("ENRICHMENT_BATCH_SIZE",      "3"))
_DB_BACKUP_INTERVAL_HOURS  = int(os.getenv("DB_BACKUP_INTERVAL_HOURS",   "24"))
_DB_BACKUP_RETENTION_DAYS  = backup_retention_days()
_SESSION_CLEANUP_INTERVAL  = 86400
_last_session_cleanup      = 0.0
# Issue #157: idle Twitch soft accounts are purged once a day by the week maintenance loop.
_SOFT_ACCOUNT_PURGE_INTERVAL = 86400
_SOFT_ACCOUNT_RETENTION_DAYS = soft_accounts.retention_days()
_last_soft_account_purge     = 0.0
# Issue #160: expired Twitch sign-in attempts and merge undo-log rows older than 30
# days are deleted once a day by the same loop.
_TWITCH_OAUTH_CLEANUP_INTERVAL = 86400
_last_twitch_oauth_cleanup     = 0.0
# Issue #150: used or expired Steam sign-in attempts and pending sign-ups, and OpenID
# nonces older than a day, are deleted once a day by the same loop.
_STEAM_CLEANUP_INTERVAL = 86400
_last_steam_cleanup     = 0.0


def _week_maintenance_loop():
    """Background thread: periodically lock weeks whose match window has opened,
    run bench substitutions SUBSTITUTION_DELAY_HOURS after a week ends (issue #129),
    and mark weeks whose scoring window has closed as available in the Weekly
    Report.

    Weeks themselves are created manually by admins (Week Management tab) —
    this loop no longer auto-generates them. Once a day it also deletes expired
    login sessions (issue #117), Twitch soft accounts idle for
    TWITCH_SOFT_ACCOUNT_RETENTION_DAYS (issue #157), and expired Twitch sign-in
    attempts and merge undo-log rows older than 30 days (issue #160), and Steam
    sign-in attempts, pending sign-ups and day-old OpenID nonces (issue #150).
    """
    global _last_session_cleanup, _last_soft_account_purge, _last_twitch_oauth_cleanup
    global _last_steam_cleanup
    while not _stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                auto_lock_weeks(db)
                due_substitutions(db)  # only matters when both fall due in the same tick; otherwise the report opens first with a "substitutions pending" note
                generate_weekly_summaries(db)
                if time.time() - _last_session_cleanup >= _SESSION_CLEANUP_INTERVAL:
                    deleted = sessions.cleanup_expired(db)
                    _last_session_cleanup = time.time()
                    if deleted:
                        logger.info("Deleted %d expired login session(s)", deleted)
                if time.time() - _last_soft_account_purge >= _SOFT_ACCOUNT_PURGE_INTERVAL:
                    soft_accounts.purge_inactive_soft_accounts(
                        db, int(time.time()), _SOFT_ACCOUNT_RETENTION_DAYS)
                    _last_soft_account_purge = time.time()
                if time.time() - _last_twitch_oauth_cleanup >= _TWITCH_OAUTH_CLEANUP_INTERVAL:
                    twitch_oauth.cleanup(db, int(time.time()))
                    _last_twitch_oauth_cleanup = time.time()
                if time.time() - _last_steam_cleanup >= _STEAM_CLEANUP_INTERVAL:
                    steam_openid.cleanup(db, int(time.time()))
                    _last_steam_cleanup = time.time()
            finally:
                db.close()
        except Exception:
            logger.exception("Week maintenance error")
        _stop_event.wait(timeout=_WEEK_CHECK_INTERVAL)


def _profile_enrichment_loop():
    """Background thread: periodically enrich player profiles with hero stats and AI bios."""
    while not _stop_event.is_set():
        try:
            with ThreadPoolExecutor(max_workers=1) as _executor:
                _future = _executor.submit(run_profile_enrichment, batch_size=_ENRICHMENT_BATCH_SIZE)
                try:
                    result = _future.result(timeout=300)  # 5-minute timeout
                    if result["enriched"] or result["errors"]:
                        logger.info("Profile enrichment: %s", result)
                except FuturesTimeoutError:
                    logging.warning("Profile enrichment timed out after 300s")
                except Exception as _e:
                    logging.error("Profile enrichment error: %s", _e)
        except Exception:
            logger.exception("Profile enrichment loop error")
        _stop_event.wait(timeout=_ENRICHMENT_INTERVAL)


def _auto_ingest(league_ids: list[int], live_league_ids: set[int]):
    for league_id in league_ids:
        try:
            logger.info("Auto-ingest: league %d starting", league_id)
            ingest_league(league_id)
            if league_id in live_league_ids:
                logger.info("Auto-ingest: league %d has a live match — skipping enrichment this cycle", league_id)
            else:
                logger.info("Auto-ingest: league %d has no live match — running enrichment", league_id)
                run_enrichment()
            logger.info("Auto-ingest: league %d done", league_id)
        except Exception:
            logger.exception("Auto-ingest: league %d failed", league_id)

    # Re-check recent matches that were ingested before OpenDota parsed the replay.
    # Skipped when nothing is monitored so a fresh/test DB never makes OpenDota calls.
    if league_ids and _INGEST_PARSE_RETRY_HOURS > 0:
        try:
            summary = retry_unparsed_matches(_INGEST_PARSE_RETRY_HOURS)
            logger.info("Parse retry: %s", summary)
        except Exception:
            logger.exception("Parse retry step failed")


def _run_toornament_sync():
    try:
        db = SessionLocal()
        try:
            result = sync_toornament_results(db)
        finally:
            db.close()
        logger.info("Toornament sync: %s", result)
    except Exception:
        logger.exception("Toornament sync error")


def _get_monitored_league_ids() -> list[int]:
    db = SessionLocal()
    try:
        return [l.id for l in db.query(League).filter(League.is_monitored == True).all()]
    finally:
        db.close()


def _has_active_week() -> bool:
    db = SessionLocal()
    try:
        now = int(time.time())
        return db.query(Week).filter(
            Week.start_time <= now, Week.end_time >= now, Week.is_locked == False
        ).first() is not None
    finally:
        db.close()


def _has_recently_ended_live_match(league_ids: list[int]) -> bool:
    """True if a stored live match of these leagues ended within
    INGEST_POST_MATCH_FAST_POLL_MINUTES and its stats are not ingested yet."""
    if not league_ids or _INGEST_POST_MATCH_FAST_POLL_MINUTES <= 0:
        return False
    cutoff = int(time.time()) - _INGEST_POST_MATCH_FAST_POLL_MINUTES * 60
    db = SessionLocal()
    try:
        ingested = db.query(PlayerMatchStats.id).filter(
            PlayerMatchStats.match_id == LiveMatch.match_id
        ).exists()
        return db.query(LiveMatch.match_id).filter(
            LiveMatch.league_id.in_(league_ids),
            LiveMatch.ended_at.isnot(None),
            LiveMatch.ended_at >= cutoff,
            ~ingested,
        ).first() is not None
    finally:
        db.close()


def _live_league_ids(league_ids: list[int]) -> set[int]:
    """Leagues with a stored live match that has not ended and was seen in the last
    15 minutes (written by the live thread)."""
    if not league_ids:
        return set()
    cutoff = int(time.time()) - _LIVE_MATCH_FRESH_SECONDS
    db = SessionLocal()
    try:
        rows = db.query(LiveMatch.league_id).filter(
            LiveMatch.league_id.in_(league_ids),
            LiveMatch.ended_at.is_(None),
            LiveMatch.last_seen_at >= cutoff,
        ).distinct().all()
        return {r[0] for r in rows}
    finally:
        db.close()


def _ingest_poll_loop():
    """Background thread: periodically ingest new matches then sync to toornament.
    Makes no live calls: which leagues are live comes from live_matches (_live_poll_loop)."""
    while not _stop_event.is_set():
        try:
            monitored = _get_monitored_league_ids()
            try:
                live = _live_league_ids(monitored)
            except Exception:
                logger.exception("Ingest poll: reading live matches failed")
                live = set()
            if live:
                logger.info("Ingest poll: monitored league(s) with a live match: %s", sorted(live))
            else:
                logger.info("Ingest poll: no monitored league has a live match")
            # Shared with the admin-triggered manual ingest endpoint so the two
            # never write the same league's data concurrently.
            with INGEST_LOCK:
                _auto_ingest(monitored, live)
                _run_toornament_sync()
            if live or _has_recently_ended_live_match(monitored):
                interval = _INGEST_LIVE_MATCH_POLL_INTERVAL
            elif _has_active_week():
                interval = _INGEST_LIVE_POLL_INTERVAL
            else:
                interval = _INGEST_POLL_INTERVAL
        except Exception:
            logger.exception("Unexpected error in ingest poll loop")
            interval = _INGEST_POLL_INTERVAL
        _stop_event.wait(timeout=interval)


def _live_poll_once():
    """One live check: Steam's live games of the monitored leagues into live_matches.
    A failed request keeps the stored rows as they are (none is marked ended)."""
    monitored = _get_monitored_league_ids()
    if not monitored or not steam_live.STEAM_API_KEY:
        return
    games = steam_live.get_live_league_games(monitored)
    if games is None:
        return
    store_live_matches(games, monitored)
    steam_live.live_checked_at = int(time.time())


def _live_poll_loop():
    """Background thread: check for live games every LIVE_POLL_INTERVAL seconds, apart
    from the ingest loop so ingest, enrichment and their backoffs never delay it."""
    while not _stop_event.is_set():
        try:
            _live_poll_once()
        except Exception:
            logger.exception("Live poll failed")
        _stop_event.wait(timeout=_LIVE_POLL_INTERVAL)


def _backup_loop():
    """Background thread: periodically snapshot the SQLite DB and prune old backups.

    Runs regardless of DEMO_MODE (like week maintenance) since it's the only
    thing standing between a crashed/corrupted volume and total data loss —
    scripts/backup-db.sh and the season-reset backup are both manual/one-off.
    """
    while not _stop_event.is_set():
        try:
            path = backup_sqlite_db()
            if path:
                logger.info("Automatic DB backup created: %s", path)
                deleted = cleanup_old_backups(_DB_BACKUP_RETENTION_DAYS)
                if deleted:
                    logger.info("Pruned %d backup(s) older than %d day(s)", deleted, _DB_BACKUP_RETENTION_DAYS)
        except Exception:
            logger.exception("Automatic DB backup failed")
        _stop_event.wait(timeout=_DB_BACKUP_INTERVAL_HOURS * 3600)


def _start_background_threads():
    if _DEMO_MODE:
        logger.info("Ingest poll thread skipped (DEMO_MODE=true)")
        logger.info("Live poll thread skipped (DEMO_MODE=true)")
    else:
        threading.Thread(target=_ingest_poll_loop, daemon=True).start()
        logger.info("Ingest poll thread started (interval=%ds)", _INGEST_POLL_INTERVAL)
        if steam_live.STEAM_API_KEY:
            threading.Thread(target=_live_poll_loop, daemon=True).start()
            logger.info("Live poll thread started (interval=%ds)", _LIVE_POLL_INTERVAL)
        else:
            logger.warning("STEAM_API_KEY is not set: live-game detection is off, so matches "
                           "reach the Twitch MVP picker only after ingest")
    threading.Thread(target=_week_maintenance_loop, daemon=True).start()
    logger.info("Week maintenance thread started (interval=%ds)", _WEEK_CHECK_INTERVAL)
    threading.Thread(target=_profile_enrichment_loop, daemon=True).start()
    logger.info("Profile enrichment thread started (interval=%ds)", _ENRICHMENT_INTERVAL)
    threading.Thread(target=_backup_loop, daemon=True).start()
    logger.info("DB backup thread started (interval=%dh, retention=%dd)",
                _DB_BACKUP_INTERVAL_HOURS, _DB_BACKUP_RETENTION_DAYS)


def _ensure_card_points_current():
    """Rebuild stored card points when the table is empty or the weights changed since
    the last build (issue #141). A failure is logged and leaves the previous rows."""
    db = database.SessionLocal()
    try:
        rows = card_points.ensure_card_points_current(db)
        if rows is not None:
            logger.info("Startup: rebuilt %d stored card points", rows)
    except Exception:
        logger.exception("Startup: stored card points check failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_level = logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logger.info("DB: %s", DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    seed_users()
    login_mode.log_startup()
    seed_admin_from_env()
    seed_weights()
    _ensure_card_points_current()
    seed_tags()
    if os.getenv("TWITCH_LOCAL_DEV", "").lower() == "true":
        if os.getenv("SECRET_KEY"):
            raise RuntimeError(
                "TWITCH_LOCAL_DEV=true must not be set when SECRET_KEY is configured — "
                "this bypass must never run in production"
            )
    twitch_module.warn_if_mvp_channels_unset()
    if _DEMO_MODE:
        logger.warning(
            "[DEMO MODE] DEMO_MODE=true — clock override and demo account seeding "
            "endpoints are active. NEVER enable in production."
        )
    if os.getenv("BACKGROUND_TASKS_ENABLED", "true").lower() != "false":
        _start_background_threads()
    else:
        # The test suite disables these: they share the tests' in-memory DB
        # connection and outlive the test that started them.
        logger.info("Background tasks disabled (BACKGROUND_TASKS_ENABLED=false)")
    yield
    _stop_event.set()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
_secret_key = os.environ.get("SECRET_KEY", "")
_is_dev = os.getenv("TWITCH_LOCAL_DEV") == "true" or os.getenv("DEBUG", "").lower() == "true"
_MIN_PRODUCTION_SECRET_LEN = 32
if os.getenv("ENV", "").lower() == "production":
    _active_dev_flags = [
        name for name in ("DEBUG", "TWITCH_LOCAL_DEV")
        if os.getenv(name, "").lower() == "true"
    ]
    if _active_dev_flags:
        raise RuntimeError(
            f"[SECURITY] ENV=production but {' and '.join(f'{n}=true' for n in _active_dev_flags)} "
            "is set. Dev bypasses must never run in production — unset them."
        )
    if len(_secret_key) < _MIN_PRODUCTION_SECRET_LEN:
        raise RuntimeError(
            f"[SECURITY] ENV=production requires a SECRET_KEY of at least "
            f"{_MIN_PRODUCTION_SECRET_LEN} characters (got {len(_secret_key)})."
        )
if not _secret_key:
    if not _is_dev:
        raise RuntimeError(
            "[SECURITY] SECRET_KEY is not set. Set SECRET_KEY in your environment. "
            "To bypass this check in local dev, set DEBUG=true or TWITCH_LOCAL_DEV=true."
        )
    warnings.warn(
        "[SECURITY] SECRET_KEY not set — using insecure default. Only acceptable in local dev.",
        stacklevel=1,
    )
    _secret_key = "dev-secret-change-me"
_https_only = os.getenv("HTTPS_ONLY", "false").lower() == "true"
if _https_only and os.getenv("TWITCH_LOCAL_DEV", "").lower() == "true":
    # HTTPS_ONLY is a production signal that doesn't depend on ENV (issue #165).
    raise RuntimeError(
        "[SECURITY] TWITCH_LOCAL_DEV=true is not allowed with HTTPS_ONLY=true. "
        "The Twitch JWT bypass must never run on a TLS-served deployment."
    )
if not _https_only and not _is_dev:
    raise RuntimeError(
        "[SECURITY] HTTPS_ONLY is not set. Session cookies would be sent without the Secure "
        "flag, making them interceptable over unencrypted connections. Set HTTPS_ONLY=true "
        "once the app is behind a TLS-terminating reverse proxy (nginx, Caddy, etc.). "
        "To bypass this check in local dev, set DEBUG=true or TWITCH_LOCAL_DEV=true."
    )

# The six session limits (and the SESSION_MAX_AGE_SECONDS alias) are validated when
# `sessions` is imported above, so a bad value already stopped startup. The server
# enforces the limits; the cookie only has to outlive the longest of them.
SESSION_COOKIE_MAX_AGE = sessions.COOKIE_MAX_AGE
# __Host- pins the cookie to this exact host (Secure, Path=/, no Domain). Browsers
# reject the prefix without Secure, so plain-HTTP local dev keeps "session".
SESSION_COOKIE_NAME = "__Host-session" if _https_only else "session"

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv"
        )
        if _https_only:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key,
    session_cookie=SESSION_COOKIE_NAME,
    # Must stay "lax": the Twitch sign-in callback (GET /auth/twitch/callback, issue
    # #160) is a cross-site top-level GET from id.twitch.tv and needs the session
    # cookie to know which player started the flow. "strict" would drop the cookie
    # there and every callback would fail with "no session".
    same_site="lax",
    https_only=_https_only,
    path="/",
    max_age=SESSION_COOKIE_MAX_AGE,
)
app.add_middleware(SecurityHeadersMiddleware)


_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _url_host(url: str, scheme_hint: str | None = None) -> str | None:
    """Return lower-cased host[:port] of a URL (default port dropped), or None when unparseable.

    With scheme_hint, `url` is a bare Host header value such as "example.com:8000".
    """
    try:
        parts = urlsplit(f"//{url}" if scheme_hint else url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    scheme = scheme_hint or parts.scheme.lower()
    if not scheme or not host:
        return None
    # A TLS-terminating proxy may forward https traffic as http, so a bare
    # Host header drops either default port.
    defaults = set(_DEFAULT_PORTS.values()) if scheme_hint else {_DEFAULT_PORTS.get(scheme)}
    if port is None or port in defaults:
        return host
    return f"{host}:{port}"


# /twitch/* routes use a Twitch JWT, except these, which use the session cookie
# (called from the main site's Profile tab, issue #160) and so get the Origin check too.
_COOKIE_AUTH_TWITCH_PATHS = {"/twitch/merge/confirm", "/twitch/disconnect"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Refuse cross-origin state-changing requests (issue #136).

    The session cookie is SameSite=Lax, which does not stop same-site sibling
    subdomains (e.g. test.kana-cards.com). Unsafe methods carrying an Origin
    (or, failing that, a Referer) whose host matches neither the request Host
    nor APP_BASE_URL get 403. Requests with neither header (API clients,
    tests) pass. /twitch/* uses a JWT in Authorization, not the cookie, and is
    called from the extension origin, so it is exempt, except the cookie-auth
    routes in _COOKIE_AUTH_TWITCH_PATHS. Settings are read per
    request so CSRF_ORIGIN_CHECK / APP_BASE_URL changes need no reload.
    """

    async def dispatch(self, request: Request, call_next):
        if (
            request.method in _UNSAFE_METHODS
            and (not request.url.path.startswith("/twitch/")
                 or request.url.path in _COOKIE_AUTH_TWITCH_PATHS)
            and os.getenv("CSRF_ORIGIN_CHECK", "true").lower() != "false"
        ):
            source = request.headers.get("origin") or request.headers.get("referer")
            if source:
                source_host = _url_host(source)
                allowed = set()
                req_host = _url_host(request.headers.get("host", "").strip(), request.url.scheme)
                if req_host:
                    allowed.add(req_host)
                base_url = os.getenv("APP_BASE_URL", "")
                if base_url:
                    base_host = _url_host(base_url)
                    if base_host:
                        allowed.add(base_host)
                if source_host is None or source_host not in allowed:
                    return JSONResponse(
                        {"detail": "Cross-origin request refused"}, status_code=403
                    )
        return await call_next(request)


app.add_middleware(OriginCheckMiddleware)
# Only our Twitch extension iframe (https://<TWITCH_EXTENSION_CLIENT_ID>.ext-twitch.tv)
# calls the API cross-origin; the main site is same-origin and needs no CORS.
# Issue #171: other extensions' origins are refused, and without a client id no
# ext-twitch.tv origin is allowed. All /twitch/* endpoints authenticate via JWT in
# the Authorization header, not cookies, so allow_credentials stays False.
# CORS_EXTRA_ORIGINS adds origins such as http://localhost:8080 for Twitch Local Test.
_cors_extra_origins = [
    o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()
]
_ext_client_id = os.getenv("TWITCH_EXTENSION_CLIENT_ID", "").strip()
_ext_origin_regex = (rf"^https://{re.escape(_ext_client_id)}\.ext-twitch\.tv$"
                     if _ext_client_id else None)
if not _ext_client_id:
    logger.warning("TWITCH_EXTENSION_CLIENT_ID unset: no Twitch extension origin is allowed by CORS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_extra_origins,
    allow_origin_regex=_ext_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Must be a plain (sync) function, not `async def`: SlowAPIMiddleware's
    # global baseline check runs inside a synchronous code path
    # (slowapi.middleware.sync_check_limits) and cannot await a coroutine
    # handler — it silently falls back to slowapi's own {"error": ...} shape
    # for any exception_handler where inspect.iscoroutinefunction() is True.
    # Route-level @limiter.limit(...) violations go through FastAPI's normal
    # (async-aware) exception handling and would work with either, but this
    # handler must stay sync so the app-wide middleware path also gets this
    # app's {"detail": ...} shape instead.
    return JSONResponse(status_code=429, content={"detail": f"Rate limit exceeded: {exc.detail}"})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(twitch_router)
app.include_router(twitch_oauth.router)
app.include_router(steam_openid.router)
app.include_router(players_router.router)
app.include_router(auth_router.router)
app.include_router(profile_router.router)
app.include_router(leaderboard_router.router)
app.include_router(cards_router.router)
app.include_router(admin_users_router.router)
app.include_router(admin_twitch_router.router)
app.include_router(admin_ingest_router.router)
app.include_router(admin_weeks_router.router)
app.include_router(admin_notifications_router.router)
app.include_router(admin_tags_router.router)
app.include_router(admin_players_router.router)
app.include_router(admin_leagues_router.router)
app.include_router(admin_season_router.router)
app.include_router(admin_backups_router.router)
app.include_router(admin_matches_router.router)
app.include_router(admin_demo_router.router)
app.include_router(weekly_summary_router.router)


@app.api_route("/twitch/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
def _twitch_unknown_route(rest: str):
    """Unknown /twitch/* paths, such as the retired POST /twitch/link-code, POST
    /twitch/link and GET /twitch/status (issue #160), answer 404 rather than the
    static frontend mount's 405 for non-GET methods."""
    raise HTTPException(status_code=404, detail="Not Found")


@app.api_route("/auth/steam/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
def _steam_unknown_route(rest: str):
    """Unknown /auth/steam/* paths (and every Steam route in password mode, issue #150)
    answer 404 rather than the static frontend mount's 405 for non-GET methods."""
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/config")
def get_config(db=Depends(get_db)):
    needed = {"team_booster_cost", "draw_rate_common", "draw_rate_rare", "draw_rate_epic", "draw_rate_legendary"}
    weights = {w.key: w.value for w in db.query(Weight).filter(Weight.key.in_(needed)).all()}

    booster_cost = int(weights.get("team_booster_cost", 3))

    defaults = {"draw_rate_common": 60.0, "draw_rate_rare": 25.0,
                "draw_rate_epic": 10.0, "draw_rate_legendary": 5.0}
    raw = {key: float(weights.get(key, defaults[key])) for key in defaults}
    total = sum(raw.values()) or 1.0
    draw_rates = {
        "common":    round(raw["draw_rate_common"]    / total * 100, 1),
        "rare":      round(raw["draw_rate_rare"]      / total * 100, 1),
        "epic":      round(raw["draw_rate_epic"]      / total * 100, 1),
        "legendary": round(raw["draw_rate_legendary"] / total * 100, 1),
    }

    return {
        "token_name": TOKEN_NAME,
        "initial_tokens": INITIAL_TOKENS,
        "app_version": _APP_VERSION,
        "app_release": _APP_RELEASE,
        "team_booster_cost": booster_cost,
        "draw_rates": draw_rates,
        # Read live (not the startup-frozen _DEMO_MODE) so tests toggling the env
        # var per-case observe the current value without reimporting the module.
        "demo_mode": os.getenv("DEMO_MODE", "").lower() == "true",
        # Issue #144 — automatic first-visit guided tour; off unless exactly "true".
        "tour_autostart": os.getenv("GUIDED_TOUR_AUTOSTART", "false").strip().lower() == "true",
        # Issue #150 — password | both | steam_signup; the login page and Profile follow it.
        "login_method": login_mode.current(),
    }


@app.get("/health")
def health(db=Depends(get_db)):
    """Readiness check, not just liveness — verifies the DB is actually reachable rather than
    only that the ASGI process is accepting requests. See reference/container-health-check.md.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check DB connectivity failure")
        return JSONResponse(status_code=503, content={"status": "error"})
    return {"status": "ok"}


_FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if not os.path.isdir(_FRONTEND_DIR):
    _FRONTEND_DIR = "frontend"  # docker image copies to /app/frontend

_TWITCH_EXT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "twitch-extension"))
if not os.path.isdir(_TWITCH_EXT_DIR):
    _TWITCH_EXT_DIR = "twitch-extension"
if os.path.isdir(_TWITCH_EXT_DIR):
    app.mount("/twitch-ext", StaticFiles(directory=_TWITCH_EXT_DIR), name="twitch-extension")

if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
