import logging
import os
import threading
import time
import warnings
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from twitch import router as twitch_router
from database import SessionLocal, engine, Base, DATABASE_URL
from migrate import run_migrations
from ingest import ingest_league
from enrich import run_enrichment, run_profile_enrichment
from seed import seed_users, seed_cards, seed_weights
from weeks import generate_weeks, auto_lock_weeks
from toornament import sync_toornament_results
from image import _ASSETS_DIR
from routers import players as players_router
from routers import auth as auth_router
from routers import profile as profile_router
from routers import leaderboard as leaderboard_router
from routers import cards as cards_router
from routers import admin as admin_router

logger = logging.getLogger(__name__)

TOKEN_NAME     = os.getenv("TOKEN_NAME", "Tokens")
INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))
_APP_VERSION   = os.getenv("APP_VERSION", "APP_VERSION")
_APP_RELEASE   = os.getenv("APP_RELEASE", "")

_WEEK_CHECK_INTERVAL       = int(os.getenv("WEEK_CHECK_INTERVAL",       "300"))
_INGEST_POLL_INTERVAL      = int(os.getenv("INGEST_POLL_INTERVAL",      "900"))
_ENRICHMENT_INTERVAL       = int(os.getenv("ENRICHMENT_CHECK_INTERVAL", "300"))
_ENRICHMENT_BATCH_SIZE     = int(os.getenv("ENRICHMENT_BATCH_SIZE",     "3"))


def _week_maintenance_loop():
    """Background thread: periodically generate new weeks and lock past ones."""
    while True:
        try:
            db = SessionLocal()
            try:
                generate_weeks(db)
                auto_lock_weeks(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Week maintenance error")
        time.sleep(_WEEK_CHECK_INTERVAL)


def _profile_enrichment_loop():
    """Background thread: periodically enrich player profiles with hero stats and AI bios."""
    while True:
        try:
            result = run_profile_enrichment(batch_size=_ENRICHMENT_BATCH_SIZE)
            if result["enriched"] or result["errors"]:
                logger.info("Profile enrichment: %s", result)
        except Exception:
            logger.exception("Profile enrichment loop error")
        time.sleep(_ENRICHMENT_INTERVAL)


def _auto_ingest(league_ids: list[int]):
    for league_id in league_ids:
        try:
            logger.info("Auto-ingest: league %d starting", league_id)
            ingest_league(league_id)
            run_enrichment()
            seed_cards(league_id)
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


def _ingest_poll_loop(league_ids: list[int]):
    """Background thread: periodically ingest new matches then sync to toornament."""
    while True:
        try:
            _auto_ingest(league_ids)
            _run_toornament_sync()
        except Exception:
            logger.exception("Unexpected error in ingest poll loop")
        time.sleep(_INGEST_POLL_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logger.info("DB: %s", DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    seed_users()
    seed_weights()
    _leagues_env = os.getenv("AUTO_INGEST_LEAGUES", "19368,19369")
    _league_ids = [int(x.strip()) for x in _leagues_env.split(",") if x.strip().isdigit()]
    if _league_ids:
        threading.Thread(target=_ingest_poll_loop, args=(_league_ids,), daemon=True).start()
        logger.info("Ingest poll thread started (interval=%ds)", _INGEST_POLL_INTERVAL)
    threading.Thread(target=_week_maintenance_loop, daemon=True).start()
    logger.info("Week maintenance thread started (interval=%ds)", _WEEK_CHECK_INTERVAL)
    threading.Thread(target=_profile_enrichment_loop, daemon=True).start()
    logger.info("Profile enrichment thread started (interval=%ds)", _ENRICHMENT_INTERVAL)
    yield


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
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key,
    same_site="lax",
    https_only=_https_only,
)
# Twitch extension iframes are served from *.ext-twitch.tv — a different origin.
# All /twitch/* endpoints authenticate via JWT (not cookies), so allow_origins="*"
# is safe: cross-origin requests cannot carry session cookies, so regular
# session-protected endpoints are unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
def get_config():
    return {"token_name": TOKEN_NAME, "initial_tokens": INITIAL_TOKENS, "app_version": _APP_VERSION, "app_release": _APP_RELEASE}


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
