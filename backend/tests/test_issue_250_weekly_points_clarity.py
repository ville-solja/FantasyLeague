"""Tests for plan-issue-250-weekly-points-clarity (GitHub issue #250).

Weekly-standings chips show how many games their points cover, the single-match
panel reads as "Best single games" with date and opponent per row, and admins get a
read-only points check (`GET /admin/points-check?week_id=…`) that compares stored
`card_match_points` rows with a fresh `card_points._compute` for that week's rostered
cards. No scoring change: formulas, weights, rounding and stored points stay as they are.

Developer notes (fixtures and helpers to reuse):
- `db` fixture from conftest; import `models` at module level so tables exist.
- Seeding: follow `_seed` in test_issue_141_stored_card_points.py (weights, users,
  players, teams, cards, weeks, `WeeklyRosterEntry`, matches, `PlayerMatchStats`), then
  `card_points.rebuild_all(db)` so stored rows exist. Give one card two or more games in
  the week and another card exactly one, so `games` differs per chip (`4 games` vs
  `1 game`). Compare totals with `display_points(exact_sum)`.
- Readers are called as plain functions: `routers.leaderboard.weekly_leaderboard(
  week_id=..., db=db)`, `routers.leaderboard.top_performances(db=db)` and
  `top_performance_rows(db, limit=..., match_ids=...)`.
- Twitch panel: reuse the `_seed_world` / `_viewer()` / `twitch.panel_live(payload=...,
  db=db)` pattern in test_issue_157_twitch_extension_policy_compliance.py (its
  `spy_top` signature `(db_, limit=10, match_ids=None)` must keep working).
- Points check: import inside each test (`import card_points` then
  `card_points.check_week(db, week_id)`), since the function does not exist yet.
  Expected return: `{"week", "cards", "games", "checked", "mismatches": [{user, player,
  card_type, match_id, stored, fresh, …}]}` (`checked`: card-game values compared); tolerance 0.05; a missing stored row is a mismatch with
  `stored` None. "Writes nothing": snapshot `card_match_points` rows (and
  `PlayerMatchStats.fantasy_points`) before and after, and/or count INSERT/UPDATE/DELETE
  statements with a `before_cursor_execute` listener on `db.get_bind()`
  (see test_issue_141's query-count test).
- Route: find it the way test_issue_141 checks `/recalculate`
  (`next(r for r in admin_ingest.router.routes if r.path == "/admin/points-check" and
  "GET" in r.methods)`) and assert `require_admin` is in
  `[d.call for d in route.dependant.dependencies]`; call the route function directly
  with `db=db` and an admin dict (`{"user_id": 1, "username": "admin", "is_admin": True}`)
  for the 404. A non-admin 403 can also be shown by calling `deps.require_admin` with a
  non-admin user row in `db` (it checks the database, not the dict).
  "Rate-limited like other admin reads" means the global default limit only; there is
  no per-route `@limiter.limit` on admin reads today.
- `routers/admin_ingest.py` is 345 lines and test_issue_85 caps admin routers at 350:
  keep the route a thin wrapper over `card_points.check_week`, or the full suite fails.
- Frontend checks are static reads of frontend/app-leaderboard.js, index.html and
  app-admin-ingest.js, plus a Node harness for `_lbStandingsRow` / `loadTop` rendering:
  reuse `_badges` / `_run_node` / `_globals_src` / `_fn_body` from
  test_issue_202_ui_feedback_polish.py (skip when node is missing). `loadTop` is async
  and uses `fetch`, `renderIfChanged`, `playerLink`, `_imgSrc`, `setStatus`: stub them
  in the harness (lessons-learned: `_fn_body` drops `async`).
- Existing pins that this change breaks and must be updated together:
  test_issue_149_points_rounding.py pins the old footnote "Totals are rounded from exact
  points, so card values may differ by 0.1 in sum" inside `_lbStandingsRow`'s
  `detailRow` and `lb.count(...) == 1` (the How to Play note keeps the old text);
  test_issue_202 pins chip markup (`<span class="lb-chip-rarity"`) and no inline styles
  in `_lbStandingsRow`. The current panel heading in index.html is "Single match
  performance" (`<tbody id="topBody">`).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

import card_points
import models  # noqa: F401  (registers tables for the db fixture)
from deps import require_admin
from models import (
    Card, CardMatchPoints, CardModifier, Match, Player, PlayerMatchStats, Team, User, Week,
    WeeklyRosterEntry,
)
from routers import admin_ingest
from routers.leaderboard import top_performance_rows, top_performances, weekly_leaderboard
from scoring import display_points
from tests.test_issue_141_stored_card_points import _add_weights, _expected
from tests.test_issue_151_weekly_report_aesthetics import _fn_body
from tests.test_issue_202_ui_feedback_polish import _badges, _f, _globals_src, _run_node

_ADMIN = {"user_id": 1, "username": "alice", "is_admin": True}

# (match_id, start_time, {player_id: (kills, deaths, gpm, is_mvp)})
# Week 1 = [0, 1000], Week 2 = [1001, 2000]. P101 plays for team 1, P102 for team 2.
_MATCHES = [
    (1, 100, {101: (5, 2, 437, True), 102: (3, 12, 391, False)}),
    (2, 200, {101: (2, 1, 403, False)}),
    (3, 1500, {101: (7, 4, 521, False), 102: (2, 2, 333, False), 103: (4, 1, 480, False)}),
]
_TEAM_OF = {101: 1, 102: 2, 103: 1}


def _seed(db):
    """alice (admin) rosters c1 common P101 (2 week-1 games) and c2 rare P102 (1 game);
    bob rosters c3 epic P101 (+10% kills, 2 games) and c4 common P103 (no week-1 games).
    carol owns c6 common P102 but has no week-1 roster. Week 2 roster: alice c1, carol c6."""
    _add_weights(db)
    db.add(User(id=1, username="alice", email="a@test", password_hash="x", is_admin=True))
    db.add(User(id=2, username="bob", email="b@test", password_hash="x"))
    db.add(User(id=3, username="carol", email="c@test", password_hash="x"))
    db.add(Team(id=1, name="Radiant Pros"))
    db.add(Team(id=2, name="Elisa Oyj"))
    for pid in (101, 102, 103):
        db.add(Player(id=pid, name=f"P{pid}"))
    db.add(Card(id=1, player_id=101, owner_id=1, card_type="common", is_active=True))
    db.add(Card(id=2, player_id=102, owner_id=1, card_type="rare", is_active=True))
    db.add(Card(id=3, player_id=101, owner_id=2, card_type="epic", is_active=True))
    db.add(Card(id=4, player_id=103, owner_id=2, card_type="common", is_active=True))
    db.add(Card(id=6, player_id=102, owner_id=3, card_type="common", is_active=True))
    db.add(CardModifier(card_id=3, stat_key="kills", bonus_pct=10.0))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=1000, is_locked=True))
    db.add(Week(id=2, label="Week 2", start_time=1001, end_time=2000, is_locked=True))
    for week_id, user_id, card_id in ((1, 1, 1), (1, 1, 2), (1, 2, 3), (1, 2, 4), (2, 1, 1), (2, 3, 6)):
        db.add(WeeklyRosterEntry(week_id=week_id, user_id=user_id, card_id=card_id))
    for match_id, start, players in _MATCHES:
        db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=2, start_time=start,
                     radiant_win=True, league_id=1))
        for pid, (kills, deaths, gpm, is_mvp) in players.items():
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=_TEAM_OF[pid],
                                    fantasy_points=float(10 * match_id + pid % 10), is_mvp=is_mvp,
                                    kills=kills, deaths=deaths, gold_per_min=gpm))
    db.commit()
    card_points.rebuild_all(db)


def _chips(db, week_id=1):
    return {c["card_id"]: c for r in weekly_leaderboard(week_id=week_id, db=db) for c in r["cards"]}


def _snapshot(db):
    cmp = sorted(db.execute(select(CardMatchPoints.card_id, CardMatchPoints.match_id,
                                   CardMatchPoints.points)).all())
    stats = sorted(db.execute(select(PlayerMatchStats.id, PlayerMatchStats.fantasy_points)).all())
    return cmp, stats


def _set_stored(db, card_id, match_id, points):
    row = db.query(CardMatchPoints).filter_by(card_id=card_id, match_id=match_id).one()
    row.points = points
    db.commit()


# ---------------------------------------------------------------------------
# Story: A Card's Week Points Say How Many Games They Cover
# ---------------------------------------------------------------------------

def test_weekly_leaderboard_chip_games_equals_games_in_week(db):
    """AC (API): GET /leaderboard/weekly returns `games` on each card chip, equal to the card's games in that week (the existing match_count)."""
    _seed(db)
    chips = _chips(db)
    assert {cid: c["games"] for cid, c in chips.items()} == {1: 2, 2: 1, 3: 2}
    assert all(isinstance(c["games"], int) for c in chips.values())
    # Week 2: P101 played once (match 3).
    assert _chips(db, 2)[1]["games"] == 1


def test_weekly_leaderboard_chip_points_and_totals_unchanged(db):
    """AC (API): adding `games` leaves each chip's points and each user's week_points unchanged (display_points of the exact sums)."""
    _seed(db)
    chips = _chips(db)
    exact = {1: _expected(db, 1, 1) + _expected(db, 1, 2), 2: _expected(db, 2, 1),
             3: _expected(db, 3, 1) + _expected(db, 3, 2)}
    for cid, total in exact.items():
        assert chips[cid]["points"] == display_points(total)
        assert set(chips[cid]) == {"card_id", "card_type", "player_name", "points", "games"}
    totals = {r["username"]: r["week_points"] for r in weekly_leaderboard(week_id=1, db=db)}
    assert totals["alice"] == display_points(exact[1] + exact[2])
    assert totals["bob"] == display_points(exact[3])


def test_weekly_leaderboard_card_without_games_not_shown(db):
    """AC (failure path): a rostered card with no games in the week gets no chip, as today, so no chip ever has games == 0."""
    _seed(db)
    chips = _chips(db)
    assert 4 not in chips
    assert all(c["games"] > 0 for c in chips.values())


def test_weekly_leaderboard_unknown_week_returns_404(db):
    """Failure path: GET /leaderboard/weekly for an unknown week still answers 404."""
    _seed(db)
    with pytest.raises(HTTPException) as exc:
        weekly_leaderboard(week_id=999, db=db)
    assert exc.value.status_code == 404


_CHIP_ROW = {"id": 7, "username": "alice", "is_admin": False, "week_points": 107.4, "tags": [],
             "cards": [{"card_type": "common", "player_name": "Glete", "points": 86.3, "games": 4},
                       {"card_type": "rare", "player_name": "<b>X</b>", "points": 21.1, "games": 1}]}


def test_lb_standings_row_chip_shows_points_and_game_count():
    """AC (count): `_lbStandingsRow` renders each chip as points followed by `· N games`, e.g. `86.3 · 4 games`, and `21.1 · 1 game` for a single game (Node harness)."""
    out = _badges(f"out.h = _lbStandingsRow({json.dumps(_CHIP_ROW)}, 0, 'week_points');")
    h = out["h"]
    assert '<span class="lb-chip-pts">86.3</span> <span class="lb-chip-games">· 4 games</span>' in h
    assert '<span class="lb-chip-pts">21.1</span> <span class="lb-chip-games">· 1 game</span>' in h
    assert "1 games" not in h


def test_lb_standings_row_chip_tooltip_spells_out_games():
    """AC (tooltip): the chip's title reads "<player> (<rarity>): <points> points from <N> games this week", with the player name escaped."""
    h = _badges(f"out.h = _lbStandingsRow({json.dumps(_CHIP_ROW)}, 0, 'week_points');")["h"]
    assert 'title="Glete (common): 86.3 points from 4 games this week"' in h
    assert 'title="&lt;b&gt;X&lt;/b&gt; (rare): 21.1 points from 1 game this week"' in h
    assert "<b>X</b>" not in h


_NEW_FOOTNOTE = "Card points are the week's total over every game the player played, rounded from exact points."


def test_lb_standings_row_detail_footnote_describes_week_total():
    """AC (footnote): the expanded row's note reads "Card points are the week's total over every game the player played, rounded from exact points." and appears once in app-leaderboard.js."""
    lb = _f("app-leaderboard.js")
    assert lb.count(_NEW_FOOTNOTE) == 1
    row = _fn_body(lb, "_lbStandingsRow")
    assert _NEW_FOOTNOTE in row[row.index("const detailRow"):]
    h = _badges(f"out.h = _lbStandingsRow({json.dumps(_CHIP_ROW)}, 0, 'week_points');")["h"]
    assert f'<div class="lb-rounding-note">{_NEW_FOOTNOTE}</div>' in h


def test_lb_standings_row_season_rows_show_no_game_count():
    """AC (failure path): season standings (showCards=false) render no chips, no game count and no footnote."""
    row = {**_CHIP_ROW, "season_points": 107.4}
    h = _badges(f"out.h = _lbStandingsRow({json.dumps(row)}, 0, 'season_points', false);")["h"]
    assert "lb-card-chip" not in h
    assert "game" not in h
    assert _NEW_FOOTNOTE not in h
    assert '_lbStandingsRow(r, i, "season_points", false)' in _f("app-leaderboard.js")


# ---------------------------------------------------------------------------
# Story: The Single-Game Panel Reads as Single Games
# ---------------------------------------------------------------------------

def test_top_performances_rows_include_match_id_start_time_and_opponent(db):
    """AC (API): each GET /top row adds match_id, start_time (from the match) and opponent (the other team's name)."""
    _seed(db)
    rows = top_performances(db=db)
    by_key = {(r["id"], r["match_id"]): r for r in rows}
    assert by_key[(101, 1)]["start_time"] == 100
    assert by_key[(101, 1)]["opponent"] == "Elisa Oyj"     # P101 on team 1 (radiant) faces team 2
    assert by_key[(102, 3)]["opponent"] == "Radiant Pros"  # P102 on team 2 (dire) faces team 1
    assert by_key[(102, 3)]["start_time"] == 1500
    for r in rows:
        assert {"id", "name", "avatar_url", "fantasy_points", "match_id", "start_time", "opponent"} <= set(r)


def test_top_performances_order_and_points_unchanged(db):
    """AC (API): GET /top keeps ORDER BY fantasy_points DESC, its limit, and display_points values unchanged."""
    _seed(db)
    rows = top_performances(db=db)
    stats = sorted(db.query(PlayerMatchStats).all(), key=lambda s: s.fantasy_points, reverse=True)
    assert [(r["id"], r["match_id"]) for r in rows] == [(s.player_id, s.match_id) for s in stats]
    assert [r["fantasy_points"] for r in rows] == [display_points(s.fantasy_points) for s in stats]
    assert len(top_performance_rows(db, limit=2)) == 2
    assert [r["match_id"] for r in top_performance_rows(db, match_ids=[1])] == [1, 1]


def test_top_performances_unknown_opponent_team_returns_null_opponent(db):
    """AC (failure path): when the stat row's team or the other side's team is unknown (null id or missing teams row), opponent is null and the row is still returned."""
    db.add(Player(id=201, name="NoTeam"))
    db.add(Player(id=202, name="GhostOpp"))
    db.add(Team(id=1, name="Radiant Pros"))
    db.add(Match(match_id=10, radiant_team_id=1, dire_team_id=99, start_time=500))  # team 99 missing
    db.add(Match(match_id=11, radiant_team_id=None, dire_team_id=None, start_time=600))
    db.add(PlayerMatchStats(player_id=202, match_id=10, team_id=1, fantasy_points=20.0))
    db.add(PlayerMatchStats(player_id=201, match_id=11, team_id=None, fantasy_points=10.0))
    db.commit()
    rows = top_performances(db=db)
    assert [(r["id"], r["opponent"]) for r in rows] == [(202, None), (201, None)]
    assert rows[1]["start_time"] == 600


def test_top_performance_rows_twitch_panel_still_works(db, monkeypatch):
    """AC (API): the Twitch panel (`twitch.panel_live`), which calls top_performance_rows with match_ids, still returns its public rows and ignores the extra keys."""
    import schedule
    import twitch
    from routers import leaderboard
    _seed(db)
    calls = []
    real_top = leaderboard.top_performance_rows

    def spy_top(db_, limit=10, match_ids=None):
        calls.append((limit, match_ids))
        return real_top(db_, limit=limit, match_ids=match_ids)

    monkeypatch.setattr(leaderboard, "top_performance_rows", spy_top)
    monkeypatch.setattr(schedule, "next_scheduled_match", lambda db_: None)
    data = twitch.panel_live(payload={"channel_id": "1", "role": "viewer", "opaque_user_id": "A1"}, db=db)
    assert calls and calls[0][1]
    assert data["top_performers"]
    for row in data["top_performers"]:
        assert set(row) == {"player_id", "player_name", "fantasy_points"}


def test_top_performance_rows_empty_match_ids_returns_empty(db):
    """Failure path: top_performance_rows(db, match_ids=[]) still returns [] after the join changes."""
    _seed(db)
    assert top_performance_rows(db, match_ids=[]) == []


def _top_panel_html():
    html = _f("index.html")
    end = html.index('<tbody id="topBody">')
    start = html.rindex('<div class="panel">', 0, end)
    return html[start:end]


def test_index_html_single_game_panel_heading_and_subline():
    """AC (heading): the panel holding #topBody is headed "Best single games" with the sub-line "One game each, this season"; "Single match performance" is gone."""
    panel = _top_panel_html()
    assert "<h2>Best single games</h2>" in panel
    assert '<p class="panel-subline">One game each, this season</p>' in panel
    assert "Single match performance" not in _f("index.html")


def _load_top(rows):
    lb = _f("app-leaderboard.js")
    script = (_globals_src("_escHtml")
              + "\nvar API = '';\nvar out = {};\n"
              + "var _els = {};\n"
              + "var document = { getElementById: id => (_els[id] = _els[id] || {id}) };\n"
              + "function renderIfChanged(el, html) { out.html = html; return true; }\n"
              + "function setStatus(id, msg, ok) { out.status = [id, msg, ok]; }\n"
              + "function playerLink(id, name) { return '<a>' + _escHtml(name) + '</a>'; }\n"
              + "function _imgSrc(u) { return u || ''; }\n"
              + f"async function fetch(url) {{ out.url = url; return {{ ok: true, json: async () => ({json.dumps(rows)}) }}; }}\n"
              + "async " + _fn_body(lb, "loadTop") + "\n}\n"
              + "loadTop().then(() => console.log(JSON.stringify(out)));")
    return _run_node(script)


_NOV_14_2025_NOON_UTC = 1763121600


def test_load_top_renders_date_and_opponent():
    """AC (rows): loadTop renders rank, player, the date as `14.11.` and "vs <opponent>", and the points (Node harness with stubbed fetch)."""
    out = _load_top([{"id": 5, "name": "tanelidota:)", "avatar_url": None, "fantasy_points": 48.24,
                      "match_id": 77, "start_time": _NOV_14_2025_NOON_UTC, "opponent": "Elisa Oyj"}])
    h = out["html"]
    assert out["url"] == "/top"
    assert "<td>1</td>" in h
    assert "<a>tanelidota:)</a>" in h
    assert '<div class="top-game-meta">14.11. vs Elisa Oyj</div>' in h
    assert "<td>48.2</td>" in h


def test_load_top_escapes_opponent_name():
    """AC (failure path): an opponent name containing markup is escaped by loadTop, and a null opponent renders no "vs" text."""
    out = _load_top([
        {"id": 5, "name": "A", "avatar_url": None, "fantasy_points": 30.0, "match_id": 1,
         "start_time": _NOV_14_2025_NOON_UTC, "opponent": "<img src=x onerror=alert(1)>"},
        {"id": 6, "name": "B", "avatar_url": None, "fantasy_points": 20.0, "match_id": 2,
         "start_time": _NOV_14_2025_NOON_UTC, "opponent": None},
    ])
    h = out["html"]
    assert "<img src=x" not in h
    assert "vs &lt;img src=x onerror=alert(1)&gt;" in h
    assert h.count("vs ") == 1
    assert '<div class="top-game-meta">14.11.</div>' in h


# ---------------------------------------------------------------------------
# Story: An Admin Can Check That Stored Points Add Up
# ---------------------------------------------------------------------------

def test_check_week_all_match_after_refresh(db):
    """AC (result): after rebuild_all, card_points.check_week returns the week, the counts of rostered cards and games checked, and no mismatches."""
    _seed(db)
    result = card_points.check_week(db, 1)
    assert result["week"] == {"id": 1, "label": "Week 1"}
    assert result["cards"] == 4          # c1, c2, c3, c4 on week-1 rosters
    assert result["games"] == 2          # matches 1 and 2
    assert result["checked"] == 5        # c1×2, c2×1, c3×2
    assert result["mismatches"] == []


def test_check_week_reports_edited_stored_value(db):
    """AC (result): a card_match_points value edited by more than 0.05 is reported with user, player, card_type, match_id, stored and fresh values."""
    _seed(db)
    fresh = _expected(db, 3, 2)
    _set_stored(db, 3, 2, fresh + 1.0)
    result = card_points.check_week(db, 1)
    assert len(result["mismatches"]) == 1
    m = result["mismatches"][0]
    assert {k: m[k] for k in ("user", "player", "card_type", "match_id")} == {
        "user": "bob", "player": "P101", "card_type": "epic", "match_id": 2}
    assert m["stored"] == pytest.approx(round(fresh + 1.0, 2))
    assert m["fresh"] == pytest.approx(round(fresh, 2))


def test_check_week_ignores_difference_within_tolerance(db):
    """AC (result): a stored value within 0.05 of the fresh calculation is not reported."""
    _seed(db)
    _set_stored(db, 1, 1, _expected(db, 1, 1) + 0.04)
    _set_stored(db, 2, 1, _expected(db, 2, 1) - 0.04)
    assert card_points.check_week(db, 1)["mismatches"] == []
    _set_stored(db, 1, 1, _expected(db, 1, 1) + 0.06)
    assert [m["match_id"] for m in card_points.check_week(db, 1)["mismatches"]] == [1]


def test_check_week_reports_missing_stored_row(db):
    """AC (result): a rostered card's game with no card_match_points row is a mismatch with stored None."""
    _seed(db)
    db.query(CardMatchPoints).filter_by(card_id=2, match_id=1).delete()
    db.commit()
    result = card_points.check_week(db, 1)
    assert len(result["mismatches"]) == 1
    m = result["mismatches"][0]
    assert (m["user"], m["card_type"], m["match_id"], m["stored"]) == ("alice", "rare", 1, None)
    assert m["fresh"] == pytest.approx(round(_expected(db, 2, 1), 2))


def test_check_week_writes_nothing(db):
    """AC (writes nothing): check_week with mismatches present leaves card_match_points and player stats unchanged and issues no INSERT/UPDATE/DELETE."""
    _seed(db)
    _set_stored(db, 1, 2, 999.0)
    db.query(CardMatchPoints).filter_by(card_id=3, match_id=1).delete()
    db.commit()
    before = _snapshot(db)
    statements = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        result = card_points.check_week(db, 1)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    assert len(result["mismatches"]) == 2
    assert statements and not {"INSERT", "UPDATE", "DELETE"} & set(statements)
    db.rollback()
    assert _snapshot(db) == before


def test_check_week_only_checks_that_weeks_rostered_cards(db):
    """AC (bounded): cards not on the week's rosters, and games outside the week, are neither counted nor reported, even when their stored values are wrong."""
    _seed(db)
    _set_stored(db, 6, 1, 500.0)   # carol's c6 is not on a week-1 roster
    _set_stored(db, 1, 3, 500.0)   # match 3 is in week 2
    result = card_points.check_week(db, 1)
    assert result["mismatches"] == []
    assert result["cards"] == 4 and result["games"] == 2
    week2 = card_points.check_week(db, 2)
    assert {(m["card_id"], m["match_id"]) for m in week2["mismatches"]} == {(1, 3)}
    assert week2["cards"] == 2 and week2["games"] == 1


def _route():
    return next(r for r in admin_ingest.router.routes
                if r.path == "/admin/points-check" and "GET" in r.methods)


def test_points_check_route_returns_check_week_result(db):
    """AC (run): GET /admin/points-check?week_id=… exists in routers/admin_ingest.py and returns check_week's result for an admin."""
    _seed(db)
    route = _route()
    assert route.endpoint(week_id=1, db=db, _=_ADMIN) == card_points.check_week(db, 1)


def test_points_check_unknown_week_returns_404(db):
    """AC (bounded, failure path): an unknown week_id returns 404."""
    _seed(db)
    with pytest.raises(HTTPException) as exc:
        _route().endpoint(week_id=999, db=db, _=_ADMIN)
    assert exc.value.status_code == 404


def test_points_check_week_id_is_bounded():
    """Security review (Low): week_id is bounded to 1..2**63-1, so an out-of-range value
    is a 422 from validation, never an OverflowError (500) in the database layer."""
    params = {p.name: p for p in _route().dependant.query_params}
    meta = {type(m).__name__: m for m in params["week_id"].field_info.metadata}
    assert meta["Ge"].ge == 1 and meta["Le"].le == 2**63 - 1


def test_points_check_non_admin_returns_403(db):
    """AC (admin only, failure path): the route depends on require_admin, and a non-admin gets 403."""
    _seed(db)
    assert require_admin in [d.call for d in _route().dependant.dependencies]
    with pytest.raises(HTTPException) as exc:
        require_admin(current_user={"user_id": 2, "username": "bob", "is_admin": True}, db=db)
    assert exc.value.status_code == 403


def test_admin_settings_scoring_has_check_points_controls():
    """AC (run): Admin › Settings › Scoring in index.html has a Check points button and a week picker; app-admin-ingest.js calls `/admin/points-check?week_id=` and defaults to the latest locked week."""
    html = _f("index.html")
    start = html.index('id="settings-section-scoring"')
    scoring = html[start:html.index("</section>", start)]
    assert '<select id="pointsCheckWeekSelect"' in scoring
    assert 'onclick="checkPoints()">Check points</button>' in scoring
    js = _f("app-admin-ingest.js")
    assert "/admin/points-check?week_id=${weekId}" in _fn_body(js, "checkPoints")
    loader = _fn_body(js, "loadPointsCheckWeeks")
    assert "weeks.filter(w => w.is_locked)" in loader
    assert "locked[locked.length - 1].id" in loader
    assert "loadPointsCheckWeeks();" in _f("app-globals.js")


def _render_check(data):
    js = _f("app-admin-ingest.js")
    script = (_globals_src("_escHtml")
              + "\nvar out = {};\nvar _els = {};\n"
              + "var document = { getElementById: id => (_els[id] = _els[id] || {id, innerHTML: ''}) };\n"
              + "function setStatus(id, msg, ok) { out.status = [id, msg, ok]; }\n"
              + _fn_body(js, "_pointsCheckValue") + "\n}\n"
              + _fn_body(js, "_renderPointsCheck") + "\n}\n"
              + f"_renderPointsCheck({json.dumps(data)});\n"
              + "out.html = _els.pointsCheckResult.innerHTML;\n"
              + "console.log(JSON.stringify(out));")
    return _run_node(script)


def test_admin_check_points_result_messages():
    """AC (result): app-admin-ingest.js shows "All N card points match" when there are no mismatches, otherwise a table of mismatches and a pointer to Recalculate Fantasy Points; mismatch names are escaped."""
    base = {"week": {"id": 1, "label": "Week 1"}, "cards": 4, "games": 2, "checked": 5}
    ok = _render_check({**base, "mismatches": []})
    assert ok["status"][0] == "pointsCheckStatus" and ok["status"][2] is True
    assert ok["status"][1].startswith("All 5 card points match.")
    assert ok["html"] == ""
    bad = _render_check({**base, "mismatches": [
        {"user_id": 2, "user": "<b>bob</b>", "card_id": 3, "player": "P<101>", "card_type": "epic",
         "match_id": 2, "stored": 12.5, "fresh": 11.0},
        {"user_id": 1, "user": "alice", "card_id": 2, "player": "P102", "card_type": "rare",
         "match_id": 1, "stored": None, "fresh": 9.1}]})
    assert bad["status"][2] is False
    assert "Recalculate Fantasy Points" in bad["status"][1]
    h = bad["html"]
    assert "<b>bob</b>" not in h and "&lt;b&gt;bob&lt;/b&gt;" in h
    assert "P&lt;101&gt; (epic)" in h
    assert "<td>12.5</td>" in h and "<td>11</td>" in h
    assert "<td>—</td>" in h and "<td>9.1</td>" in h
