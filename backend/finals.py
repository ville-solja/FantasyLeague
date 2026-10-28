"""Div 1 finals predictions (issue #237).

Everything here comes from our own data: the Div 1 group standings from ingested
league matches, the bracket (seed 1 vs 4, seed 2 vs 3), the prediction lock and the
series results. The league's fixtures site is only read by the admin cross-check
(`fetch_site_standings`), which fails quietly and changes nothing.

State names: "projected" (group series remain), "waiting_for_tiebreak" (a shared tie
touches seeds 1-4 after the last group series), "set" (predictions open), "locked"
and "decided" (the grand final has a winner).
"""
import copy
import json
import logging
import threading
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import accolades
import schedule
from logo_hosts import safe_logo_url
from models import FinalsBracket, FinalsPrediction, League, LiveMatch, Match, SeasonArchive, Team
from team_insights import team_divisions

logger = logging.getLogger(__name__)

DIVISION = "div1"
SEMIS = ("sf1", "sf2")
SERIES_LABELS = {"sf1": "Semi-final 1", "sf2": "Semi-final 2", "final": "Grand final"}
SLOT_LABELS = ("1st place", "2nd place", "3rd place", "4th place")
SEEDS_IN_BRACKET = 4
WINS_TO_TAKE_SERIES = 2
SITE_TIMEOUT_SECONDS = 4
SITE_MAX_BYTES = 256 * 1024
SITE_CACHE_SECONDS = 300
PUBLIC_CACHE_SECONDS = 30
AVAILABILITY_CACHE_SECONDS = 60
MAX_REVISIONS = 20  # saves per user per bracket; identical re-saves don't count

# Short-lived, process-local caches: GET /finals and GET /config are public and hit on
# every page view, so they don't recompute the standings each time. Writes and admin
# actions always refresh first; admin actions clear these.
_cache_lock = threading.Lock()
_public_cache = {"at": 0.0, "entry": None}
_available_cache = {"at": 0.0, "value": None}
_site_cache = {"at": 0.0, "value": None, "filled": False}


def clear_caches():
    with _cache_lock:
        _public_cache.update(at=0.0, entry=None)
        _available_cache.update(at=0.0, value=None)
        _site_cache.update(at=0.0, value=None, filled=False)

WAITING_TEXT = "Seeding waits for a tiebreak decision"
OPEN_TEXT = "Predictions close when the first semi-final game starts"
PAUSED_TEXT = "Predictions are paused"
LOCKED_TEXT = "Predictions closed"
DECIDED_TEXT = "The finals are decided"


def _pair(a, b) -> tuple:
    return (a, b) if a <= b else (b, a)


def _series_points(wins_a: int, wins_b: int) -> tuple[int, int]:
    """Group series points: win 2, draw (1-1) 1, loss 0."""
    if wins_a > wins_b:
        return 2, 0
    if wins_b > wins_a:
        return 0, 2
    return 1, 1


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

def _div1_league_ids(db) -> set[int]:
    return {lg.id for lg in db.query(League).all() if accolades.league_division(lg.name) == DIVISION}


def _feed_series(db) -> dict[tuple, list[int]]:
    """{team pair: match ids} of the Div 1 group series the Schedule has resolved, read
    from its cached data only (never fetched here)."""
    data = schedule._cache.get("data") or {}
    out: dict[tuple, list[int]] = {}
    for week in data.get("weeks") or []:
        for series in week.get("div1") or []:
            a, b = series.get("team1_id"), series.get("team2_id")
            ids = (series.get("series_result") or {}).get("match_ids") or []
            if a and b and a != b and ids:
                out.setdefault(_pair(a, b), list(ids))
    return out


def _h2h_tiers(group: list[int], results: dict) -> list[list[int]]:
    """Order teams level on points and series wins by a mini-table of the series among
    them. Teams the mini-table can't split stay one tier (shared)."""
    if len(group) < 2:
        return [list(group)]
    pts = {t: 0 for t in group}
    for i, a in enumerate(group):
        for b in group[i + 1:]:
            res = results.get(_pair(a, b))
            if res is None:
                continue
            lo, hi = _pair(a, b)
            p_lo, p_hi = _series_points(*res)
            pts[lo] += p_lo
            pts[hi] += p_hi
    tiers = []
    for level in sorted(set(pts.values()), reverse=True):
        part = [t for t in group if pts[t] == level]
        if len(part) == 1 or len(part) == len(group):
            tiers.append(part)
        else:
            tiers.extend(_h2h_tiers(part, results))
    return tiers


def _rank(teams: list[int], stats: dict, results: dict) -> tuple[list[list[int]], dict]:
    """Tiers in table order (a tier of two or more is a shared rank) and each team's
    tiebreak note: None, "series wins", "head-to-head" or "shared"."""
    tiers, notes = [], {}
    for points in sorted({stats[t]["points"] for t in teams}, reverse=True):
        level = [t for t in teams if stats[t]["points"] == points]
        for wins in sorted({stats[t]["series_wins"] for t in level}, reverse=True):
            sub = [t for t in level if stats[t]["series_wins"] == wins]
            if len(sub) == 1:
                tiers.append(sub)
                notes[sub[0]] = "series wins" if len(level) > 1 else None
                continue
            for tier in _h2h_tiers(sub, results):
                tiers.append(tier)
                for t in tier:
                    notes[t] = "head-to-head" if len(tier) == 1 else "shared"
    return tiers, notes


def _team_info(db, ids, fallback: dict | None = None) -> dict[int, dict]:
    ids = [i for i in set(ids) if i is not None]
    rows = {t.id: t for t in db.query(Team).filter(Team.id.in_(ids)).all()} if ids else {}
    fallback = fallback or {}
    out = {}
    for tid in ids:
        t = rows.get(tid)
        name = (t.name if t and t.name else None) or fallback.get(str(tid)) or f"Team {tid}"
        out[tid] = {"team_id": tid, "name": name, "logo_url": safe_logo_url(t.logo_url) if t else None}
    return out


def standings(db) -> dict:
    """Div 1 group standings from ingested Div 1 league matches between Div 1 teams.

    A pair's group series is the Schedule's resolution of it (cached) or else the pair's
    first two Div 1 league games; it counts once both games have a result. Returns the
    table rows, the tiers, the played and total series counts and the inputs the bracket
    code reuses (the games, the group-series match ids, the league ids)."""
    league_ids = _div1_league_ids(db)
    divisions = team_divisions(db)
    teams = sorted(t for t, d in divisions.items() if d == DIVISION)
    games = []
    if league_ids and teams:
        games = (db.query(Match)
                 .filter(Match.league_id.in_(league_ids),
                         Match.radiant_team_id.in_(teams), Match.dire_team_id.in_(teams))
                 .order_by(Match.start_time, Match.match_id).all())
    by_pair: dict[tuple, list] = {}
    for m in games:
        if m.radiant_team_id != m.dire_team_id:
            by_pair.setdefault(_pair(m.radiant_team_id, m.dire_team_id), []).append(m)
    feed = _feed_series(db)
    stats = {t: {"played": 0, "series_wins": 0, "draws": 0, "losses": 0, "points": 0} for t in teams}
    results: dict[tuple, tuple[int, int]] = {}
    group_ids: set[int] = set()
    group_end_at = None
    for pair, ms in by_pair.items():
        wanted = set(feed.get(pair) or ())
        chosen = [m for m in ms if m.match_id in wanted] or ms
        series = chosen[:2]
        group_ids.update(m.match_id for m in series)
        decided = [m for m in series if m.radiant_win is not None]
        if len(decided) < 2:
            continue
        wins = {pair[0]: 0, pair[1]: 0}
        for m in decided:
            wins[m.radiant_team_id if m.radiant_win else m.dire_team_id] += 1
        results[pair] = (wins[pair[0]], wins[pair[1]])
        last = max((m.start_time or 0) for m in series)
        group_end_at = last if group_end_at is None else max(group_end_at, last)
        p0, p1 = _series_points(*results[pair])
        for team, pts in ((pair[0], p0), (pair[1], p1)):
            s = stats[team]
            s["played"] += 1
            s["points"] += pts
            s["series_wins"] += pts == 2
            s["draws"] += pts == 1
            s["losses"] += pts == 0
    tiers, notes = _rank(teams, stats, results)
    info = _team_info(db, teams)
    rows, pos = [], 0
    for tier in tiers:
        for t in sorted(tier, key=lambda x: info[x]["name"].lower()):
            rows.append({**info[t], **stats[t], "rank": pos + 1, "shared": len(tier) > 1,
                         "note": notes.get(t)})
        pos += len(tier)
    total = len(teams) * (len(teams) - 1) // 2
    return {"rows": rows, "tiers": tiers, "stats": stats, "teams": teams, "info": info,
            "played": len(results), "total": total, "results": results, "games": games,
            "group_ids": group_ids, "group_end_at": group_end_at, "league_ids": league_ids}


def _complete(st) -> bool:
    return st["total"] > 0 and st["played"] == st["total"] and len(st["teams"]) >= SEEDS_IN_BRACKET


def holding_tiers(st) -> list[list[int]]:
    """Shared tiers that touch seeds 1-4 (inside the top four or across the 4th/5th cut)."""
    out, pos = [], 0
    for tier in st["tiers"]:
        if len(tier) > 1 and pos < SEEDS_IN_BRACKET:
            out.append(tier)
        pos += len(tier)
    return out


def _flat_order(st, order: list[int] | None = None) -> list[int]:
    """Table order; with `order`, the teams of each holding tier follow it."""
    held = {t for tier in holding_tiers(st) for t in tier}
    out = []
    for tier in st["tiers"]:
        if order and held.intersection(tier):
            out.extend(sorted(tier, key=order.index))
        else:
            out.extend(sorted(tier, key=lambda t: st["info"][t]["name"].lower()))
    return out


# ---------------------------------------------------------------------------
# Bracket, lock and results
# ---------------------------------------------------------------------------

def current_bracket(db, label: str):
    return db.query(FinalsBracket).filter_by(season_label=label, division=DIVISION).first()


def series_teams(b) -> dict[str, tuple | None]:
    final = (b.sf1_winner, b.sf2_winner) if b.sf1_winner and b.sf2_winner else None
    return {"sf1": (b.seed1_team_id, b.seed4_team_id), "sf2": (b.seed2_team_id, b.seed3_team_id),
            "final": final}


def _sources(b) -> dict:
    try:
        return json.loads(b.result_sources_json or "{}")
    except ValueError:
        return {}


def _store_bracket(db, label, st, seeds, source, now):
    b = FinalsBracket(
        season_label=label, division=DIVISION,
        seed1_team_id=seeds[0], seed2_team_id=seeds[1], seed3_team_id=seeds[2], seed4_team_id=seeds[3],
        seed_names_json=json.dumps({str(t): st["info"][t]["name"] for t in seeds}),
        set_at=now, group_end_at=st["group_end_at"] or 0, seed_source=source,
        paused=False, result_sources_json="{}",
    )
    try:
        with db.begin_nested():
            db.add(b)
    except IntegrityError:
        b = current_bracket(db, label)
    return b


def _playoff_games(st, b, a, c) -> list:
    """Div 1 league games between a and c after the group stage, oldest first."""
    pair = _pair(a, c)
    return [m for m in st["games"]
            if _pair(m.radiant_team_id, m.dire_team_id) == pair
            and m.match_id not in st["group_ids"] and (m.start_time or 0) > b.group_end_at]


def _series_score(games, a, c):
    """(winner or None, {a: wins, c: wins}): the first team to two game wins."""
    wins = {a: 0, c: 0}
    for m in games:
        if m.radiant_win is None:
            continue
        w = m.radiant_team_id if m.radiant_win else m.dire_team_id
        wins[w] += 1
        if wins[w] >= WINS_TO_TAKE_SERIES:
            return w, wins
    return None, wins


def _feed_semi_start_times(db, b) -> list[int]:
    """Start times the fixtures feed (cached Schedule data) gives a semi pairing, if any."""
    pairs = {_pair(b.seed1_team_id, b.seed4_team_id), _pair(b.seed2_team_id, b.seed3_team_id)}
    out = []
    for week in (schedule._cache.get("data") or {}).get("weeks") or []:
        for s in week.get("div1") or []:
            a, c = s.get("team1_id"), s.get("team2_id")
            if not (a and c and s.get("scheduled") and s.get("datetime_iso")) or _pair(a, c) not in pairs:
                continue
            try:
                dt = datetime.fromisoformat(s["datetime_iso"]).replace(tzinfo=schedule.LEAGUE_TZ)
                out.append(int(dt.timestamp()))
            except (TypeError, ValueError):
                continue
    return out


def _update_lock(db, b, st, now):
    """Move locked_at to the earliest known start of a semi: a live sighting, an
    ingested game or a feed start time that has passed. It only ever moves earlier."""
    pairs = {_pair(b.seed1_team_id, b.seed4_team_id), _pair(b.seed2_team_id, b.seed3_team_id)}
    candidates = []
    if st["league_ids"]:
        live = (db.query(LiveMatch)
                .filter(LiveMatch.league_id.in_(st["league_ids"]),
                        LiveMatch.radiant_team_id.isnot(None), LiveMatch.dire_team_id.isnot(None),
                        LiveMatch.first_seen_at > b.group_end_at).all())
        seen = [r.first_seen_at for r in live
                if _pair(r.radiant_team_id, r.dire_team_id) in pairs and r.first_seen_at]
        if seen:
            candidates.append(("live", min(seen)))
    ingested = [m.start_time for m in st["games"]
                if _pair(m.radiant_team_id, m.dire_team_id) in pairs and m.match_id not in st["group_ids"]
                and m.start_time and m.start_time > b.group_end_at]
    if ingested:
        candidates.append(("ingested", min(ingested)))
    feed = [t for t in _feed_semi_start_times(db, b) if b.group_end_at < t <= now]
    if feed:
        candidates.append(("feed_time", min(feed)))
    for source, t in candidates:
        if b.locked_at is None or t < b.locked_at:
            b.locked_at, b.lock_source = t, source


def _update_results(b, st):
    sources = _sources(b)
    for key in SEMIS:
        if sources.get(key) == "admin":
            continue
        a, c = series_teams(b)[key]
        winner, _ = _series_score(_playoff_games(st, b, a, c), a, c)
        setattr(b, f"{key}_winner", winner)
        if winner:
            sources[key] = "matches"
        else:
            sources.pop(key, None)
    teams = series_teams(b)["final"]
    if teams and sources.get("final") == "admin" and b.final_winner not in teams:
        sources.pop("final", None)
    if not teams:
        b.final_winner = None
        sources.pop("final", None)
    elif sources.get("final") != "admin":
        winner, _ = _series_score(_playoff_games(st, b, *teams), *teams)
        b.final_winner = winner
        if winner:
            sources["final"] = "matches"
        else:
            sources.pop("final", None)
    b.result_sources_json = json.dumps(sources, sort_keys=True)


def effective_predictions(db, b) -> dict[int, FinalsPrediction]:
    """{user_id: row}: each user's latest save before the lock (the latest while open)."""
    q = db.query(FinalsPrediction).filter(FinalsPrediction.bracket_id == b.id)
    if b.locked_at is not None:
        q = q.filter(FinalsPrediction.saved_at < b.locked_at)
    out = {}
    for row in q.order_by(FinalsPrediction.saved_at, FinalsPrediction.id).all():
        out[row.user_id] = row
    return out


def _correct_count(b, row) -> int:
    return ((row.sf1_pick == b.sf1_winner) + (row.sf2_pick == b.sf2_winner)
            + (row.final_pick == b.final_winner))


def _update_correct_picks(db, b):
    """correct_picks on each effective row once the final is decided; None elsewhere."""
    effective = {r.id for r in effective_predictions(db, b).values()} if b.final_winner else set()
    for row in db.query(FinalsPrediction).filter(FinalsPrediction.bracket_id == b.id).all():
        value = _correct_count(b, row) if row.id in effective else None
        if row.correct_picks != value:
            row.correct_picks = value


def _state(b, st) -> str:
    if b is None:
        return "waiting_for_tiebreak" if _complete(st) and holding_tiers(st) else "projected"
    if b.final_winner:
        return "decided"
    if b.locked_at is not None:
        return "locked"
    return "set"


def refresh(db, now: int | None = None) -> dict:
    """Bring the current season's bracket up to date: store it once the group stage is
    complete and seeds 1-4 are clear, then the lock, the results and correct_picks.
    Flushes; the caller commits."""
    now = int(time.time()) if now is None else now
    label = accolades.current_season_label(db)
    st = standings(db)
    b = current_bracket(db, label)
    if b is None and _complete(st) and not holding_tiers(st):
        b = _store_bracket(db, label, st, _flat_order(st)[:SEEDS_IN_BRACKET], "standings", now)
    if b is not None:
        before = (b.locked_at, b.sf1_winner, b.sf2_winner, b.final_winner)
        _update_lock(db, b, st, now)
        _update_results(b, st)
        if (b.locked_at, b.sf1_winner, b.sf2_winner, b.final_winner) != before:
            _update_correct_picks(db, b)
        db.flush()
    return {"label": label, "standings": st, "bracket": b, "state": _state(b, st), "now": now}


def bracket_state(db) -> str:
    """The current state after a refresh (see refresh)."""
    return refresh(db)["state"]


def is_available(db) -> bool:
    """GET /config finals_available: the tab shows once every Div 1 team has played a
    group series (or a bracket exists), until the season is archived. Cached for
    AVAILABILITY_CACHE_SECONDS."""
    with _cache_lock:
        if _available_cache["value"] is not None and time.monotonic() - _available_cache["at"] < AVAILABILITY_CACHE_SECONDS:
            return _available_cache["value"]
    value = _compute_available(db)
    with _cache_lock:
        _available_cache.update(at=time.monotonic(), value=value)
    return value


def _compute_available(db) -> bool:
    try:
        label = accolades.current_season_label(db)
        if db.query(SeasonArchive).filter(SeasonArchive.season_label == label).first():
            return False
        if current_bracket(db, label) is not None:
            return True
        st = standings(db)
        return len(st["teams"]) >= SEEDS_IN_BRACKET and all(
            st["stats"][t]["played"] >= 1 for t in st["teams"])
    except Exception:
        logger.exception("Finals availability check failed")
        return False


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _live_pairs(db, league_ids, now) -> set[tuple]:
    if not league_ids:
        return set()
    rows = (db.query(LiveMatch)
            .filter(LiveMatch.league_id.in_(league_ids), LiveMatch.ended_at.is_(None),
                    LiveMatch.last_seen_at >= now - schedule.LIVE_FRESH_SECONDS,
                    LiveMatch.radiant_team_id.isnot(None), LiveMatch.dire_team_id.isnot(None)).all())
    return {_pair(r.radiant_team_id, r.dire_team_id) for r in rows}


def _projected_slot(st, position) -> dict:
    pos = 0
    for tier in st["tiers"]:
        if pos <= position < pos + len(tier):
            names = sorted(st["info"][t]["name"] for t in tier)
            if len(tier) == 1:
                return {"slot": SLOT_LABELS[position], "team_id": None, "now": names[0], "tie": False, "tied": []}
            return {"slot": SLOT_LABELS[position], "team_id": None, "now": None, "tie": True, "tied": names}
        pos += len(tier)
    return {"slot": SLOT_LABELS[position], "team_id": None, "now": None, "tie": False, "tied": []}


def _tree(db, ctx) -> list[dict]:
    st, b, now = ctx["standings"], ctx["bracket"], ctx["now"]
    if b is None:
        slots = [_projected_slot(st, i) for i in range(SEEDS_IN_BRACKET)]
        winner_slots = [{"slot": f"Winner of {SERIES_LABELS[k].lower()}", "team_id": None} for k in SEMIS]
        return [
            {"key": "sf1", "label": SERIES_LABELS["sf1"], "teams": [slots[0], slots[3]], "score": None, "live": False, "winner": None},
            {"key": "sf2", "label": SERIES_LABELS["sf2"], "teams": [slots[1], slots[2]], "score": None, "live": False, "winner": None},
            {"key": "final", "label": SERIES_LABELS["final"], "teams": winner_slots, "score": None, "live": False, "winner": None},
        ]
    names = json.loads(b.seed_names_json or "{}")
    seeds = [b.seed1_team_id, b.seed2_team_id, b.seed3_team_id, b.seed4_team_id]
    info = _team_info(db, seeds, names)
    live = _live_pairs(db, st["league_ids"], now)
    out = []
    for key, teams in series_teams(b).items():
        if teams is None:
            entries = [{"slot": f"Winner of {SERIES_LABELS[k].lower()}", "team_id": None} for k in SEMIS]
            out.append({"key": key, "label": SERIES_LABELS[key], "teams": entries, "score": None,
                        "live": False, "winner": None})
            continue
        entries = [{**info[t], "slot": SLOT_LABELS[seeds.index(t)], "seed": seeds.index(t) + 1} for t in teams]
        games = _playoff_games(st, b, *teams)
        _, wins = _series_score(games, *teams)
        out.append({"key": key, "label": SERIES_LABELS[key], "teams": entries,
                    "score": [wins[teams[0]], wins[teams[1]]] if games else None,
                    "live": _pair(*teams) in live, "winner": getattr(b, f"{key}_winner")})
    return out


def _notice(ctx) -> str:
    st, b, state = ctx["standings"], ctx["bracket"], ctx["state"]
    if state == "projected":
        return f"{st['played']}/{st['total']} group series played"
    if state == "waiting_for_tiebreak":
        return WAITING_TEXT
    if state == "set":
        return PAUSED_TEXT if b.paused else OPEN_TEXT
    return LOCKED_TEXT if state == "locked" else DECIDED_TEXT


def _shares(b, effective: dict) -> dict:
    """{series: {"count": n, "shares": [{team_id, pct}]}} from effective predictions."""
    out = {}
    for key in ("sf1", "sf2", "final"):
        counts: dict[int, int] = {}
        for row in effective.values():
            pick = getattr(row, f"{key}_pick")
            counts[pick] = counts.get(pick, 0) + 1
        n = sum(counts.values())
        out[key] = {"count": n, "shares": [{"team_id": t, "pct": round(100 * c / n)}
                                          for t, c in sorted(counts.items(), key=lambda kv: -kv[1])]}
    return out


def _own(b, row) -> dict | None:
    if row is None:
        return None
    marks = {}
    for key in ("sf1", "sf2", "final"):
        winner = getattr(b, f"{key}_winner")
        marks[key] = None if winner is None else getattr(row, f"{key}_pick") == winner
    return {"sf1_pick": row.sf1_pick, "sf2_pick": row.sf2_pick, "final_pick": row.final_pick,
            "saved_at": row.saved_at, "marks": marks}


def public_view(db, user_id: int | None, ctx: dict | None = None) -> dict:
    """GET /finals. Other users' picks never appear; after the lock only the share of
    picks per team and the prediction count per series."""
    ctx = ctx or refresh(db)
    st, b, state = ctx["standings"], ctx["bracket"], ctx["state"]
    opened = state == "set" and not b.paused
    out = {
        "state": state, "season_label": ctx["label"], "division": DIVISION,
        "played": st["played"], "total": st["total"], "notice": _notice(ctx),
        "tree": _tree(db, ctx), "logged_in": user_id is not None,
        "open": opened, "can_predict": opened and user_id is not None,
        "paused": bool(b.paused) if b else False,
        "locked_at": b.locked_at if b else None,
        "prediction": None, "results": None, "summary": None,
    }
    if b is None:
        return out
    effective = effective_predictions(db, b)
    if user_id is not None:
        out["prediction"] = _own(b, effective.get(user_id))
    if state in ("locked", "decided"):
        out["results"] = _shares(b, effective)
    if state == "decided":
        own = effective.get(user_id) if user_id is not None else None
        out["summary"] = {
            "correct": _correct_count(b, own) if own else None, "of": 3,
            "perfect_count": sum(1 for r in effective.values() if _correct_count(b, r) == 3),
            "prediction_count": len(effective),
        }
    return out


def _latest_row(db, b, user_id, before_lock=True):
    q = db.query(FinalsPrediction).filter(FinalsPrediction.bracket_id == b.id,
                                          FinalsPrediction.user_id == user_id)
    if before_lock and b.locked_at is not None:
        q = q.filter(FinalsPrediction.saved_at < b.locked_at)
    return q.order_by(FinalsPrediction.saved_at.desc(), FinalsPrediction.id.desc()).first()


def cached_public_view(db, user_id: int | None) -> dict:
    """GET /finals: the shared part (tree, state, shares) from a refresh at most
    PUBLIC_CACHE_SECONDS old, plus the caller's own prediction read fresh. A lock learned
    meanwhile still applies: saves always refresh first, and the prediction that counts
    is the last one saved before the lock."""
    with _cache_lock:
        entry = _public_cache["entry"]
        if entry is not None and time.monotonic() - _public_cache["at"] >= PUBLIC_CACHE_SECONDS:
            entry = None
    if entry is None:
        ctx = refresh(db)
        db.commit()
        entry = {"view": public_view(db, None, ctx),
                 "bracket_id": ctx["bracket"].id if ctx["bracket"] is not None else None}
        with _cache_lock:
            _public_cache.update(at=time.monotonic(), entry=entry)
    view = copy.deepcopy(entry["view"])
    if user_id is None:
        return view
    view["logged_in"] = True
    view["can_predict"] = bool(view["open"])
    b = db.get(FinalsBracket, entry["bracket_id"]) if entry["bracket_id"] else None
    if b is not None:
        row = _latest_row(db, b, user_id)
        view["prediction"] = _own(b, row)
        if view["summary"] is not None:
            view["summary"]["correct"] = _correct_count(b, row) if row else None
    return view


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def save_prediction(db, user_id: int, sf1_pick: int, sf2_pick: int, final_pick: int,
                    now: int | None = None) -> dict:
    """Append a prediction revision. 409 unless predictions are open; 422 for picks
    outside the bracket."""
    ctx = refresh(db, now)
    b, state = ctx["bracket"], ctx["state"]
    if b is None:
        raise HTTPException(status_code=409, detail="Predictions are not open yet")
    if state != "set":
        raise HTTPException(status_code=409, detail="Predictions are closed")
    if b.paused:
        raise HTTPException(status_code=409, detail="Predictions are paused")
    teams = series_teams(b)
    if sf1_pick not in teams["sf1"]:
        raise HTTPException(status_code=422, detail="Semi-final 1 pick must be one of its two teams")
    if sf2_pick not in teams["sf2"]:
        raise HTTPException(status_code=422, detail="Semi-final 2 pick must be one of its two teams")
    if final_pick not in (sf1_pick, sf2_pick):
        raise HTTPException(status_code=422, detail="The grand final pick must be one of your semi-final picks")
    latest = _latest_row(db, b, user_id)
    if latest is not None and (latest.sf1_pick, latest.sf2_pick, latest.final_pick) == (sf1_pick, sf2_pick, final_pick):
        return _own(b, latest)
    saves = (db.query(FinalsPrediction)
             .filter(FinalsPrediction.bracket_id == b.id, FinalsPrediction.user_id == user_id).count())
    if saves >= MAX_REVISIONS:
        raise HTTPException(status_code=429,
                            detail="You have changed your predictions too often; your last save counts")
    row = FinalsPrediction(bracket_id=b.id, user_id=user_id, sf1_pick=sf1_pick, sf2_pick=sf2_pick,
                           final_pick=final_pick, saved_at=ctx["now"])
    db.add(row)
    db.flush()
    return _own(b, row)


def _require_bracket(ctx):
    if ctx["bracket"] is None:
        raise HTTPException(status_code=409, detail="The bracket is not set yet")
    return ctx["bracket"]


def resolve_tiebreak(db, order: list[int], now: int | None = None):
    """Store the bracket with the admin's order of the tied teams (all of them, once)."""
    ctx = refresh(db, now)
    if ctx["state"] != "waiting_for_tiebreak":
        raise HTTPException(status_code=409, detail="No tie is waiting for a decision")
    st = ctx["standings"]
    tied = {t for tier in holding_tiers(st) for t in tier}
    if len(order) != len(set(order)) or set(order) != tied:
        raise HTTPException(status_code=422, detail="Order exactly the tied teams")
    seeds = _flat_order(st, order)[:SEEDS_IN_BRACKET]
    b = _store_bracket(db, ctx["label"], st, seeds, "admin_tiebreak", ctx["now"])
    clear_caches()
    return refresh(db, ctx["now"])["bracket"] or b


def toggle_pause(db) -> FinalsBracket:
    b = _require_bracket(refresh(db))
    b.paused = not b.paused
    db.flush()
    clear_caches()
    return b


def close_now(db, now: int | None = None) -> FinalsBracket:
    """Lock now, unless a lock is already earlier."""
    ctx = refresh(db, now)
    b = _require_bracket(ctx)
    if b.locked_at is None or ctx["now"] < b.locked_at:
        b.locked_at, b.lock_source = ctx["now"], "admin"
        _update_correct_picks(db, b)
    refresh(db, ctx["now"])
    clear_caches()
    return b


def set_result(db, series: str, winner: int) -> FinalsBracket:
    """An admin result for one series; it wins over the matches. A result while
    predictions are still open also locks them now (lock_source "admin"), so nobody can
    save after a result is known."""
    ctx = refresh(db)
    b = _require_bracket(ctx)
    teams = series_teams(b).get(series)
    if teams is None:
        raise HTTPException(status_code=409, detail="Both semi-final winners are needed first")
    if winner not in teams:
        raise HTTPException(status_code=422, detail="The winner must be one of the series' two teams")
    if b.locked_at is None:
        b.locked_at, b.lock_source = ctx["now"], "admin"
    setattr(b, f"{series}_winner", winner)
    sources = _sources(b)
    sources[series] = "admin"
    b.result_sources_json = json.dumps(sources, sort_keys=True)
    _update_correct_picks(db, b)
    refresh(db, ctx["now"])
    clear_caches()
    return b


# ---------------------------------------------------------------------------
# Admin view and the optional fixtures-site cross-check
# ---------------------------------------------------------------------------

def _parse_site_standings(payload) -> list[dict] | None:
    """[{name, position, shared}] for the upper division, read leniently."""
    rows = payload
    if isinstance(rows, dict):
        for key in ("upper", "div1", "standings", "data"):
            if key in rows:
                rows = rows[key]
                break
        if isinstance(rows, dict):
            rows = rows.get("upper") or rows.get("div1") or []
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        division = str(r.get("division") or "").strip().lower()
        if division and division not in ("upper", "div1", "div 1"):
            continue
        team = r.get("team") or r.get("name") or r.get("team_name")
        if isinstance(team, dict):
            team = team.get("name")
        if not team:
            continue
        try:
            position = int(r.get("position") or r.get("rank") or r.get("pos") or len(out) + 1)
        except (TypeError, ValueError):
            position = len(out) + 1
        out.append({"name": str(team), "position": position, "shared": bool(r.get("shared"))})
    return out or None


def fetch_site_standings() -> list[dict] | None:
    """The fixtures site's standings (next to SCHEDULE_FIXTURES_URL, at `standings`), or
    None when unset, unreachable or unreadable. Cached for SITE_CACHE_SECONDS."""
    with _cache_lock:
        if _site_cache["filled"] and time.monotonic() - _site_cache["at"] < SITE_CACHE_SECONDS:
            return _site_cache["value"]
    value = _fetch_site_standings()
    with _cache_lock:
        _site_cache.update(at=time.monotonic(), value=value, filled=True)
    return value


def _fetch_site_standings() -> list[dict] | None:
    """Short timeout, no redirects, at most SITE_MAX_BYTES read; never raises."""
    base = schedule.SCHEDULE_FIXTURES_URL
    if not base:
        return None
    res = None
    try:
        res = requests.get(urljoin(base, "standings"), timeout=SITE_TIMEOUT_SECONDS,
                           allow_redirects=False, stream=True)
        if res.status_code != 200:
            return None
        body = b""
        for chunk in res.iter_content(chunk_size=16384):
            body += chunk
            if len(body) > SITE_MAX_BYTES:
                logger.info("Finals cross-check: fixtures site standings too large; ignored")
                return None
        return _parse_site_standings(json.loads(body))
    except Exception as e:
        logger.info("Finals cross-check: fixtures site standings unavailable (%s)", type(e).__name__)
        return None
    finally:
        if res is not None:
            try:
                res.close()
            except Exception:
                pass


def _site_order(db, site) -> list[int] | None:
    """Our team ids in the site's order (unknown names dropped)."""
    if not site:
        return None
    lookup = schedule.build_team_lookup(db)
    ids = []
    for r in sorted(site, key=lambda x: x["position"]):
        tid = schedule.find_team_id(r["name"], lookup)
        if tid is not None and tid not in ids:
            ids.append(tid)
    return ids


def admin_view(db) -> dict:
    """GET /admin/finals: standings with tiebreak notes, state, lock and result sources,
    the tied teams with the fixtures site's order as a hint, and the cross-check."""
    ctx = refresh(db)
    st, b, state = ctx["standings"], ctx["bracket"], ctx["state"]
    site = fetch_site_standings()
    site_ids = _site_order(db, site)
    tied = [t for tier in holding_tiers(st) for t in tier] if state == "waiting_for_tiebreak" else []
    suggestion = None
    if tied and site:
        positions = {}
        lookup = schedule.build_team_lookup(db)
        for r in site:
            tid = schedule.find_team_id(r["name"], lookup)
            if tid in tied and not r["shared"]:
                positions[tid] = r["position"]
        if set(positions) == set(tied) and len(set(positions.values())) == len(tied):
            suggestion = sorted(tied, key=positions.get)
    ours = ([b.seed1_team_id, b.seed2_team_id, b.seed3_team_id, b.seed4_team_id] if b
            else _flat_order(st)[:SEEDS_IN_BRACKET])
    differs = False
    if site_ids and len(site_ids) >= SEEDS_IN_BRACKET and len(ours) == SEEDS_IN_BRACKET:
        top = site_ids[:SEEDS_IN_BRACKET]
        differs = top != ours if b else set(top) != set(ours)
    out = {
        "state": state, "season_label": ctx["label"], "played": st["played"], "total": st["total"],
        "standings": st["rows"],
        "tied": [st["info"][t] for t in tied], "suggestion": suggestion,
        "cross_check": {"reachable": site is not None, "differs": differs,
                        "site_top4": [st["info"].get(t, {"team_id": t, "name": f"Team {t}"})["name"]
                                      for t in (site_ids or [])[:SEEDS_IN_BRACKET]]},
        "bracket": None,
    }
    if b is not None:
        sources = _sources(b)
        tree = _tree(db, ctx)
        out["bracket"] = {
            "set_at": b.set_at, "seed_source": b.seed_source, "locked_at": b.locked_at,
            "lock_source": b.lock_source, "paused": bool(b.paused),
            "prediction_count": len(effective_predictions(db, b)),
            "series": [{**s, "source": sources.get(s["key"])} for s in tree],
        }
    return out
