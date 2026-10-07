"""Tests for plan-issue-141-stored-card-points (GitHub issue #141).

Card points are stored per (card, match) in a new `card_match_points` table
(`CardMatchPoints` in backend/models.py), written by backend/card_points.py
(`refresh_card_points`, `rebuild_all`, `weights_fingerprint`), and every view
(My Team, weekly leaderboard, season leaderboard, End Season archive) sums the
stored rows instead of recalculating per request. The death bonus is floored
per match.

Fixture approach:
- `_seed` builds users/players/teams/cards/weeks/roster entries/matches/stats/weights
  directly, then calls `card_points.rebuild_all(db)` so stored rows exist before reading.
- Readers are called directly: `routers.cards._build_roster_response(db, user_id, week_id)`,
  `routers.leaderboard.weekly_leaderboard(week_id=..., db=db)`,
  `routers.leaderboard.compute_season_standings(db)`.
- Endpoints (draw, reroll, MVP, recalculate, season reset, league purge) are called as
  plain functions with `db=db` and a `current_user`/`admin` dict.
- Startup check: `card_points.ensure_card_points_current(db)` is called directly; main is
  only inspected as source (lessons-learned 2026-09-27 / 2026-09-28).
- Query counts: a `before_cursor_execute` listener on `db.get_bind()`.
- Benchmark ms targets (scripts/bench_leaderboards.py) are manual verification.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

import card_points
import card_utils
import ingest
import scoring
import twitch
from card_utils import _compute_card_points, _load_weights, _mvp_bonus_delta
from deps import require_admin
from models import (
    Card, CardMatchPoints, CardModifier, League, Match, Player, PlayerMatchStats, ScoringState,
    Team, TwitchMVP, User, Week, WeeklyRosterEntry, Weight,
)
from routers import admin_ingest, admin_leagues, admin_matches, admin_players, admin_season
from routers import cards as cards_router
from routers import leaderboard as leaderboard_router
from routers.cards import _build_roster_response
from routers.leaderboard import compute_season_standings, weekly_leaderboard
from scoring import card_fantasy_score, display_points, fantasy_score, stat_dict_from_row

REPO = Path(__file__).resolve().parents[2]
_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}

_WEIGHTS = {
    "kills": 0.3, "gold_per_min": 0.002,
    "death_pool": 3.0, "death_deduction": 0.3, "mvp_bonus_pct": 10.0,
    "rarity_common": 0.0, "rarity_rare": 1.0, "rarity_epic": 2.0, "rarity_legendary": 3.0,
    "modifier_count_common": 0.0, "modifier_count_rare": 1.0, "modifier_count_epic": 2.0,
    "modifier_count_legendary": 3.0, "modifier_bonus_pct": 10.0, "team_booster_cost": 3.0,
}

# (match_id, start_time, {player_id: (kills, deaths, gpm, is_mvp)})
# Week 1 = [0, 1000] locked, Week 2 = [1001, 2000] locked, Week 3 = [2001, 3000] unlocked.
_MATCHES = [
    (1, 100, {101: (5, 2, 437, True), 102: (3, 12, 391, False), 103: (1, 1, 512, False)}),
    (2, 200, {101: (2, 1, 403, False), 102: (4, 0, 455, False), 103: (6, 3, 377, False)}),
    (3, 1500, {101: (7, 4, 521, False), 102: (2, 2, 333, False), 103: (0, 5, 299, False)}),
    (4, 2500, {101: (1, 0, 310, False)}),
    (5, 5000, {101: (10, 0, 600, False)}),
]


def _stats(kills, deaths, gpm):
    return {"kills": kills, "deaths": deaths, "gold_per_min": gpm}


def _add_weights(db, weights=_WEIGHTS):
    for key, value in weights.items():
        db.add(Weight(key=key, label=key, value=value))


def _seed(db, rebuild=True):
    """alice (1) holds c1 rare P101 (+10% kills), c2 common P102, bench c5 common P103.
    bob (2) holds c3 common P101, c4 epic P103 (+10% deaths, +10% gpm).
    Week 1 roster: alice c1, c2; bob c3, c4. Week 2 roster: alice c1; bob c3, c4."""
    _add_weights(db)
    db.add(User(id=1, username="alice", email="a@test", password_hash="x", tokens=5))
    db.add(User(id=2, username="bob", email="b@test", password_hash="x", tokens=5))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    for pid in (101, 102, 103):
        db.add(Player(id=pid, name=f"P{pid}"))
    db.add(Card(id=1, player_id=101, owner_id=1, card_type="rare", is_active=True, slot_index=0))
    db.add(Card(id=2, player_id=102, owner_id=1, card_type="common", is_active=True, slot_index=1))
    db.add(Card(id=5, player_id=103, owner_id=1, card_type="common", is_active=False))
    db.add(Card(id=3, player_id=101, owner_id=2, card_type="common", is_active=True, slot_index=0))
    db.add(Card(id=4, player_id=103, owner_id=2, card_type="epic", is_active=True, slot_index=1))
    db.add(CardModifier(card_id=1, stat_key="kills", bonus_pct=10.0))
    db.add(CardModifier(card_id=4, stat_key="deaths", bonus_pct=10.0))
    db.add(CardModifier(card_id=4, stat_key="gold_per_min", bonus_pct=10.0))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=1000, is_locked=True))
    db.add(Week(id=2, label="Week 2", start_time=1001, end_time=2000, is_locked=True))
    db.add(Week(id=3, label="Week 3", start_time=2001, end_time=3000, is_locked=False))
    for week_id, user_id, card_id in ((1, 1, 1), (1, 1, 2), (1, 2, 3), (1, 2, 4),
                                      (2, 1, 1), (2, 2, 3), (2, 2, 4)):
        db.add(WeeklyRosterEntry(week_id=week_id, user_id=user_id, card_id=card_id))
    for match_id, start, players in _MATCHES:
        db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=2, start_time=start,
                     radiant_win=True, league_id=1))
        for pid, (kills, deaths, gpm, is_mvp) in players.items():
            stats = _stats(kills, deaths, gpm)
            base = fantasy_score(stats, _WEIGHTS)
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=1 if pid != 103 else 2,
                                    fantasy_points=round(base * 1.1 if is_mvp else base, 4),
                                    is_mvp=is_mvp, **stats))
    db.commit()
    if rebuild:
        card_points.rebuild_all(db)


def _stored(db) -> dict:
    return {(r.card_id, r.match_id): r.points
            for r in db.execute(select(CardMatchPoints.card_id, CardMatchPoints.match_id,
                                       CardMatchPoints.points)).all()}


def _expected(db, card_id, match_id) -> float:
    """Per-match card points computed straight from the plan's formula."""
    weights, rarity = _load_weights(db)
    card = db.get(Card, card_id)
    row = db.query(PlayerMatchStats).filter_by(player_id=card.player_id, match_id=match_id).one()
    mods = card_utils._card_modifiers_map(db, [card_id]).get(card_id, {})
    mvp = _mvp_bonus_delta(row, weights) if row.is_mvp else 0.0
    return _compute_card_points(stat_dict_from_row(row), card.card_type, weights, rarity, mods,
                                mvp_bonus=mvp, match_count=1)


def _weekly_cards(db, week_id):
    return {r["username"]: {c["card_id"]: c["points"] for c in r["cards"]}
            for r in weekly_leaderboard(week_id=week_id, db=db)}


def _weekly_totals(db, week_id):
    return {r["username"]: r["week_points"] for r in weekly_leaderboard(week_id=week_id, db=db)}


def _season_cards(db):
    return {r["username"]: {c["card_id"]: c["points"] for c in r["cards"]}
            for r in compute_season_standings(db)}


def _season_totals(db):
    return {r["username"]: r["points"] for r in compute_season_standings(db)}


def _roster_points(db, user_id, week_id):
    result = _build_roster_response(db, user_id, week_id)
    return {c["id"]: c["total_points"] for c in result["active"] + result["bench"]}


def _all_readers(db):
    """Every reader's numbers as one flat dict (pytest.approx does not nest)."""
    groups = {
        "w1": _weekly_totals(db, 1), "w2": _weekly_totals(db, 2), "s": _season_totals(db),
        "r1": _roster_points(db, 1, 1), "r2": _roster_points(db, 2, 1),
        "rs": {"alice": _build_roster_response(db, 1, 1)["season_points"]},
    }
    return {f"{g}_{k}": v for g, values in groups.items() for k, v in values.items()}


def _set_excluded(db, match_id, value):
    db.get(Match, match_id).excluded_from_scoring = value
    db.commit()


class _QueryCounter:
    def __init__(self, db):
        self.engine = db.get_bind()
        self.count = 0

    def _inc(self, *a, **k):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._inc)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._inc)


# ---------------------------------------------------------------------------
# Story 1 — One Card Value Everywhere
# ---------------------------------------------------------------------------

def test_card_week_points_equal_sum_of_stored_match_points_on_every_page(db):
    """A card's week points are the sum of its stored per-match points for the scored
    matches in the week window, identical on My Team (_build_roster_response active
    card total_points), weekly_leaderboard card entry and the per-week sum behind
    compute_season_standings."""
    _seed(db)
    stored = _stored(db)
    wk1 = stored[(1, 1)] + stored[(1, 2)]
    wk2 = stored[(1, 3)]

    # Every reader shows the exact stored sum rounded once (issue #149).
    assert _roster_points(db, 1, 1)[1] == display_points(wk1)
    assert _roster_points(db, 1, 2)[1] == display_points(wk2)
    assert _weekly_cards(db, 1)["alice"][1] == display_points(wk1)
    assert _weekly_cards(db, 2)["alice"][1] == display_points(wk2)
    assert _season_cards(db)["alice"][1] == display_points(wk1 + wk2)


def test_card_season_points_equal_sum_of_weekly_points_over_locked_weeks(db):
    """A card's season points equal the sum of its weekly points over the locked weeks
    it was rostered in (two locked weeks, card rostered in both; season chip ==
    week1 + week2 from weekly_leaderboard)."""
    _seed(db)
    stored = _stored(db)
    w1, w2, season = _weekly_cards(db, 1), _weekly_cards(db, 2), _season_cards(db)
    for user, card_id in (("alice", 1), ("bob", 3), ("bob", 4)):
        # Exact: the season chip is the card's stored points over matches 1-3 (weeks 1-2).
        assert season[user][card_id] == display_points(sum(stored[(card_id, m)] for m in (1, 2, 3)))
        # Shown values: each is rounded once, so they may differ by up to 0.05 per value.
        assert season[user][card_id] == pytest.approx(w1[user][card_id] + w2[user][card_id], abs=0.15)


def test_user_weekly_and_season_totals_equal_sum_of_card_points(db):
    """A user's week_points (weekly_leaderboard) and season points
    (compute_season_standings, _build_roster_response season_points) equal the sum
    of their cards' points in that scope."""
    _seed(db)
    stored = _stored(db)
    alice_season = sum(stored[k] for k in ((1, 1), (1, 2), (1, 3), (2, 1), (2, 2)))
    bob_season = sum(stored[k] for k in ((3, 1), (3, 2), (3, 3), (4, 1), (4, 2), (4, 3)))
    alice_w1 = sum(stored[k] for k in ((1, 1), (1, 2), (2, 1), (2, 2)))

    assert _weekly_totals(db, 1)["alice"] == display_points(alice_w1)
    assert _season_totals(db) == {"alice": display_points(alice_season), "bob": display_points(bob_season)}
    assert _build_roster_response(db, 1, 1)["season_points"] == display_points(alice_season)
    assert _build_roster_response(db, 2, 2)["season_points"] == display_points(bob_season)
    assert _build_roster_response(db, 1, 1)["combined_value"] == display_points(alice_w1)


def test_death_bonus_floored_per_match_matches_players_tab_fantasy_points(db):
    """Death bonus is floored at 0 per match: a common card (no modifiers, rarity 1,
    no MVP) with one high-death match and one low-death match has week points equal
    to the sum of the two matches' PlayerMatchStats.fantasy_points, not the
    aggregate max(0, pool*games - deaths*deduction) value."""
    _seed(db)
    rows = db.query(PlayerMatchStats).filter(PlayerMatchStats.player_id == 102,
                                             PlayerMatchStats.match_id.in_([1, 2])).all()
    per_match = sum(r.fantasy_points for r in rows)
    aggregate = card_fantasy_score({"kills": 7, "deaths": 12, "gold_per_min": 391 + 455},
                                   _WEIGHTS, {}, match_count=2)

    week = _roster_points(db, 1, 1)[2]

    assert week == display_points(per_match)
    assert week != display_points(aggregate)
    assert per_match > aggregate


def test_compute_season_standings_card_chips_carry_season_scope(db):
    """Season leaderboard card chips include "scope": "season" (response shape
    otherwise unchanged)."""
    _seed(db)
    season = compute_season_standings(db)
    chips = [c for r in season for c in r["cards"]]
    assert chips
    assert all(c["scope"] == "season" for c in chips)
    assert all(set(c) == {"card_id", "card_type", "player_name", "points", "scope"} for c in chips)
    assert all(set(r) == {"id", "username", "points", "is_admin", "tags", "cards"} for r in season)
    weekly_chips = [c for r in weekly_leaderboard(week_id=1, db=db) for c in r["cards"]]
    assert all(set(c) == {"card_id", "card_type", "player_name", "points"} for c in weekly_chips)
    endpoint = leaderboard_router.season_leaderboard(db=db)
    assert all(c["scope"] == "season" for r in endpoint for c in r["cards"])


def test_season_view_renders_no_chips_and_weekly_chips_match_my_team(db):
    """The season leaderboard view shows totals only (no card chips); weekly
    leaderboard chips and My Team show the same stored week value for a card.
    Static check of frontend/app-leaderboard.js plus a backend comparison."""
    lb = (REPO / "frontend" / "app-leaderboard.js").read_text()
    roster = (REPO / "frontend" / "app-roster.js").read_text()
    assert '_lbStandingsRow(r, i, "season_points", false)' in lb
    assert '_lbStandingsRow(r, i, "week_points")' in lb
    assert 'c.scope === "season"' not in lb
    assert "lb-chip-scope" not in lb
    assert "_escHtml(c.player_name)" in lb
    assert "wk pts" in roster

    _seed(db)
    for week_id in (1, 2):
        for row in weekly_leaderboard(week_id=week_id, db=db):
            my_team = {c["id"]: c["total_points"]
                       for c in _build_roster_response(db, row["id"], week_id)["active"]}
            assert row["cards"]
            for chip in row["cards"]:
                assert chip["points"] == my_team[chip["card_id"]]


def test_card_values_add_up_to_shown_total_within_rounding(db):
    """Values are rounded only for display: across several cards with fractional
    per-match points, the sum of the card values in each response is within 0.1 of
    the user total in that response (weekly, season, My Team)."""
    _seed(db)
    assert any(abs(p - round(p, 1)) > 1e-6 for p in _stored(db).values())
    for rows, key in ((weekly_leaderboard(week_id=1, db=db), "week_points"),
                      (compute_season_standings(db), "points")):
        for r in rows:
            assert abs(sum(c["points"] for c in r["cards"]) - r[key]) < 0.1
    roster = _build_roster_response(db, 1, 1)
    assert abs(sum(c["total_points"] for c in roster["active"]) - roster["combined_value"]) < 0.1


def test_card_week_points_ignore_matches_outside_window_and_unrostered_weeks(db):
    """Failure path: stored points for matches outside the week window, excluded
    matches, and locked weeks where the card was not rostered do not count toward
    the card's week or season points."""
    _seed(db)
    stored = _stored(db)
    assert (1, 4) in stored and (1, 5) in stored and (2, 3) in stored

    season = _season_cards(db)
    assert season["alice"][1] == display_points(stored[(1, 1)] + stored[(1, 2)] + stored[(1, 3)])
    # c2 is not on alice's Week 2 roster, so match 3 does not count for it.
    assert season["alice"][2] == display_points(stored[(2, 1)] + stored[(2, 2)])

    _set_excluded(db, 2, True)
    assert _weekly_cards(db, 1)["alice"][1] == display_points(stored[(1, 1)])
    assert _roster_points(db, 1, 1)[1] == display_points(stored[(1, 1)])


# ---------------------------------------------------------------------------
# Story 2 — Stored Per-Match Card Points
# ---------------------------------------------------------------------------

def test_card_match_points_unique_constraint_rejects_duplicate_card_match(db):
    """Failure path: inserting a second CardMatchPoints row for the same (card_id,
    match_id) raises IntegrityError (uq_card_match_points)."""
    db.add(CardMatchPoints(card_id=1, match_id=1, player_id=101, points=1.0))
    db.commit()
    db.add(CardMatchPoints(card_id=1, match_id=1, player_id=101, points=2.0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_refresh_card_points_stores_final_points_with_modifiers_mvp_and_rarity(db):
    """refresh_card_points stores one row per (card, match) whose points equal
    _compute_card_points(stat_dict_from_row(row), card_type, weights, rarity, mods,
    mvp_bonus=_mvp_bonus_delta(row, weights) if is_mvp else 0, match_count=1) — a rare
    card with a modifier, one MVP match and one non-MVP match."""
    _seed(db, rebuild=False)
    written = card_points.refresh_card_points(db, card_ids=[1])
    db.commit()

    stored = _stored(db)
    assert written == 5
    assert set(stored) == {(1, m) for m in (1, 2, 3, 4, 5)}
    for match_id in (1, 2, 3, 4, 5):
        assert stored[(1, match_id)] == pytest.approx(_expected(db, 1, match_id))
    # Match 1 by hand: kills 5*0.3*1.1 = 1.65, gpm 437*0.002 = 0.874, deaths 3 - 0.6 = 2.4
    # -> 4.924; MVP bonus = fantasy_score (1.5 + 0.874 + 2.4 = 4.774) * 10% = 0.4774;
    # rare x1.01 -> (4.924 + 0.4774) * 1.01
    assert stored[(1, 1)] == pytest.approx((4.924 + 0.4774) * 1.01)


def test_refresh_card_points_upserts_existing_rows_without_duplicates(db):
    """Calling refresh_card_points twice for the same card/match updates the row in place
    (ON CONFLICT upsert): row count unchanged, points reflect the latest stats."""
    _seed(db)
    before_count = db.query(CardMatchPoints).count()
    row_id = db.query(CardMatchPoints.id).filter_by(card_id=3, match_id=2).scalar()

    db.query(PlayerMatchStats).filter_by(player_id=101, match_id=2).one().kills = 20
    card_points.refresh_card_points(db, card_ids=[3], match_ids=[2])
    card_points.refresh_card_points(db, card_ids=[3], match_ids=[2])
    db.commit()

    assert db.query(CardMatchPoints).count() == before_count
    assert db.query(CardMatchPoints.id).filter_by(card_id=3, match_id=2).scalar() == row_id
    assert _stored(db)[(3, 2)] == pytest.approx(_expected(db, 3, 2))
    assert _stored(db)[(3, 2)] > 6.0


_PAYLOAD = {
    "version": 21, "duration": 2400, "radiant_win": True, "start_time": 150,
    "radiant_team_id": 1, "dire_team_id": 2,
    "players": [
        {"account_id": 101, "isRadiant": True, "kills": 9, "deaths": 1, "gold_per_min": 500},
        {"account_id": 103, "isRadiant": False, "kills": 2, "deaths": 7, "gold_per_min": 350},
    ],
}


def _patch_opendota(monkeypatch, payload):
    monkeypatch.setattr(ingest, "opendota_get_json", lambda url, *a, **k: payload)
    monkeypatch.setattr(ingest, "opendota_post_json", lambda url, *a, **k: {"job": {"jobId": 1}})
    monkeypatch.setattr(ingest, "_parse_requested", {})


def test_ingest_match_writes_card_match_points_for_players_cards(db, monkeypatch):
    """ingest.ingest_match writes rows for every card of every player in the match
    (patch the OpenDota fetch as in test_unparseable_match_handling._patch_opendota)."""
    _seed(db)
    _patch_opendota(monkeypatch, _PAYLOAD)

    ingest.ingest_match(db, 777, 1, set(), set(), dict(_WEIGHTS))

    stored = _stored(db)
    new_keys = {k for k in stored if k[1] == 777}
    assert new_keys == {(1, 777), (3, 777), (4, 777), (5, 777)}
    for card_id, match_id in new_keys:
        assert stored[(card_id, match_id)] == pytest.approx(_expected(db, card_id, match_id))
    # Match 777 falls in Week 1: alice's c1 weekly value picks it up with no rebuild.
    assert _roster_points(db, 1, 1)[1] == display_points(stored[(1, 1)] + stored[(1, 2)] + stored[(1, 777)])


def test_refresh_match_stats_updates_card_match_points_after_parse(db, monkeypatch):
    """ingest.refresh_match_stats (parse-retry stat replacement) updates the stored
    points for that match's cards to the new stats."""
    _seed(db)
    payload = {**_PAYLOAD, "players": [
        {"account_id": 101, "isRadiant": True, "kills": 11, "deaths": 0, "gold_per_min": 700},
    ]}
    _patch_opendota(monkeypatch, payload)
    other_before = {k: v for k, v in _stored(db).items() if k[1] != 2}

    assert ingest.refresh_match_stats(db, 2, dict(_WEIGHTS)) == "refreshed"

    stored = _stored(db)
    assert stored[(1, 2)] == pytest.approx(_expected(db, 1, 2))
    assert stored[(3, 2)] == pytest.approx((11 * 0.3 + 700 * 0.002 + 3.0))
    # Players 102 and 103 have no stat rows in the replaced match any more.
    assert not any(k in stored for k in ((2, 2), (4, 2), (5, 2)))
    assert {k: v for k, v in stored.items() if k[1] != 2} == pytest.approx(other_before)


def test_reapply_mvp_bonus_refreshes_card_match_points(db):
    """ingest._reapply_mvp_bonus leaves stored card points including the MVP bonus
    for the match's MVP."""
    _seed(db)
    before = _stored(db)[(3, 2)]
    db.add(TwitchMVP(match_id=2, player_id=101, channel_id="c", selected_at=0))
    db.commit()

    ingest._reapply_mvp_bonus(db, 2)

    row = db.query(PlayerMatchStats).filter_by(player_id=101, match_id=2).one()
    assert row.is_mvp is True
    # c3 is a common card with no modifiers: its stored points equal the MVP'd fantasy_points.
    assert _stored(db)[(3, 2)] == pytest.approx(row.fantasy_points, abs=1e-3)
    assert _stored(db)[(3, 2)] == pytest.approx(before * 1.1)


@pytest.fixture
def twitch_env(monkeypatch):
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    monkeypatch.setattr(twitch, "_eligible_mvp_match_ids", lambda db: {1, 2, 3})
    monkeypatch.setattr(twitch, "_pubsub_broadcast", lambda *a, **k: None)
    monkeypatch.setattr(twitch, "_post_chat_message", lambda *a, **k: None)
    monkeypatch.setattr(twitch, "bust_cache", lambda: None)


def test_twitch_set_mvp_refreshes_card_match_points_for_match(db, twitch_env):
    """Twitch MVP set/change (twitch.set_mvp path via upsert_mvp + _apply_mvp_bonus)
    refreshes the match's rows: new MVP's cards gain the bonus, previous MVP's cards
    lose it, rows for other matches untouched."""
    _seed(db)
    before = _stored(db)
    payload = {"channel_id": "chan", "role": "broadcaster", "opaque_user_id": "U1"}

    twitch.set_mvp(twitch.MVPBody(match_id=2, player_id=103), payload=payload, db=db)
    after_first = _stored(db)
    assert after_first[(4, 2)] > before[(4, 2)]
    assert after_first[(4, 2)] == pytest.approx(_expected(db, 4, 2))

    twitch.set_mvp(twitch.MVPBody(match_id=2, player_id=101), payload=payload, db=db)
    after = _stored(db)
    assert after[(4, 2)] == pytest.approx(before[(4, 2)])
    assert after[(3, 2)] > before[(3, 2)]
    assert after[(3, 2)] == pytest.approx(_expected(db, 3, 2))
    assert {k: v for k, v in after.items() if k[1] != 2} == pytest.approx(
        {k: v for k, v in before.items() if k[1] != 2})


def test_admin_set_mvp_refreshes_card_match_points_for_match(db):
    """routers.admin_matches.admin_set_mvp refreshes that match's rows, including
    removing the bonus from the previous MVP's cards."""
    _seed(db)
    before = _stored(db)
    # Match 1's MVP is player 101 (seeded is_mvp) — register it so the change clears it.
    db.add(TwitchMVP(match_id=1, player_id=101, channel_id="admin", selected_at=0))
    db.commit()

    admin_matches.admin_set_mvp(1, admin_matches.AdminMVPRequest(player_id=103), db=db, admin=_ADMIN)

    after = _stored(db)
    assert after[(3, 1)] < before[(3, 1)]
    assert after[(3, 1)] == pytest.approx(_expected(db, 3, 1))
    assert after[(4, 1)] > before[(4, 1)]
    assert after[(5, 1)] == pytest.approx(_expected(db, 5, 1))
    assert {k: v for k, v in after.items() if k[1] != 1} == pytest.approx(
        {k: v for k, v in before.items() if k[1] != 1})


def test_admin_set_mvp_unknown_match_leaves_card_match_points_unchanged(db):
    """Failure path: admin_set_mvp on an unknown match returns 404 and writes no
    card_match_points rows."""
    _seed(db)
    before = _stored(db)
    with pytest.raises(HTTPException) as exc:
        admin_matches.admin_set_mvp(9999, admin_matches.AdminMVPRequest(player_id=101), db=db, admin=_ADMIN)
    assert exc.value.status_code == 404
    assert _stored(db) == before


def test_draw_card_writes_card_match_points_for_all_player_matches(db, monkeypatch):
    """routers.cards.draw_card: the drawn card gets a row for every existing match of
    its player."""
    _seed(db)
    db.add(User(id=3, username="carol", email="c@test", password_hash="x", tokens=3))
    db.commit()
    monkeypatch.setattr(cards_router, "_roll_rarity", lambda w: "rare")
    monkeypatch.setattr(cards_router, "_pick_player", lambda db_, uid, rarity: db_.get(Player, 101))

    result = cards_router.draw_card(db=db, current_user={"user_id": 3})

    new_id = result["id"]
    stored = _stored(db)
    assert {k for k in stored if k[0] == new_id} == {(new_id, m) for m in (1, 2, 3, 4, 5)}
    for m in (1, 2, 3, 4, 5):
        assert stored[(new_id, m)] == pytest.approx(_expected(db, new_id, m))


def test_draw_booster_writes_card_match_points_for_drawn_cards(db, monkeypatch):
    """routers.cards.draw_booster (team draw): every drawn card gets rows for all of
    its player's matches."""
    _seed(db)
    db.add(User(id=3, username="carol", email="c@test", password_hash="x", tokens=10))
    db.commit()
    monkeypatch.setattr(cards_router, "_roll_rarity", lambda w: "epic")

    result = cards_router.draw_booster(team_id=2, db=db, current_user={"user_id": 3})

    new_id = result["id"]
    assert result["player_id"] == 103
    stored = _stored(db)
    assert {k for k in stored if k[0] == new_id} == {(new_id, m) for m in (1, 2, 3)}
    for m in (1, 2, 3):
        assert stored[(new_id, m)] == pytest.approx(_expected(db, new_id, m))


def test_reroll_modifiers_refreshes_only_that_card(db, monkeypatch):
    """routers.cards.reroll_modifiers rewrites the rerolled card's rows to match its
    new modifiers; rows for the user's other cards are unchanged."""
    _seed(db)
    before = _stored(db)
    monkeypatch.setattr(card_utils.random, "sample", lambda population, k: ["gold_per_min"][:k])

    cards_router.reroll_modifiers(1, db=db, current_user={"user_id": 1})

    after = _stored(db)
    assert card_utils._card_modifiers_map(db, [1])[1] == {"gold_per_min": 10.0}
    for m in (1, 2, 3, 4, 5):
        assert after[(1, m)] == pytest.approx(_expected(db, 1, m))
    assert after[(1, 1)] != pytest.approx(before[(1, 1)])
    assert {k: v for k, v in after.items() if k[0] != 1} == pytest.approx(
        {k: v for k, v in before.items() if k[0] != 1})


def test_reroll_modifiers_without_tokens_leaves_card_match_points_unchanged(db):
    """Failure path: reroll with 0 tokens returns 409 and the card's stored points
    are unchanged."""
    _seed(db)
    db.get(User, 1).tokens = 0
    db.commit()
    before = _stored(db)
    with pytest.raises(HTTPException) as exc:
        cards_router.reroll_modifiers(1, db=db, current_user={"user_id": 1})
    assert exc.value.status_code == 409
    assert _stored(db) == before


def test_reset_season_deletes_all_card_match_points(db, monkeypatch, tmp_path):
    """routers.admin_season.reset_season deletes card_match_points along with cards
    and matches (patch backup_sqlite_db for the pre-reset backup)."""
    _seed(db)
    assert db.query(CardMatchPoints).count() > 0
    monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda: str(tmp_path / "backup.db"))

    result = admin_season.reset_season(admin_season.SeasonResetBody(force=True), db=db, admin=_ADMIN)

    assert db.query(CardMatchPoints).count() == 0
    assert db.query(Card).count() == 0
    assert result["counts"]["card_match_points"] > 0


def test_purge_league_data_deletes_card_match_points_for_league_matches(db):
    """routers.admin_leagues.purge_league_data deletes rows for that league's matches
    only; rows for other leagues' matches remain."""
    _seed(db)
    db.add(League(id=1, name="L1"))
    db.add(League(id=2, name="L2"))
    db.get(Match, 5).league_id = 2
    db.commit()

    admin_leagues.purge_league_data(1, db=db, admin=_ADMIN)

    stored = _stored(db)
    assert stored
    assert {m for _, m in stored} == {5}


def test_remove_players_card_match_points_follow_card_lifecycle(db):
    """routers.admin_players.remove_players deactivates cards (is_active=False) rather
    than deleting them, so their card_match_points rows are kept: past locked weeks
    must still score. No row references a card that no longer exists."""
    _seed(db)
    before = _stored(db)
    season_before = _season_totals(db)

    admin_players.remove_players(admin_players.RemovePlayersBody(player_ids=[101]), db=db, admin=_ADMIN)

    assert db.get(Card, 1) is not None and db.get(Card, 1).is_active is False
    assert _stored(db) == before
    assert _season_totals(db) == pytest.approx(season_before)
    card_ids = {c.id for c in db.query(Card.id).all()}
    assert {c for c, _ in _stored(db)} <= card_ids


def test_readers_sum_stored_card_match_points(db):
    """My Team, weekly_leaderboard, compute_season_standings read SUM(points) from
    card_match_points: planting known stored values (differing from what the stats
    would compute) makes each reader return exactly those sums."""
    _seed(db)
    db.query(CardMatchPoints).update({CardMatchPoints.points: 10.0})
    db.commit()

    assert _roster_points(db, 1, 1) == {1: 20.0, 2: 20.0}
    assert _weekly_totals(db, 1) == {"alice": 40.0, "bob": 40.0}
    assert _season_totals(db) == {"alice": 50.0, "bob": 60.0}
    assert _build_roster_response(db, 1, 1)["season_points"] == 50.0


def test_toggling_excluded_from_scoring_changes_totals_without_rebuild(db, monkeypatch):
    """Match exclusion is applied at read time: setting excluded_from_scoring removes
    the match's points from all readers immediately, clearing restores them, with no
    refresh/rebuild call in between."""
    _seed(db)
    before = _all_readers(db)
    calls = []
    monkeypatch.setattr(card_points, "rebuild_all", lambda *a, **k: calls.append("rebuild"))
    monkeypatch.setattr(card_points, "refresh_card_points", lambda *a, **k: calls.append("refresh"))

    _set_excluded(db, 2, True)
    excluded = _all_readers(db)
    _set_excluded(db, 2, False)
    restored = _all_readers(db)

    assert calls == []
    assert excluded["w1_alice"] < before["w1_alice"]
    assert excluded["s_bob"] < before["s_bob"]
    assert excluded["r1_1"] < before["r1_1"]
    assert excluded["rs_alice"] < before["rs_alice"]
    assert {k: v for k, v in excluded.items() if k.startswith("w2_")} == \
        {k: v for k, v in before.items() if k.startswith("w2_")}
    assert restored == pytest.approx(before)


def test_changing_match_week_override_changes_totals_without_rebuild(db):
    """Week assignment is applied at read time: setting a match's week_override_id to
    another week moves its points between weeks immediately, with no rebuild."""
    _seed(db)
    stored = _stored(db)
    w1_before, w2_before = _weekly_cards(db, 1), _weekly_cards(db, 2)

    db.get(Match, 2).week_override_id = 2
    db.commit()

    w1, w2 = _weekly_cards(db, 1), _weekly_cards(db, 2)
    assert w1_before["alice"][1] == display_points(stored[(1, 1)] + stored[(1, 2)])
    assert w2_before["alice"][1] == display_points(stored[(1, 3)])
    assert w1["alice"][1] == display_points(stored[(1, 1)])
    assert w2["alice"][1] == display_points(stored[(1, 3)] + stored[(1, 2)])
    assert _roster_points(db, 1, 2)[1] == display_points(stored[(1, 3)] + stored[(1, 2)])


def test_roster_unlocked_week_uses_current_cards_with_stored_points(db):
    """For an unlocked week, _build_roster_response sums stored points over the user's
    current active cards (not roster entries), as today."""
    _seed(db)
    stored = _stored(db)

    result = _build_roster_response(db, 1, 3)

    assert [c["id"] for c in result["active"]] == [1, 2]
    assert [c["id"] for c in result["bench"]] == [5]
    points = {c["id"]: c["total_points"] for c in result["active"] + result["bench"]}
    assert points == {1: display_points(stored[(1, 4)]), 2: 0.0, 5: 0.0}
    assert result["combined_value"] == display_points(stored[(1, 4)])


# ---------------------------------------------------------------------------
# Story 3 — Rebuild Stored Points
# ---------------------------------------------------------------------------

def test_recalculate_rebuilds_card_match_points_and_reports_count(db):
    """routers.admin_ingest.recalculate rebuilds every card_match_points row (stale
    planted values replaced) and its response includes the number of rows written."""
    _seed(db)
    expected = _stored(db)
    db.query(CardMatchPoints).update({CardMatchPoints.points: 999.0})
    db.commit()

    result = admin_ingest.recalculate(db=db, admin=_ADMIN)

    assert result["status"] == "ok"
    assert result["recalculated"] == db.query(PlayerMatchStats).count()
    assert result["card_points"] == len(expected)
    assert _stored(db) == pytest.approx(expected)


def test_recalculate_route_requires_admin():
    """Failure path: POST /recalculate still depends on require_admin (inspect the
    route's dependants as in test_unparseable_match_handling._route)."""
    route = next(r for r in admin_ingest.router.routes
                 if getattr(r, "path", None) == "/recalculate" and "POST" in r.methods)
    assert require_admin in [d.call for d in route.dependant.dependencies]


def test_recalculate_rebuild_failure_keeps_fantasy_points_and_previous_card_rows(db, monkeypatch):
    """Failure path: when card_points.rebuild_all raises during POST /recalculate, the
    committed fantasy_points pass persists, the previous card_match_points rows are
    kept, the endpoint returns an error and the audit row records the failure."""
    from models import AuditLog

    _seed(db)
    before_cards = _stored(db)
    # Plant stale fantasy_points so the recalculation pass visibly changes them.
    db.query(PlayerMatchStats).update({PlayerMatchStats.fantasy_points: 999.0})
    db.commit()

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(card_points, "_compute_card_points", _boom)
    with pytest.raises(HTTPException) as exc:
        admin_ingest.recalculate(db=db, admin=_ADMIN)

    assert exc.value.status_code == 500
    db.expire_all()
    points = [r.fantasy_points for r in db.query(PlayerMatchStats).all()]
    assert points and all(p != 999.0 for p in points)
    assert _stored(db) == before_cards
    audit = db.query(AuditLog).filter_by(action="admin_recalculate").one()
    assert "card_points=failed" in audit.detail


def test_weights_fingerprint_is_stable_and_order_independent():
    """card_points.weights_fingerprint gives the same value for the same weights in any
    key order and a different value when any weight value changes."""
    a = {"kills": 0.3, "death_pool": 3.0, "mvp_bonus_pct": 10.0}
    b = {"mvp_bonus_pct": 10.0, "kills": 0.3, "death_pool": 3.0}
    assert card_points.weights_fingerprint(a) == card_points.weights_fingerprint(b)
    assert card_points.weights_fingerprint(a) == card_points.weights_fingerprint(dict(a))
    assert card_points.weights_fingerprint(a) != card_points.weights_fingerprint({**a, "kills": 0.31})
    assert card_points.weights_fingerprint(a) != card_points.weights_fingerprint({**a, "extra": 1.0})


def test_startup_check_rebuilds_when_table_empty(db):
    """The startup check in card_points (called directly, not via main's lifespan)
    rebuilds when card_match_points is empty and stores the weights fingerprint."""
    _seed(db, rebuild=False)
    assert db.query(CardMatchPoints).count() == 0

    rows = card_points.ensure_card_points_current(db)

    assert rows == db.query(CardMatchPoints).count() > 0
    state = db.get(ScoringState, card_points.FINGERPRINT_KEY)
    assert state.value == card_points.weights_fingerprint(_load_weights(db)[0])


def test_startup_check_rebuilds_when_weights_fingerprint_changed(db):
    """The startup check rebuilds when the stored fingerprint differs from the current
    weights (simulated WEIGHTS_JSON change) and stored points reflect the new weights."""
    _seed(db)
    old = _stored(db)[(3, 1)]
    db.get(Weight, "kills").value = 1.0
    db.commit()

    rows = card_points.ensure_card_points_current(db)

    assert rows is not None and rows > 0
    assert _stored(db)[(3, 1)] == pytest.approx(old + 5 * (1.0 - 0.3) * 1.1)
    assert db.get(ScoringState, card_points.FINGERPRINT_KEY).value == \
        card_points.weights_fingerprint(_load_weights(db)[0])


def test_startup_check_skips_rebuild_when_fingerprint_unchanged(db, monkeypatch):
    """The startup check does not rebuild when rows exist and the fingerprint matches
    (spy on rebuild_all; call count 0)."""
    _seed(db)
    calls = []
    monkeypatch.setattr(card_points, "rebuild_all", lambda *a, **k: calls.append(1))

    assert card_points.ensure_card_points_current(db) is None
    assert calls == []


def test_main_lifespan_calls_startup_check_after_seed_weights():
    """main.lifespan calls the card-points startup check after seed_weights() (static
    source inspection of backend/main.py; do not reload main)."""
    src = (REPO / "backend" / "main.py").read_text()
    lifespan = src[src.index("async def lifespan"):]
    lifespan = lifespan[:lifespan.index("yield")]
    assert "seed_weights()" in lifespan
    assert "_ensure_card_points_current()" in lifespan
    assert lifespan.index("seed_weights()") < lifespan.index("_ensure_card_points_current()")
    helper = src[src.index("def _ensure_card_points_current"):src.index("async def lifespan")]
    assert "card_points.ensure_card_points_current(db)" in helper
    assert "logger.exception" in helper


def test_rebuild_all_failure_keeps_previous_rows_and_logs_error(db, monkeypatch, caplog):
    """Failure path: when rebuild_all raises mid-way (monkeypatch the per-card
    computation), the previous rows and fingerprint remain and the error is logged."""
    _seed(db)
    before = _stored(db)
    fingerprint = db.get(ScoringState, card_points.FINGERPRINT_KEY).value
    db.get(Weight, "kills").value = 5.0
    db.commit()

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(card_points, "_compute_card_points", _boom)
    with caplog.at_level("ERROR", logger="card_points"):
        with pytest.raises(RuntimeError):
            card_points.rebuild_all(db)

    assert _stored(db) == before
    assert db.get(ScoringState, card_points.FINGERPRINT_KEY).value == fingerprint
    assert "rebuild failed" in caplog.text


# ---------------------------------------------------------------------------
# Story 4 — Faster Pages
# ---------------------------------------------------------------------------

def _add_users(db, n, start_id=100):
    """n extra users, each with one card for player 103 rostered in Weeks 1 and 2."""
    for i in range(n):
        uid, cid = start_id + i, start_id + i
        db.add(User(id=uid, username=f"u{uid}", email=f"u{uid}@test", password_hash="x", tokens=0))
        db.add(Card(id=cid, player_id=103, owner_id=uid, card_type="rare", is_active=True, slot_index=0))
        db.add(WeeklyRosterEntry(week_id=1, user_id=uid, card_id=cid))
        db.add(WeeklyRosterEntry(week_id=2, user_id=uid, card_id=cid))
    db.commit()
    card_points.rebuild_all(db)


def _count_queries(db, fn):
    db.expire_all()
    with _QueryCounter(db) as qc:
        fn()
    return qc.count


def test_weekly_leaderboard_query_count_independent_of_user_count(db):
    """weekly_leaderboard runs the same number of SQL statements for 2 users as for 20
    users (count via a before_cursor_execute listener)."""
    _seed(db)
    small = _count_queries(db, lambda: weekly_leaderboard(week_id=1, db=db))
    _add_users(db, 18)
    large = _count_queries(db, lambda: weekly_leaderboard(week_id=1, db=db))
    assert len(weekly_leaderboard(week_id=1, db=db)) == 20
    assert small == large


def test_compute_season_standings_query_count_independent_of_user_count(db):
    """compute_season_standings runs the same number of SQL statements regardless of
    the number of users, cards and locked weeks."""
    _seed(db)
    small = _count_queries(db, lambda: compute_season_standings(db))
    _add_users(db, 18)
    db.add(Week(id=4, label="Week 4", start_time=5000, end_time=6000, is_locked=True))
    db.add(WeeklyRosterEntry(week_id=4, user_id=1, card_id=1))
    db.commit()
    large = _count_queries(db, lambda: compute_season_standings(db))
    assert small == large


def test_roster_response_query_count_independent_of_card_count(db):
    """_build_roster_response runs the same number of SQL statements for 1 card as for
    10 cards."""
    _seed(db)
    db.add(User(id=50, username="dave", email="d@test", password_hash="x", tokens=0))
    db.add(Card(id=50, player_id=101, owner_id=50, card_type="rare", is_active=True, slot_index=0))
    db.add(WeeklyRosterEntry(week_id=1, user_id=50, card_id=50))
    db.commit()
    card_points.rebuild_all(db)
    small_locked = _count_queries(db, lambda: _build_roster_response(db, 50, 1))
    small_open = _count_queries(db, lambda: _build_roster_response(db, 50, 3))

    for i in range(9):
        cid = 51 + i
        db.add(Card(id=cid, player_id=(101, 102, 103)[i % 3], owner_id=50,
                    card_type=("common", "rare", "epic")[i % 3], is_active=i < 4, slot_index=i + 1))
        db.add(CardModifier(card_id=cid, stat_key="kills", bonus_pct=10.0))
        db.add(WeeklyRosterEntry(week_id=1, user_id=50, card_id=cid))
    db.commit()
    card_points.rebuild_all(db)

    assert len(_build_roster_response(db, 50, 1)["active"]) == 10
    assert _count_queries(db, lambda: _build_roster_response(db, 50, 1)) == small_locked
    assert _count_queries(db, lambda: _build_roster_response(db, 50, 3)) == small_open


def test_readers_do_not_call_per_card_python_scoring(db, monkeypatch):
    """Failure path: with card_fantasy_score / _compute_card_points monkeypatched to raise
    in routers.cards, routers.leaderboard and card_utils, all three readers still
    return correct stored totals (no per-card Python scoring loop)."""
    _seed(db)
    expected = _all_readers(db)

    def _boom(*a, **k):
        raise AssertionError("per-request card scoring")

    for module in (cards_router, leaderboard_router, card_utils, scoring):
        for name in ("card_fantasy_score", "_compute_card_points", "_mvp_bonus_delta"):
            monkeypatch.setattr(module, name, _boom, raising=False)

    assert _all_readers(db) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Plan Step 5 — Parity with the pre-#141 per-request totals
# ---------------------------------------------------------------------------

def _old_card_week_total(db, card_id, week) -> float:
    """The pre-#141 per-request formula: aggregate the week's scored stats, one death
    pool per game floored over the whole window, plus per-match MVP deltas."""
    weights, rarity = _load_weights(db)
    card = db.get(Card, card_id)
    rows = [s for s, m in db.query(PlayerMatchStats, Match)
            .join(Match, Match.match_id == PlayerMatchStats.match_id)
            .filter(PlayerMatchStats.player_id == card.player_id).all()
            if not m.excluded_from_scoring and week.start_time <= m.start_time <= week.end_time]
    if not rows:
        return 0.0
    sums = {}
    for r in rows:
        for k, v in stat_dict_from_row(r).items():
            sums[k] = sums.get(k, 0) + v
    mvp = sum(_mvp_bonus_delta(r, weights) for r in rows if r.is_mvp)
    mods = card_utils._card_modifiers_map(db, [card_id]).get(card_id, {})
    return _compute_card_points(sums, card.card_type, weights, rarity, mods, mvp, match_count=len(rows))


def test_stored_totals_equal_old_totals_when_death_floor_not_triggered(db):
    """For a fixture season where no match's death term hits the floor, stored totals
    equal the old aggregate formula (card_fantasy_score over summed stats with
    match_count) for every card, week and user."""
    _seed(db, rebuild=False)
    # Lift player 102's 12-death game off the floor so no match floors out.
    db.query(PlayerMatchStats).filter_by(player_id=102, match_id=1).one().deaths = 4
    db.commit()
    card_points.rebuild_all(db)
    weeks = {w.id: w for w in db.query(Week).filter(Week.is_locked == True).all()}  # noqa: E712
    rostered = {(e.week_id, e.user_id, e.card_id) for e in db.query(WeeklyRosterEntry).all()}

    for week_id, user_id, card_id in rostered:
        old = _old_card_week_total(db, card_id, weeks[week_id])
        assert _roster_points(db, user_id, week_id)[card_id] == display_points(old)
    for week_id in weeks:
        old_users = {}
        for w, u, c in rostered:
            if w == week_id:
                old_users[u] = old_users.get(u, 0.0) + _old_card_week_total(db, c, weeks[week_id])
        new = _weekly_totals(db, week_id)
        assert new == {{1: "alice", 2: "bob"}[u]: display_points(v) for u, v in old_users.items()}
    old_season = {}
    for w, u, c in rostered:
        name = {1: "alice", 2: "bob"}[u]
        old_season[name] = old_season.get(name, 0.0) + _old_card_week_total(db, c, weeks[w])
    assert _season_totals(db) == {u: display_points(v) for u, v in old_season.items()}


def test_stored_totals_use_per_match_sums_when_death_floor_triggered(db):
    """Where one match's death term hits the floor, the card's week points equal the sum
    of per-match values and are >= the old aggregate value (never lower)."""
    _seed(db)
    week1 = db.get(Week, 1)
    stored = _stored(db)

    new = _roster_points(db, 1, 1)[2]
    old = _old_card_week_total(db, 2, week1)

    assert new == display_points(stored[(2, 1)] + stored[(2, 2)])
    assert new == display_points(_expected(db, 2, 1) + _expected(db, 2, 2))
    assert stored[(2, 1)] + stored[(2, 2)] > old
    for card_id in (1, 3, 4):
        # Exact stored week sums (the shown values are rounded to one decimal).
        exact = stored[(card_id, 1)] + stored[(card_id, 2)]
        assert exact >= _old_card_week_total(db, card_id, week1) - 1e-9
