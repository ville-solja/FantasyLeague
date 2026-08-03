import logging
import os
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from twitch import router as twitch_router
from database import SessionLocal, engine, Base, DATABASE_URL, get_db
from models import League, Week, Weight
from migrate import run_migrations
from ingest import ingest_league
from enrich import run_enrichment, run_profile_enrichment
from seed import seed_users, seed_admin_from_env, seed_weights, seed_tags
from weeks import auto_lock_weeks
from toornament import sync_toornament_results
from image import _ASSETS_DIR
from routers import players as players_router
from routers import auth as auth_router
from routers import profile as profile_router
from routers import leaderboard as leaderboard_router
from routers import cards as cards_router
from routers import admin as admin_router

logger = logging.getLogger(__name__)

_stop_event = threading.Event()

TOKEN_NAME     = os.getenv("TOKEN_NAME", "Tokens")
INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))
_APP_VERSION   = os.getenv("APP_VERSION", "APP_VERSION")
_APP_RELEASE   = os.getenv("APP_RELEASE", "")
_DEMO_MODE     = os.getenv("DEMO_MODE", "").lower() == "true"

_WEEK_CHECK_INTERVAL       = int(os.getenv("WEEK_CHECK_INTERVAL",        "300"))
_INGEST_POLL_INTERVAL      = int(os.getenv("INGEST_POLL_INTERVAL",       "900"))
_INGEST_LIVE_POLL_INTERVAL = int(os.getenv("INGEST_LIVE_POLL_INTERVAL",  "120"))
_ENRICHMENT_INTERVAL       = int(os.getenv("ENRICHMENT_CHECK_INTERVAL",  "300"))
_ENRICHMENT_BATCH_SIZE     = int(os.getenv("ENRICHMENT_BATCH_SIZE",      "3"))


def _week_maintenance_loop():
    """Background thread: periodically lock weeks whose match window has opened.

    Weeks themselves are created manually by admins (Week Management tab) —
    this loop no longer auto-generates them.
    """
    while not _stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                auto_lock_weeks(db)
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


def _auto_ingest(league_ids: list[int]):
    for league_id in league_ids:
        try:
            logger.info("Auto-ingest: league %d starting", league_id)
            ingest_league(league_id)
            run_enrichment()
            logger.info("Auto-ingest: league %d done", league_id)
        except Exception:
            logger.exception("Auto-ingest: league %d failed", league_id)


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


def _ingest_poll_loop():
    """Background thread: periodically ingest new matches then sync to toornament."""
    while not _stop_event.is_set():
        try:
            _auto_ingest(_get_monitored_league_ids())
            _run_toornament_sync()
            interval = _INGEST_LIVE_POLL_INTERVAL if _has_active_week() else _INGEST_POLL_INTERVAL
        except Exception:
            logger.exception("Unexpected error in ingest poll loop")
            interval = _INGEST_POLL_INTERVAL
        _stop_event.wait(timeout=interval)


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
    seed_admin_from_env()
    seed_weights()
    seed_tags()
    if os.getenv("TWITCH_LOCAL_DEV", "").lower() == "true":
        if os.getenv("SECRET_KEY"):
            raise RuntimeError(
                "TWITCH_LOCAL_DEV=true must not be set when SECRET_KEY is configured — "
                "this bypass must never run in production"
            )
    if _DEMO_MODE:
        logger.warning(
            "[DEMO MODE] DEMO_MODE=true — clock override and demo account seeding "
            "endpoints are active. NEVER enable in production."
        )
        logger.info("Ingest poll thread skipped (DEMO_MODE=true)")
    else:
        threading.Thread(target=_ingest_poll_loop, daemon=True).start()
        logger.info("Ingest poll thread started (interval=%ds)", _INGEST_POLL_INTERVAL)
    threading.Thread(target=_week_maintenance_loop, daemon=True).start()
    logger.info("Week maintenance thread started (interval=%ds)", _WEEK_CHECK_INTERVAL)
    threading.Thread(target=_profile_enrichment_loop, daemon=True).start()
    logger.info("Profile enrichment thread started (interval=%ds)", _ENRICHMENT_INTERVAL)
    yield
    _stop_event.set()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
_secret_key = os.environ.get("SECRET_KEY", "")
_is_dev = os.getenv("TWITCH_LOCAL_DEV") == "true" or os.getenv("DEBUG", "").lower() == "true"
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
    same_site="lax",
    https_only=_https_only,
    max_age=86400,
)
app.add_middleware(SecurityHeadersMiddleware)
# Twitch extension iframes are served from *.ext-twitch.tv — a different origin.
# All /twitch/* endpoints authenticate via JWT (not cookies), so allow_origins="*"
# is safe: cross-origin requests cannot carry session cookies, so regular
# session-protected endpoints are unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must stay False with allow_origins="*" — see comment above
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(twitch_router)
app.include_router(players_router.router)
app.include_router(auth_router.router)
app.include_router(profile_router.router)
app.include_router(leaderboard_router.router)
app.include_router(cards_router.router)
app.include_router(admin_router.router)


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
    }


@app.get("/health")
def health():
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
