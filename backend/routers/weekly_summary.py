import os
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam, text

from card_points import _modifiers
from card_utils import _load_weights, _mvp_bonus_delta, card_points_breakdown
from database import get_db
from deps import get_current_user
from dotabuff_league_logos import resolve_local_team_logo_path
from image import _ASSETS_DIR
from match_scoring import counted_roster_entry_sql, scored_match_sql
from routers.cards import _build_roster_response
from scoring import STAT_LABELS, display_points, stat_dict_from_row
from weeks import substitution_delay_hours
from models import (
    Card, Player, PlayerMatchStats, Team, Week, WeeklyRosterEntry,
    WeeklySummary, WeeklySummaryReveal, WeeklySummarySeen,
)

router = APIRouter()

_SERIES_GAP = 6 * 3600  # seconds — matches the clustering window backend/schedule.py uses
_LOGO_DIR = os.path.join(_ASSETS_DIR, "dotabuff_league_logos")


def _group_into_series(matches: list[dict]) -> list[dict]:
    """Cluster same-two-team matches (already sorted by start_time) into series:
    consecutive matches between the same unordered team pair belong together as
    long as the gap to the previous match in that pair is <= _SERIES_GAP.
    Scoped-down version of the same pair/gap rule backend/schedule.py uses for
    the season-wide schedule view, applied here to a single week's matches."""
    open_clusters = {}
    clusters = []
    for m in matches:
        if m["radiant_team_id"] and m["dire_team_id"]:
            pair = tuple(sorted((m["radiant_team_id"], m["dire_team_id"])))
        else:
            pair = ("unknown", m["match_id"])  # standalone series of one
        current = open_clusters.get(pair)
        if current is not None and (m["start_time"] - current[-1]["start_time"]) <= _SERIES_GAP:
            current.append(m)
        else:
            if current is not None:
                clusters.append(current)
            open_clusters[pair] = [m]
    clusters.extend(open_clusters.values())
    return [{"matches": cluster} for cluster in clusters]


def _team_logo_url(team) -> str | None:
    """Prefer the locally-scraped Dotabuff PNG already used for card image generation
    (served under /assets/) — Team.logo_url is an OpenDota HTTP field that's rarely
    populated for lower-tier leagues, so reading it alone left most teams with no
    logo at all in the Weekly Report despite having a working one elsewhere in the
    app (see backend/image.py::_load_team_logo_for_card, the same preference order)."""
    if team and team.name:
        local_path = resolve_local_team_logo_path(_LOGO_DIR, team.name)
        if local_path:
            return f"/assets/dotabuff_league_logos/{os.path.basename(local_path)}"
    return team.logo_url if team else None


def _team_dict(team):
    if not team:
        return None
    return {"id": team.id, "name": team.name, "logo_url": _team_logo_url(team)}


_IDENTITY_KEYS = ("card_id", "card_type", "player_id", "player_name", "avatar_url",
                  "team_id", "team_name")


def _roster_card(c: dict) -> dict:
    return {
        "card_id": c["id"], "card_type": c["card_type"],
        "player_id": c["player_id"], "player_name": c["player_name"],
        "avatar_url": c["avatar_url"], "team_id": c["team_id"], "team_name": c["team_name"],
        "counted": bool(c["is_active"]), "subbed_in": c["subbed_in"],
        "subbed_out": c["subbed_out"], "subbed_in_for": c["subbed_in_for"],
        "modifiers": c["modifiers"], "week_points": c["total_points"],
    }


def _card_games(db, week: Week, cards: list[dict], game_numbers: dict) -> dict:
    """card_id -> one row per game the card's player played in the week window.
    Points are the stored card_match_points row (issue #141); an excluded match
    has points None and scored False."""
    if not cards:
        return {}
    rows = db.execute(text("""
        SELECT c.id as card_id, m.match_id, m.start_time, m.radiant_team_id, m.dire_team_id,
               m.radiant_win, COALESCE(m.excluded_from_scoring, 0) as excluded,
               s.team_id, COALESCE(s.is_mvp, 0) as is_mvp, cmp.points
        FROM cards c
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = :week_id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        LEFT JOIN card_match_points cmp ON cmp.card_id = c.id AND cmp.match_id = m.match_id
        WHERE c.id IN :card_ids
        ORDER BY m.start_time ASC, m.match_id ASC
    """).bindparams(bindparam("card_ids", expanding=True)),
        {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
         "card_ids": [c["card_id"] for c in cards]}).fetchall()
    team_ids = {r.radiant_team_id for r in rows if r.radiant_team_id} | \
               {r.dire_team_id for r in rows if r.dire_team_id}
    team_names = {
        t.id: t.name for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    } if team_ids else {}
    games = {}
    for r in rows:
        opponent_id = won = None
        if r.team_id is not None and r.team_id == r.radiant_team_id:
            opponent_id = r.dire_team_id
            won = None if r.radiant_win is None else bool(r.radiant_win)
        elif r.team_id is not None and r.team_id == r.dire_team_id:
            opponent_id = r.radiant_team_id
            won = None if r.radiant_win is None else not bool(r.radiant_win)
        scored = not r.excluded
        games.setdefault(r.card_id, []).append({
            "match_id": r.match_id,
            "start_time": r.start_time,
            "game_number": game_numbers.get(r.match_id, 1),
            "opponent_team_id": opponent_id,
            "opponent_name": team_names.get(opponent_id),
            "won": won,
            "is_mvp": bool(r.is_mvp),
            "points": display_points(r.points or 0.0) if scored else None,
            "scored": scored,
        })
    return games


def _card_breakdowns(db, week: Week, cards: list[dict]) -> dict:
    """card_id -> {"raw", "steps"} (issue #152): what made up each counted card's week
    points, recomputed from the same inputs as the stored card_match_points rows over
    the card's counted, scored games in the week window.

    Steps: rarity (when its bonus is above 0), one per modifier in the card's modifier
    order, then one MVP step per MVP game in game order. raw and each step are rounded
    with display_points; the rounding remainder goes to the last step (or to raw), so
    the rounded parts add up to the card's week_points."""
    if not cards:
        return {}
    rows = db.execute(text(f"""
        SELECT c.id as card_id, s.*
        FROM cards c
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id AND {scored_match_sql()}
            AND (m.week_override_id = :week_id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        WHERE c.id IN :card_ids
        ORDER BY m.start_time ASC, m.match_id ASC
    """).bindparams(bindparam("card_ids", expanding=True)),
        {"week_id": week.id, "ws": week.start_time, "we": week.end_time,
         "card_ids": [c["card_id"] for c in cards]}).fetchall()
    weights, rarity = _load_weights(db)
    mods_map = _modifiers(db, [c["card_id"] for c in cards])
    mvp_pct = weights.get("mvp_bonus_pct", 10.0)
    card_types = {c["card_id"]: c["card_type"] for c in cards}
    sums = {}
    for r in rows:
        card_type = card_types[r.card_id]
        is_mvp = bool(r._mapping.get("is_mvp"))
        parts = card_points_breakdown(
            stat_dict_from_row(r), card_type, weights, rarity, mods_map.get(r.card_id, {}),
            _mvp_bonus_delta(r, weights) if is_mvp else 0.0)
        acc = sums.setdefault(r.card_id, {"raw": 0.0, "rarity": 0.0, "modifiers": {}, "mvp": {},
                                          "rarity_pct": parts["rarity_pct"]})
        acc["raw"] += parts["raw"]
        acc["rarity"] += parts["rarity"]
        for stat, v in parts["modifiers"].items():
            acc["modifiers"][stat] = acc["modifiers"].get(stat, 0.0) + v
        if parts["mvp"]:
            acc["mvp"][r.match_id] = acc["mvp"].get(r.match_id, 0.0) + parts["mvp"]

    result = {}
    for c in cards:
        acc = sums.get(c["card_id"]) or {"raw": 0.0, "rarity": 0.0, "modifiers": {}, "mvp": {},
                                          "rarity_pct": rarity.get(f"mod_{c['card_type']}", 0) * 100}
        exact_steps = []
        if acc["rarity_pct"] > 0:
            exact_steps.append(({"kind": "rarity", "label": str(c["card_type"]).capitalize(),
                                 "pct": display_points(acc["rarity_pct"], 2)}, acc["rarity"]))
        for m in c["modifiers"]:
            stat = m["stat"]
            exact_steps.append(({"kind": "modifier", "stat": stat,
                                 "label": STAT_LABELS.get(stat, stat.replace("_", " ").title()),
                                 "pct": m["bonus_pct"]}, acc["modifiers"].get(stat, 0.0)))
        for match_id, value in acc["mvp"].items():
            exact_steps.append(({"kind": "mvp", "label": "MVP", "pct": mvp_pct,
                                 "match_id": match_id}, value))
        raw = display_points(acc["raw"])
        steps = [{**meta, "points": display_points(value)} for meta, value in exact_steps]
        remainder = c["week_points"] - (raw + sum(st["points"] for st in steps))
        if steps:
            steps[-1]["points"] = display_points(steps[-1]["points"] + remainder)
        else:
            raw = display_points(raw + remainder)
        result[c["card_id"]] = {"raw": raw, "steps": steps}
    return result


def _build_roster_block(db, week: Week, revealed: bool, user_id: int,
                        game_numbers: dict) -> dict:
    """The "My roster" column (issue #151): the counted cards in My Team's order,
    then the subbed-out cards they replaced. Unused bench cards are left out.
    Before reveal: the lock-time roster, identity fields only."""
    if not week.is_locked:
        return {"cards": [], "week_total": 0.0} if revealed else {"cards": []}
    roster = _build_roster_response(db, user_id, week.id)
    if not revealed:
        # Swap each subbed-in card back for the card it replaced, so the list
        # gives nothing away.
        entries = db.query(WeeklyRosterEntry).filter_by(week_id=week.id, user_id=user_id).all()
        card_of_entry = {e.id: e.card_id for e in entries}
        replaced_card = {e.card_id: card_of_entry.get(e.subbed_for_entry_id)
                         for e in entries if e.subbed_in}
        by_card_id = {c["id"]: c for c in roster["active"] + roster["bench"]}
        lock_time = []
        for c in roster["active"]:
            if c["subbed_in"] and replaced_card.get(c["id"]) in by_card_id:
                c = by_card_id[replaced_card[c["id"]]]
            lock_time.append({k: v for k, v in _roster_card(c).items() if k in _IDENTITY_KEYS})
        return {"cards": lock_time}
    cards = [_roster_card(c) for c in roster["active"]] + \
            [_roster_card(c) for c in roster["bench"] if c["subbed_out"]]
    games = _card_games(db, week, cards, game_numbers)
    breakdowns = _card_breakdowns(db, week, [c for c in cards if c["counted"]])
    for c in cards:
        c["games"] = games.get(c["card_id"], [])
        if c["counted"]:
            c["breakdown"] = breakdowns[c["card_id"]]
    return {"week_total": roster["combined_value"], "cards": cards}


def _build_week_summary(db, week: Week, revealed: bool, user_id: int) -> dict:
    match_rows = db.execute(text("""
        SELECT m.match_id, m.radiant_team_id, m.dire_team_id, m.radiant_win,
               m.start_time, m.vod_url, m.excluded_from_scoring
        FROM matches m
        WHERE m.week_override_id = :week_id
           OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we)
        ORDER BY m.start_time ASC
    """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time}).fetchall()

    team_ids = {r.radiant_team_id for r in match_rows if r.radiant_team_id} | \
               {r.dire_team_id for r in match_rows if r.dire_team_id}
    teams_by_id = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    } if team_ids else {}

    series = _group_into_series([
        {"match_id": r.match_id, "radiant_team_id": r.radiant_team_id,
         "dire_team_id": r.dire_team_id, "start_time": r.start_time}
        for r in match_rows
    ])
    game_numbers = {
        m["match_id"]: i for s in series for i, m in enumerate(s["matches"], start=1)
    }
    roster_block = _build_roster_block(db, week, revealed, user_id, game_numbers)
    counted_card_ids = [c["card_id"] for c in roster_block["cards"] if c.get("counted")]

    roster_player_ids = set()
    if revealed:
        roster_player_ids = {
            row[0] for row in
            db.query(Card.player_id)
              .join(WeeklyRosterEntry, WeeklyRosterEntry.card_id == Card.id)
              .filter(WeeklyRosterEntry.week_id == week.id,
                      WeeklyRosterEntry.user_id == user_id,
                      text(counted_roster_entry_sql("weekly_roster_entries")))
              .all()
        }

    match_ids = [r.match_id for r in match_rows]
    excluded_ids = {r.match_id for r in match_rows if r.excluded_from_scoring}
    # Issue #151: the user's counted cards' stored points per (player, match).
    card_points_by = {}
    if revealed and match_ids and counted_card_ids:
        cmp_rows = db.execute(text("""
            SELECT c.player_id, cmp.match_id, SUM(cmp.points) as points
            FROM card_match_points cmp
            JOIN cards c ON c.id = cmp.card_id
            WHERE cmp.card_id IN :card_ids
            GROUP BY c.player_id, cmp.match_id
        """).bindparams(bindparam("card_ids", expanding=True)),
            {"card_ids": counted_card_ids}).fetchall()
        card_points_by = {(r.player_id, r.match_id): r.points for r in cmp_rows}

    players_by_match = {}
    if revealed and match_ids:
        stat_rows = (
            db.query(PlayerMatchStats, Player)
              .join(Player, Player.id == PlayerMatchStats.player_id)
              .filter(PlayerMatchStats.match_id.in_(match_ids))
              .all()
        )
        for stats, player in stat_rows:
            players_by_match.setdefault(stats.match_id, []).append({
                "player_id": player.id,
                "name": player.name,
                "avatar_url": player.avatar_url,
                "team_id": stats.team_id,
                "points": None if stats.match_id in excluded_ids else display_points(stats.fantasy_points),
                "is_mvp": bool(stats.is_mvp),
                "on_roster": player.id in roster_player_ids,
                "card_points": (
                    display_points(card_points_by[(player.id, stats.match_id)])
                    if (player.id, stats.match_id) in card_points_by
                    and stats.match_id not in excluded_ids else None
                ),
            })

    matches = []
    for r in match_rows:
        winner_team_id = None
        if r.radiant_win is not None and r.radiant_team_id and r.dire_team_id:
            winner_team_id = r.radiant_team_id if r.radiant_win else r.dire_team_id
        match = {
            "match_id": r.match_id,
            "radiant_team_id": r.radiant_team_id,
            "dire_team_id": r.dire_team_id,
            "radiant_team": _team_dict(teams_by_id.get(r.radiant_team_id)),
            "dire_team": _team_dict(teams_by_id.get(r.dire_team_id)),
            "winner_team_id": winner_team_id if revealed else None,
            "vod_url": r.vod_url,
            "start_time": r.start_time,
            "excluded_from_scoring": bool(r.excluded_from_scoring),
        }
        if revealed:
            match["players"] = players_by_match.get(r.match_id, [])
        matches.append(match)

    return {
        "week_id": week.id,
        "label": week.label,
        "revealed": revealed,
        "series": _group_into_series(matches),
        "roster": roster_block,
        # Issue #129: the report opens at week end, but bench substitutions run
        # SUBSTITUTION_DELAY_HOURS later; until then on_roster marks may change.
        "substitutions_pending": week.substitutions_at is None,
        "substitutions_at": week.substitutions_at,
        "substitution_delay_hours": substitution_delay_hours(),
    }


@router.get("/weekly-summary")
def list_weekly_summaries(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    rows = (
        db.query(WeeklySummary, Week)
          .join(Week, Week.id == WeeklySummary.week_id)
          .order_by(Week.start_time.desc())
          .all()
    )
    revealed_ids = {
        row[0] for row in
        db.query(WeeklySummaryReveal.week_id)
          .filter(WeeklySummaryReveal.user_id == current_user["user_id"]).all()
    }
    seen = db.get(WeeklySummarySeen, current_user["user_id"])
    latest = rows[0][1] if rows else None
    latest_week_id = latest.id if latest else None
    has_unseen = latest_week_id is not None and (
        seen is None or seen.last_seen_week_id != latest_week_id
    )
    # Issue #151: the "recap is ready" popup announces the newest week once —
    # opening the report or dismissing the popup both count as announced.
    show_prompt = latest_week_id is not None and (
        seen is None or latest_week_id not in (seen.last_seen_week_id, seen.last_prompted_week_id)
    )
    weeks = [
        {"week_id": w.id, "label": w.label, "revealed": w.id in revealed_ids}
        for _, w in rows
    ]
    return {
        "weeks": weeks,
        "has_unseen": has_unseen,
        "show_prompt": show_prompt,
        "latest_week": {"week_id": latest.id, "label": latest.label} if latest else None,
    }


@router.get("/weekly-summary/{week_id}")
def get_weekly_summary(week_id: int, db=Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    summary = db.get(WeeklySummary, week_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Weekly summary not available")
    week = db.get(Week, week_id)
    revealed = db.query(WeeklySummaryReveal).filter_by(
        week_id=week_id, user_id=current_user["user_id"]).first() is not None
    return _build_week_summary(db, week, revealed, current_user["user_id"])


@router.post("/weekly-summary/{week_id}/reveal")
def reveal_weekly_summary(week_id: int, db=Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    summary = db.get(WeeklySummary, week_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Weekly summary not available")
    week = db.get(Week, week_id)
    existing = db.query(WeeklySummaryReveal).filter_by(
        week_id=week_id, user_id=current_user["user_id"]).first()
    if not existing:
        db.add(WeeklySummaryReveal(week_id=week_id, user_id=current_user["user_id"],
                                   revealed_at=int(time.time())))
        db.commit()
    return _build_week_summary(db, week, True, current_user["user_id"])


@router.post("/weekly-summary/reveal-all")
def reveal_all_weekly_summaries(db=Depends(get_db),
                                current_user: dict = Depends(get_current_user)):
    """Reveal every currently-available week for the current user in one call.
    Idempotent — weeks the user has already revealed are left untouched (no
    duplicate row, no revealed_at overwrite). A week whose WeeklySummary row is
    created later, by the generate_weekly_summaries background pass, is untouched
    by past calls and stays unrevealed until this is called again."""
    week_ids = [row[0] for row in db.query(WeeklySummary.week_id).all()]
    already = {
        row[0] for row in
        db.query(WeeklySummaryReveal.week_id)
          .filter(WeeklySummaryReveal.user_id == current_user["user_id"],
                  WeeklySummaryReveal.week_id.in_(week_ids)).all()
    }
    now = int(time.time())
    for week_id in week_ids:
        if week_id not in already:
            db.add(WeeklySummaryReveal(week_id=week_id, user_id=current_user["user_id"],
                                       revealed_at=now))
    db.commit()
    return {"revealed_week_ids": week_ids}


def _latest_report_week(db):
    return (
        db.query(Week)
          .join(WeeklySummary, WeeklySummary.week_id == Week.id)
          .order_by(Week.start_time.desc())
          .first()
    )


def _seen_row(db, user_id: int) -> WeeklySummarySeen:
    seen = db.get(WeeklySummarySeen, user_id)
    if not seen:
        seen = WeeklySummarySeen(user_id=user_id)
        db.add(seen)
    return seen


@router.post("/weekly-summary/seen")
def mark_weekly_summary_seen(db=Depends(get_db),
                             current_user: dict = Depends(get_current_user)):
    latest = _latest_report_week(db)
    if not latest:
        return {"ok": True}
    seen = _seen_row(db, current_user["user_id"])
    seen.last_seen_week_id = latest.id
    seen.last_prompted_week_id = latest.id  # opening the report counts as announced
    db.commit()
    return {"ok": True}


@router.post("/weekly-summary/prompted")
def mark_weekly_summary_prompted(db=Depends(get_db),
                                 current_user: dict = Depends(get_current_user)):
    """The "recap is ready" popup was shown and dismissed (issue #151): mark the
    newest report week announced without marking it seen. Idempotent."""
    latest = _latest_report_week(db)
    if not latest:
        return {"ok": True}
    seen = _seen_row(db, current_user["user_id"])
    seen.last_prompted_week_id = latest.id
    db.commit()
    return {"ok": True}
