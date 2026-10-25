import logging
import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_

import card_points
from weeks import rerun_substitutions_for, scoring_week_for
from database import get_db, SessionLocal
from deps import require_admin, _audit
from enrich import run_enrichment, run_profile_enrichment
from ingest import ingest_league, retry_unparsed_matches, INGEST_LOCK
from models import Match, PlayerMatchStats, Week, Weight
from schedule import get_schedule_for_request, bust_cache, out_of_week_series, SCHEDULE_SHEET_URL
from scoring import fantasy_score, stat_dict_from_row
from toornament import sync_toornament_results
from twitch import bust_panel_cache

router = APIRouter()
logger = logging.getLogger(__name__)


class MatchWeekBody(BaseModel):
    week_id: int | None = None
    apply_to_series: bool = True


def _run_manual_ingest(league_id: int, actor_id: int, actor_username: str):
    """Runs in a background thread — see ingest_league_endpoint below for why."""
    try:
        ingest_league(league_id)
        run_enrichment()
        db = SessionLocal()
        try:
            _audit(db, "admin_ingest", actor_id=actor_id, actor_username=actor_username,
                   detail=f"league_id={league_id}")
            db.commit()
        finally:
            db.close()
        logger.info("Manual ingest complete for league %d", league_id)
    except Exception:
        logger.exception("Manual ingest failed for league %d", league_id)
    finally:
        INGEST_LOCK.release()


@router.post("/ingest/league/{league_id}")
def ingest_league_endpoint(league_id: int, admin: dict = Depends(require_admin)):
    """Starts an ingest cycle in the background and returns immediately.

    A full league ingest can take minutes (OpenDota throttled to ~55 req/min),
    which used to block the admin's HTTP request for that long. INGEST_LOCK is
    shared with the background poll loop (main.py::_ingest_poll_loop) so a
    manual trigger can never run concurrently with the automatic one.
    """
    if not INGEST_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="An ingest is already in progress — try again shortly")
    threading.Thread(
        target=_run_manual_ingest,
        args=(league_id, admin["user_id"], admin["username"]),
        daemon=True,
    ).start()
    return {"status": "started", "league_id": league_id}


def _default_parse_retry_hours() -> int:
    """Read at request time (not import time) so a changed env var is honoured without
    a restart; mirrors main.py's _INGEST_PARSE_RETRY_HOURS."""
    return int(os.getenv("INGEST_PARSE_RETRY_HOURS", "48"))


def _run_parse_retry(max_age_hours: int):
    """Runs in a background thread — see retry_unparsed_endpoint below."""
    try:
        summary = retry_unparsed_matches(max_age_hours)
        logger.info(
            "Parse retry complete (max_age_hours=%d): checked=%d refreshed=%d requested=%d still_unparsed=%d",
            max_age_hours, summary["checked"], summary["refreshed"],
            summary["requested"], summary["still_unparsed"],
        )
    except Exception:
        logger.exception("Parse retry failed (max_age_hours=%d)", max_age_hours)
    finally:
        INGEST_LOCK.release()


@router.post("/ingest/retry-unparsed")
def retry_unparsed_endpoint(
    max_age_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Re-check recently ingested matches that still look unparsed (see
    ingest.retry_unparsed_matches) in a background thread and return immediately.

    `max_age_hours` widens the window for a one-off backfill; without it the
    INGEST_PARSE_RETRY_HOURS default applies. Shares INGEST_LOCK with the poll loop
    and the manual league ingest, so it returns 409 while either is running. The
    audit row is written at trigger time (the run's counts go to the server log).
    """
    window = max_age_hours if max_age_hours is not None else _default_parse_retry_hours()
    if not INGEST_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="An ingest is already in progress — try again shortly")
    try:
        _audit(db, "parse_retry_triggered", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"max_age_hours={window}")
        db.commit()
        threading.Thread(target=_run_parse_retry, args=(window,), daemon=True).start()
    except Exception:
        INGEST_LOCK.release()
        raise
    return {"status": "started", "max_age_hours": window}


@router.post("/recalculate")
def recalculate(db=Depends(get_db), admin: dict = Depends(require_admin)):
    weights = {w.key: w.value for w in db.query(Weight).all()}
    stats = db.query(PlayerMatchStats).all()
    for stat in stats:
        stat.fantasy_points = fantasy_score(stat_dict_from_row(stat), weights)
    bonus_pct = weights.get("mvp_bonus_pct", 10.0)
    for stat in stats:
        if stat.is_mvp:
            stat.fantasy_points = round(stat.fantasy_points * (1 + bonus_pct / 100), 4)
    # Commit the fantasy_points pass first so a card-points rebuild failure (which
    # rolls back its own transaction and keeps the previous rows) does not undo it.
    db.commit()
    try:
        card_point_rows = card_points.rebuild_all(db)
    except Exception:
        _audit(db, "admin_recalculate", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"records={len(stats)} card_points=failed")
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="Stats recalculated, but rebuilding stored card points failed; previous card points kept",
        )
    _audit(db, "admin_recalculate", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"records={len(stats)} card_points={card_point_rows}")
    db.commit()
    return {"status": "ok", "recalculated": len(stats), "card_points": card_point_rows}


@router.get("/schedule")
def schedule_endpoint(db=Depends(get_db)):
    return get_schedule_for_request(db, int(time.time()))


@router.post("/schedule/refresh")
def schedule_refresh(db=Depends(get_db), admin: dict = Depends(require_admin)):
    bust_cache()
    _audit(db, "admin_schedule_refresh", actor_id=admin["user_id"], actor_username=admin["username"])
    db.commit()
    return get_schedule_for_request(db, int(time.time()))


@router.get("/schedule/debug")
def schedule_debug(_: dict = Depends(require_admin)):
    from schedule import SCHEDULE_FIXTURES_URL, parse_fixtures_json

    if SCHEDULE_FIXTURES_URL:
        url = SCHEDULE_FIXTURES_URL
        result = {
            "source": "fixtures_json",
            "url_set": True,
            "url_prefix": url[:60] + "..." if len(url) > 60 else url,
        }
        try:
            import requests as req
            res = req.get(url, timeout=15, allow_redirects=True)
            result["status_code"] = res.status_code
            result["content_type"] = res.headers.get("content-type", "")
            payload = res.json() if res.status_code == 200 else None
        except Exception as e:
            logger.exception("schedule_debug: fixtures fetch failed for %s", url)
            result["error"] = type(e).__name__
            return result
        if not isinstance(payload, dict) or "fixtures" not in payload:
            result["error"] = "response is not a fixtures.json payload"
            return result
        weeks, dropped = parse_fixtures_json(payload)
        result["season"] = payload.get("season")
        result["count"] = payload.get("count")
        result["weeks_parsed"] = len(weeks)
        result["fixtures_dropped"] = dropped
        return result

    url = os.getenv("SCHEDULE_SHEET_URL", SCHEDULE_SHEET_URL)
    result = {"source": "sheet_csv", "url_set": bool(url),
              "url_prefix": url[:60] + "..." if len(url) > 60 else url}

    if not url:
        result["error"] = "SCHEDULE_SHEET_URL is not set"
        return result

    try:
        import requests as req
        res = req.get(url, timeout=15, allow_redirects=True)
        result["status_code"] = res.status_code
        result["content_type"] = res.headers.get("content-type", "")
        result["response_length"] = len(res.text)
        result["first_200_chars"] = res.text[:200]
    except Exception as e:
        logger.exception("schedule_debug: fetch failed for %s", url)
        result["error"] = type(e).__name__

    return result


SERIES_GAP_SECONDS = 6 * 3600


def _series_matches(db, match: Match) -> list[Match]:
    """The match's series: games between the same two teams starting within 6 hours of
    it (issue #193). A match without both team ids is its own series."""
    if not match.radiant_team_id or not match.dire_team_id or match.start_time is None:
        return [match]
    a, b = match.radiant_team_id, match.dire_team_id
    return (
        db.query(Match)
        .filter(or_(and_(Match.radiant_team_id == a, Match.dire_team_id == b),
                    and_(Match.radiant_team_id == b, Match.dire_team_id == a)),
                Match.start_time.between(match.start_time - SERIES_GAP_SECONDS,
                                         match.start_time + SERIES_GAP_SECONDS))
        .order_by(Match.start_time)
        .all()
    )


def _apply_week_override(db, matches, week_id, admin, all_weeks) -> tuple[list[dict], set]:
    """Set week_override_id on each match that doesn't already have it, auditing each
    change. Returns (changes, affected week ids: old and new scoring weeks that differ).
    Caller re-runs substitutions and commits."""
    changes, affected = [], set()
    for m in matches:
        if m.week_override_id == week_id:
            continue
        old_week, _ = scoring_week_for(db, m, all_weeks)
        old_override = m.week_override_id
        m.week_override_id = week_id
        new_week, _ = scoring_week_for(db, m, all_weeks)
        old_id = old_week.id if old_week else None
        new_id = new_week.id if new_week else None
        if old_id != new_id:
            affected |= {old_id, new_id}
        _audit(db, "admin_set_match_week", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"match_id={m.match_id} old_override={old_override} new_override={week_id}")
        changes.append({"match_id": m.match_id, "old_override": old_override, "new_override": week_id,
                        "old_week_id": old_id, "new_week_id": new_id})
    return changes, affected - {None}


def _rerun_affected(db, affected, admin) -> list[dict]:
    db.flush()
    reruns = rerun_substitutions_for(db, affected, "week_override",
                                     actor_id=admin["user_id"], actor_username=admin["username"])
    return [{"week_id": w.id, "week_label": w.label, "substitutions": n} for w, n in reruns]


def _bust_caches():
    bust_cache()
    bust_panel_cache()


@router.put("/matches/{match_id}/week")
def set_match_week(match_id: int, body: MatchWeekBody, db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Override which fantasy week a match counts for (null clears it, back to the week
    containing start_time). With apply_to_series (default) every game of the series
    changes. Weeks whose substitutions already ran are re-run (issue #193)."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if body.week_id is not None:
        week = db.get(Week, body.week_id)
        if not week:
            raise HTTPException(status_code=404, detail="Week not found")
    targets = _series_matches(db, match) if body.apply_to_series else [match]
    all_weeks = db.query(Week).all()
    changes, affected = _apply_week_override(db, targets, body.week_id, admin, all_weeks)
    reruns = _rerun_affected(db, affected, admin)
    db.commit()
    if changes:
        _bust_caches()
    return {
        "match_id": match_id,
        "week_override_id": body.week_id,
        "changed_match_ids": [c["match_id"] for c in changes],
        "substitution_reruns": reruns,
    }


@router.post("/admin/sync-match-weeks")
def sync_match_weeks(dry_run: bool = Query(False), db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Count every out-of-week series (schedule.out_of_week_series: the league week's
    anchor decides the scheduled fantasy week) for its scheduled week, re-running
    affected substitutions. dry_run=true only lists the flagged series."""
    flagged = out_of_week_series(db)
    if dry_run:
        return {"dry_run": True, "series": flagged, "changes": [], "substitution_reruns": [], "errors": []}

    all_weeks = db.query(Week).all()
    changes, affected = [], set()
    for series in flagged:
        matches = db.query(Match).filter(Match.match_id.in_(series["match_ids"])).all()
        series_changes, series_affected = _apply_week_override(
            db, matches, series["scheduled_week_id"], admin, all_weeks)
        teams = f"{series.get('team1')} vs {series.get('team2')}"
        for c in series_changes:
            c.update({"target_week": series["scheduled_week_label"], "teams": teams})
        changes.extend(series_changes)
        affected |= series_affected
    reruns = _rerun_affected(db, affected, admin)
    if changes:
        _audit(db, "admin_sync_match_weeks", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"series={len(flagged)} changes={len(changes)} reruns={len(reruns)}")
    db.commit()
    if changes:
        _bust_caches()
    return {"dry_run": False, "series": flagged, "changes": changes,
            "substitution_reruns": reruns, "errors": []}


@router.post("/admin/sync-toornament")
def admin_sync_toornament(db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Push current series results to toornament.com. Idempotent — safe to call repeatedly."""
    result = sync_toornament_results(db)
    _audit(db, "admin_sync_toornament", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"pushed={result['pushed']} skipped={result['skipped']} errors={len(result['errors'])}")
    db.commit()
    return result


@router.post("/admin/enrich-profiles")
def admin_enrich_profiles(db=Depends(get_db), admin: dict = Depends(require_admin)):
    result = run_profile_enrichment()
    _audit(db, "admin_enrich_profiles", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"enriched={result['enriched']} skipped={result['skipped']} errors={result['errors']} "
                  f"rank_updated={result.get('rank_updated', 0)}")
    db.commit()
    return result
