"""
Tests for plan-issue-244-schedule-player-performance.md (resolves GitHub issue #244).

Each game row of an unfolded Schedule series gets a **Players** toggle that loads
that game's player table on demand from a new public endpoint,
`GET /matches/{match_id}/players`. The table's metric is the player's **raw
points**: `fantasy_score` of the player's own stats with the current weights,
before card rarity, card modifiers and the MVP bonus. Hidden results (hide mode)
get no button and load no player data. One class per user story, one stub per
acceptance criterion plus the primary failure path.

Developer notes
---------------

  Existing code these tests target
    - backend/scoring.py: `fantasy_score(p, weights)` (no rarity, no modifiers,
      no MVP bonus; the death pool is `weights["death_pool"]` minus
      `death_deduction` per death, floored at 0), `stat_dict_from_row(row)` (ORM
      object or Core Row; missing / NULL stats become 0, so an unparsed replay's
      wards, stuns, teamfight, runes and camps simply contribute 0, the same as
      the player popup), `display_points(x)` (one-decimal half-up rounding, use
      it exactly once on the exact raw value), `apply_mvp_bonus_to_row`
      (weight key `mvp_bonus_pct`, default 10).
    - `player_match_stats.fantasy_points` ALREADY includes the MVP bonus
      (`apply_mvp_bonus_to_row`, `/recalculate` in routers/admin_ingest.py).
      Raw points must be recomputed from the row's stats, never read from
      `fantasy_points`. This matches the Weekly Report's RAW chip
      (`card_utils.card_points_breakdown(...)["raw"]`).
    - Weights: `card_points._current_weights(db)` (wraps
      `card_utils._load_weights`) is the existing loader; the plan's
      `{w.key: w.value for w in db.query(Weight)}` works too. Weights only
      change at startup (seed.py applies WEIGHTS_JSON; there is no weights
      write route), followed by `POST /recalculate`, which does NOT call
      `schedule.bust_cache()`. A per-match cache is therefore safe across a
      weight change only because a restart empties it; if the cache key does
      not include the weights, say so in the feature doc.
    - backend/schedule.py: `_build_games(db, match_ids, team1_id, team2_id)`
      (per-game payload: heroes, kills, MVP, `excluded_from_scoring`; note it
      calls `_fetch_hero_icon_map()`, which CAN hit OpenDota; the new
      `game_players` must use `cached_hero_maps()` instead, which never
      fetches and returns `({}, {})` on a cold cache while starting
      `warm_hero_maps_in_background()`), `_cache` and `bust_cache()` (clears
      `_cache["data"]` / `["fetched_at"]` only; extend it to clear the new
      per-match dict). `bust_cache` is already called by ingest
      (`ingest.py` after storing a match), the Twitch MVP confirm
      (`twitch.py`), and routers/admin_matches.py (admin MVP, retry-parse,
      scoring toggle).
    - backend/models.py: `Match` (`radiant_team_id`, `dire_team_id`,
      `parse_status` 'parsed' | 'unparsed' | 'unparseable' | NULL,
      `excluded_from_scoring`), `PlayerMatchStats` (`team_id`, `hero_id`,
      `kills`, `deaths`, `assists`, `is_mvp`, `fantasy_points`), `Player`
      (`name`), `Team` (`name`). No new column, no migration.
    - backend/routers/players.py: public router (`list_players`,
      `/players/{player_id}`, `/teams/...`). It imports `APIRouter, Depends,
      HTTPException` from fastapi but not `Path`; add it. Bound the id with
      `Path(ge=1, le=2**63 - 1)` so an oversized id answers 422, not an
      `OverflowError` 500 (lessons-learned 2026-10-14). No `/matches/...`
      public route exists today; the only `/matches/{match_id}/players` is
      `GET /admin/matches/{match_id}/players` in routers/admin_matches.py
      (admin-only, different prefix, so no clash).
    - Plan claim to correct: `GET /schedule` is NOT in routers/players.py; it
      is `schedule_endpoint` in routers/admin_ingest.py (public, no auth
      dependency). Putting the new route in players.py is still fine.
    - frontend/app-players.js (inside `loadSchedule`): `gameRowsHtml(games)`
      builds `<div class="series-games">` with one `<div class="game-row">` per
      game; `hiddenRow(s, key, meta)` builds the hidden row; `seriesRow`
      chooses between them; module state `_schedOpenGames` (Set of series keys),
      `_schedKeyById` / `_schedKeyId(key)` (hashed DOM ids),
      `toggleScheduleGames`, `revealScheduleSeries`, `revealScheduleWeek`,
      `hideScheduleWeekAgain` -> `_schedUnreveal` -> `_schedRerender()`,
      `showScheduleLatestGames` (Latest result card's Games button),
      `_NOT_SCORED_TOOLTIP`. `playerLink(id, name)` and `_escHtml` are in
      app-globals.js.
    - The "Partial stats" badge exists only in the player popup today
      (frontend/app-player-popup.js: `_PARTIAL_STATS_TOOLTIP`,
      `_popupIsPartial(m)`), not on the Schedule. app-player-popup.js loads
      AFTER app-players.js, and the schedule Node harness loads only
      app-globals helpers plus app-players.js, so referencing
      `_PARTIAL_STATS_TOOLTIP` from the schedule code throws a ReferenceError
      in the harness. Move the constant (and ideally `_popupIsPartial`) to
      app-players.js next to `_NOT_SCORED_TOOLTIP` (no test pins its location).

  Reusable helpers / fixtures (all exist today)
    - From test_issue_211_team_view_enhancements.py: `_client(db)` (FastAPI app
      around `routers.players.router` with `get_db` overridden), `_weights(db,
      **over)` (seeds `seed.DEFAULT_WEIGHTS`), `_seed_teams(db)` (teams 1
      "Reds", 2 "Blues"), `_match(db, mid, radiant=1, dire=2, excluded=False,
      parse="parsed", ...)`, `_stat(db, pid, mid, team=1, mvp=False, hero=None,
      **over)` (adds the player and a stats row whose `fantasy_points` follow
      the formula, MVP bonus included; returns that value), `_STATS`. Its own
      `db` fixture (StaticPool) and autouse `_no_network` are NOT imported here:
      this module defines its own of each so they are active.
    - From test_issue_234_mvp_poll_for_watchers.py: `_seed_ten(db, match_id)`
      (teams 11 vs 12, ten players, flat stats: use it only where the values
      don't matter).
    - From test_issue_156_schedule_visuals.py (Node harness): `_HARNESS`,
      `_run_schedule(steps, data=None, ...)`, `_scenario()` (series Alpha-Bravo
      week 1 games 101/102 with MVP "StarGuy" on 101; Charlie-Delta week 2
      games 201/202(excluded)/203; Golf-Hotel extra result game 50), `_game`,
      `_row(html, team1, team2)`, `_now_card(html, kind)`, `_js`,
      `_load_schedule`, `_nested(body, name)`, `_css`, `_rule(css, selector)`,
      `_globals_helpers`, `_NOW`. `_HARNESS`'s `fetch` throws on any URL other
      than `/schedule` and `/weekly-summary`: build a local variant by
      replacing its `throw new Error("unexpected fetch " + url);` line with a
      branch that serves `/matches/<id>/players` from a JSON map (and records
      the call in `fetchLog`), then format it like `_run_schedule` does.
      `toggleScheduleHide()` turns hide mode off in that harness's steps
      (results start hidden). `_node` comes from
      test_issue_159_flicker_free_tab_switching.py.
    - From test_issue_151_weekly_report_aesthetics.py: `_fn_body`, `_css_blocks`,
      `_media_body` (CSS media-query bodies, for the < 480 px rule).

  Imports
    - `import models` stays at module level so the db fixture creates every
      table. Import `schedule.game_players` and anything else the plan adds
      INSIDE each test.

  Pitfalls
    - Keep the table state in module state (a Set of open match ids plus a
      Map of fetched responses) and render it from `gameRowsHtml`: every
      handler re-renders through `_schedRerender()` / `renderIfChanged`, so a
      table inserted straight into the DOM disappears on the next quiet
      refresh, and the harness's `document.querySelectorAll` returns [].
    - Older tests parse the game-row markup with regexes:
      test_issue_156 `re.findall(r'<div class="game-row">(.*?)</div>')` and
      `row.count('class="game-row"') == 3`, and test_mvp_visibility
      `<span class="game-row-meta">(.*?)<span class="game-row-duration">`
      (MVP link first in the meta cell). Do not put a `<div>` inside
      `.game-row`, put the Players button after `.game-row-duration`, and
      render the table container as a sibling AFTER the game row's closing
      `</div>` with a class that is not exactly `game-row`.
    - Hide week again: the re-render already swaps hidden rows to `hiddenRow`,
      but the open-table state must also be cleared for that week's matches,
      or a later Reveal reopens them.
    - Group by `player_match_stats.team_id` and name teams from `teams`; a
      match's radiant/dire ids can be NULL (manual matches): fall back to
      the order the team ids appear.
    - Never parse HTML with regexes in new tests where a real parse is needed
      (use html.parser); assert URLs with exact equality.
    - New CSS goes before the `GUIDED TOUR (issue #144)` block. If the table
      container is hidden with the `hidden` attribute, add
      `.cls[hidden] { display: none; }`.

  Ambiguity to settle in review
    - "A match with no stats returns empty teams" (Step 5) vs. the endpoint
      shape "`teams`: two entries". The stub below pins only that no player is
      returned; pick one and pin it.
"""

import pytest

# Registers every existing table on Base before the db fixture runs create_all.
import models  # noqa: F401


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No OpenDota hero maps and an empty schedule cache before and after each test."""
    import schedule
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", lambda: None)
    monkeypatch.setattr(schedule, "_hero_icon_cache", None)
    monkeypatch.setattr(schedule, "_hero_name_cache", {})
    schedule.bust_cache()
    yield
    schedule.bust_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import json
import os
import subprocess
from html.parser import HTMLParser

from tests.test_issue_151_weekly_report_aesthetics import _media_body
from tests.test_issue_156_schedule_visuals import (
    _HARNESS, _NOW, _css, _globals_helpers, _js, _load_schedule, _nested, _now_card, _row, _rule,
    _scenario,
)
from tests.test_issue_159_flicker_free_tab_switching import _node
from tests.test_issue_211_team_view_enhancements import _client, _match, _seed_teams, _stat, _weights

_PLAYER_KEYS = {"player_id", "player_name", "hero_id", "hero_icon", "kills", "deaths", "assists",
                "raw_points", "is_mvp", "top"}
_PARTIAL_TIP = "The replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0."
_NOT_SCORED_TIP = "An admin excluded this match from scoring. It adds no fantasy points."
_NOTE = "Raw points: from the player's own stats, before card rarity, modifiers and the MVP bonus."
_EVIL = "<img src=x onerror=alert(1)>"


def _seed_game(db, mid=900, **match_kw):
    """Teams 1 (radiant) and 2 (dire), five players each with distinct stats; the
    player with the most kills on team 1 is the MVP. Returns the player ids."""
    if not db.query(models.Weight).count():
        _weights(db)
    if db.get(models.Team, 1) is None:
        _seed_teams(db)
    _match(db, mid, **match_kw)
    pids = []
    for i in range(10):
        pid = mid * 100 + i
        _stat(db, pid, mid, team=1 if i < 5 else 2, mvp=(i == 4), hero=i + 1,
              kills=i, deaths=10 - i, assists=2 * i + 1, last_hits=40 + 7 * i)
        pids.append(pid)
    return pids


def _expected_raw(db, mid):
    from scoring import display_points, fantasy_score, stat_dict_from_row
    weights = {w.key: w.value for w in db.query(models.Weight)}
    return {r.player_id: display_points(fantasy_score(stat_dict_from_row(r), weights))
            for r in db.query(models.PlayerMatchStats).filter_by(match_id=mid)}


def _players(data):
    return [p for t in data["teams"] for p in t["players"]]


def _p(pid, name, raw, top=False, mvp=False, icon="https://cdn.example/h.png", k=3, d=2, a=7):
    return {"player_id": pid, "player_name": name, "hero_id": 1, "hero_icon": icon,
            "kills": k, "deaths": d, "assists": a, "raw_points": raw, "is_mvp": mvp, "top": top}


def _resp(mid=201, parse="parsed", excluded=False, teams=None):
    if teams is None:
        teams = [
            {"team_id": 3, "team_name": "Charlie", "players": [
                _p(31, "Ann", 12.3, top=True), _p(32, "Bob", 5, mvp=True)]},
            {"team_id": 4, "team_name": "Delta", "players": [
                _p(41, "Cid", 12.3, top=True), _p(42, "Dee", 1.2, icon=None)]},
        ]
    return {"match_id": mid, "parse_status": parse, "excluded_from_scoring": excluded, "teams": teams}


_FETCH_LINE = 'throw new Error("unexpected fetch " + url);'
_PLAYERS_FETCH = r"""const m = /^\/matches\/(\d+)\/players$/.exec(url);
  if (m && PLAYERS[m[1]]) return { ok: true, json: async () => JSON.parse(JSON.stringify(PLAYERS[m[1]])) };
  if (m) return { ok: false, status: 404, json: async () => ({ detail: "Match not found" }) };
  """ + _FETCH_LINE


def _run(steps, players=None, data=None):
    """`_run_schedule` with `/matches/<id>/players` served from `players` ({id: body})."""
    node = _node()
    if not node:
        pytest.skip("node not available")
    assert _FETCH_LINE in _HARNESS
    harness = _HARNESS.replace(_FETCH_LINE, _PLAYERS_FETCH).replace(
        "const fetchLog = [];", "const fetchLog = [];\nconst PLAYERS = %(players_map)s;")
    if players is None:
        players = {201: _resp(201), 202: _resp(202), 203: _resp(203)}
    script = harness % {
        "now": _NOW,
        "data": json.dumps(data if data is not None else _scenario()),
        "summary": json.dumps({"weeks": []}),
        "storage": json.dumps("ok"),
        "store": json.dumps({}),
        "username": json.dumps(None),
        "globals": _globals_helpers(),
        "players": _js(),
        "players_map": json.dumps({str(k): v for k, v in players.items()}),
        "steps": steps,
    }
    env = dict(os.environ, TZ="Europe/Helsinki")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, env=env)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout)


def _player_fetches(fetches):
    return [u for u, _m in fetches if u.startswith("/matches/")]


class _Tags(HTMLParser):
    """Start tags as (tag, attrs dict), and text per element class."""

    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def _parse(html):
    p = _Tags()
    p.feed(html)
    return p


def _classes(attrs):
    return (attrs.get("class") or "").split()


def _buttons(html):
    return [a for t, a in _parse(html).tags if t == "button" and "game-players-btn" in _classes(a)]


def _table(html, mid):
    """Markup of game `mid`'s player container, or None."""
    marker = f'<div class="game-players" id="game-players-{mid}">'
    if marker not in html:
        return None
    start = html.index(marker)
    depth, i = 0, start
    while True:
        opening, closing = html.find("<div", i), html.find("</div>", i)
        if opening != -1 and opening < closing:
            depth, i = depth + 1, opening + 4
        else:
            depth, i = depth - 1, closing + 6
            if depth == 0:
                return html[start:i]


def _shown_open(steps_after=""):
    return """
  await loadSchedule();
  toggleScheduleHide();
  toggleScheduleGames(id("201,202,203"));
""" + steps_after


# ---------------------------------------------------------------------------
# Story 1: See How Each Player Performed in a Game
# ---------------------------------------------------------------------------

class TestSeeHowEachPlayerPerformed:

    def test_game_players_raw_points_equal_fantasy_score_of_row_stats(self, db):
        """`schedule.game_players(db, match_id)` gives each player `raw_points ==
        display_points(fantasy_score(stat_dict_from_row(row), weights))` with the
        seeded weights, for ten players with distinct stats."""
        from schedule import game_players
        pids = _seed_game(db)
        expected = _expected_raw(db, 900)
        assert len(set(expected.values())) == 10
        got = {p["player_id"]: p["raw_points"] for p in _players(game_players(db, 900))}
        assert set(got) == set(pids)
        assert got == expected

    def test_game_players_raw_points_leave_out_mvp_bonus(self, db):
        """For the MVP row (is_mvp=True, `fantasy_points` includes the
        `mvp_bonus_pct` bonus), `raw_points` equals the bonus-free
        `display_points(fantasy_score(...))` and is lower than
        `display_points(row.fantasy_points)`; `is_mvp` is True for that player only."""
        from schedule import game_players
        from scoring import display_points
        pids = _seed_game(db)
        mvp_pid = pids[4]
        row = db.query(models.PlayerMatchStats).filter_by(match_id=900, player_id=mvp_pid).one()
        lines = {p["player_id"]: p for p in _players(game_players(db, 900))}
        assert lines[mvp_pid]["raw_points"] == _expected_raw(db, 900)[mvp_pid]
        assert lines[mvp_pid]["raw_points"] < display_points(row.fantasy_points)
        assert [pid for pid, p in lines.items() if p["is_mvp"]] == [mvp_pid]

    def test_game_players_groups_by_team_radiant_then_dire_sorted_by_raw_desc(self, db):
        """`teams` has two entries in radiant, dire order, each with `team_id` and
        `team_name` from `teams`, and each team's `players` sorted by `raw_points`
        descending; every player carries `player_id`, `player_name`, `hero_id`,
        `hero_icon`, `kills`, `deaths`, `assists`, `raw_points`, `is_mvp`, `top`."""
        from schedule import game_players
        _seed_game(db, radiant=2, dire=1)
        data = game_players(db, 900)
        assert [(t["team_id"], t["team_name"]) for t in data["teams"]] == [(2, "Blues"), (1, "Reds")]
        for t in data["teams"]:
            pts = [p["raw_points"] for p in t["players"]]
            assert len(pts) == 5 and pts == sorted(pts, reverse=True)
            for p in t["players"]:
                assert set(p) == _PLAYER_KEYS
        assert {p["player_id"] for p in data["teams"][0]["players"]} == {90005, 90006, 90007, 90008, 90009}

    def test_game_players_marks_highest_raw_score_top_including_ties(self, db):
        """`top` is True for the player(s) with the game's highest exact raw score
        across both teams; two players tied on the highest score are both `top`, and
        every other player is `top: False`."""
        from schedule import game_players
        _weights(db)
        _seed_teams(db)
        _match(db, 901)
        _stat(db, 1, 901, team=1, kills=20)
        _stat(db, 2, 901, team=2, kills=20)
        _stat(db, 3, 901, team=1, kills=2)
        _stat(db, 4, 901, team=2, kills=1)
        tops = {p["player_id"]: p["top"] for p in _players(game_players(db, 901))}
        assert tops == {1: True, 2: True, 3: False, 4: False}
        _match(db, 902)
        _stat(db, 5, 902, team=1, kills=9)
        _stat(db, 6, 902, team=2, kills=8)
        tops = {p["player_id"]: p["top"] for p in _players(game_players(db, 902))}
        assert tops == {5: True, 6: False}

    def test_game_players_uses_current_weights(self, db):
        """After the `kills` Weight row changes (and `schedule.bust_cache()`), the
        same match's `raw_points` follow the new weight, not the stored
        `fantasy_points`."""
        import schedule
        _seed_game(db)
        before = {p["player_id"]: p["raw_points"] for p in _players(schedule.game_players(db, 900))}
        w = db.query(models.Weight).filter_by(key="kills").one()
        w.value = w.value + 5
        db.commit()
        schedule.bust_cache()
        after = {p["player_id"]: p["raw_points"] for p in _players(schedule.game_players(db, 900))}
        assert after == _expected_raw(db, 900)
        assert after != before
        stored = {r.player_id: r.fantasy_points for r in db.query(models.PlayerMatchStats).filter_by(match_id=900)}
        pid = 90009  # 9 kills
        assert after[pid] > before[pid] and after[pid] != stored[pid]

    def test_game_players_hero_icon_from_cached_hero_maps_without_network(self, db, monkeypatch):
        """`hero_icon` comes from `schedule.cached_hero_maps()` (patched hero cache
        `{hero_id: url}` gives that url); with a cold cache it is None and
        `_fetch_hero_icon_map` is never called (patch it to raise)."""
        import schedule

        def _boom():
            raise AssertionError("network")
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", _boom)
        _seed_game(db)
        cold = _players(schedule.game_players(db, 900))
        assert all(p["hero_icon"] is None for p in cold)
        url = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/heroes/axe.png"
        monkeypatch.setattr(schedule, "_hero_icon_cache", {3: url})
        schedule.bust_cache()
        warm = {p["hero_id"]: p["hero_icon"] for p in _players(schedule.game_players(db, 900))}
        assert warm[3] == url
        assert all(v is None for k, v in warm.items() if k != 3)

    def test_schedule_game_row_has_players_toggle_with_aria(self):
        """Node harness: in an unfolded shown series every `.game-row` holds a
        Players button with `aria-expanded="false"` and an `aria-controls` that
        names that game's table container; the MVP link stays the first child of
        `.game-row-meta` and the button sits after `.game-row-duration`."""
        out = _run(_shown_open("  out.s = snap();\n"))
        content = out["s"]["content"]
        btns = _buttons(content)
        assert [b["aria-controls"] for b in btns] == ["game-players-201", "game-players-202", "game-players-203"]
        assert all(b["aria-expanded"] == "false" for b in btns)
        chunks = content.split('<div class="game-row">')[1:]
        assert len(chunks) == 3
        for n, chunk in enumerate(chunks):
            meta = chunk[chunk.index('class="game-row-meta"'):]
            assert meta.index('class="game-row-duration"') < meta.index("game-players-btn") < meta.index("opendota.com")
            if n == 0:
                assert meta.index("entity-link") < meta.index('class="game-row-duration"')
        assert _player_fetches(out["s"]["fetches"]) == []

    def test_schedule_players_toggle_opens_and_closes_table(self):
        """Node harness: pressing Players for game 201 fetches
        `/matches/201/players` and renders the table after that game row with the
        button `aria-expanded="true"`; pressing it again removes the table and sets
        `aria-expanded="false"`; opening it a second time makes no second fetch."""
        out = _run(_shown_open("""
  await toggleSchedulePlayers(201);
  out.open = snap();
  await toggleSchedulePlayers(201);
  out.closed = snap();
  await toggleSchedulePlayers(201);
  out.again = snap();
"""))
        opened = out["open"]["content"]
        assert _player_fetches(out["open"]["fetches"]) == ["/matches/201/players"]
        assert _buttons(opened)[0]["aria-expanded"] == "true"
        assert [b["aria-expanded"] for b in _buttons(opened)[1:]] == ["false", "false"]
        table_at = opened.index('id="game-players-201"')
        first_row = opened.index('<div class="game-row">')
        second_row = opened.index('<div class="game-row">', first_row + 1)
        assert first_row < table_at < second_row
        closed = out["closed"]["content"]
        assert "game-players-table" not in closed and 'id="game-players-201"' not in closed
        assert _buttons(closed)[0]["aria-expanded"] == "false"
        assert "game-players-table" in out["again"]["content"]
        assert _player_fetches(out["again"]["fetches"]) == ["/matches/201/players"]

    def test_schedule_players_table_columns_note_and_points(self):
        """Node harness: the open table groups rows under both team names in
        response order, each row showing player name, hero icon, "K/D/A" and
        raw points to one decimal (`5.0`, not `5`), and the note under it reads
        exactly "Raw points: from the player's own stats, before card rarity,
        modifiers and the MVP bonus.\""""
        out = _run(_shown_open("  await toggleSchedulePlayers(201);\n  out.s = snap();\n"))
        table = _table(out["s"]["content"], 201)
        text = "".join(_parse(table).text)
        assert text.index("Charlie") < text.index("Ann") < text.index("Bob") < text.index("Delta") < text.index("Cid")
        for header in ("Player", "Hero", "K/D/A", "Raw"):
            assert header in text
        assert "3/2/7" in text
        assert "12.3" in text and "5.0" in text and "1.2" in text
        imgs = [a for t, a in _parse(table).tags if t == "img" and "hero-icon" in _classes(a)]
        assert len(imgs) == 3 and imgs[0]["src"] == "https://cdn.example/h.png"
        assert "hero-icon-placeholder" in table
        start = table.index('<p class="game-players-note">')
        note = table[start:table.index("</p>", start)]
        assert "".join(_parse(note).text) == _NOTE

    def test_schedule_players_table_marks_top_performer_and_mvp_star(self):
        """Node harness: rows with `top: true` carry the top-performer marker class
        (both rows on a tie), and the `is_mvp` row carries the ★ star; other rows
        carry neither."""
        out = _run(_shown_open("  await toggleSchedulePlayers(201);\n  out.s = snap();\n"))
        table = _table(out["s"]["content"], 201)
        rows = table.split('<tr class="game-players-row')[1:]
        by_name = {}
        for r in rows:
            for name in ("Ann", "Bob", "Cid", "Dee"):
                if f">{name}</span>" in r:
                    by_name[name] = r
        assert set(by_name) == {"Ann", "Bob", "Cid", "Dee"}
        for name in ("Ann", "Cid"):
            assert by_name[name].startswith(' top"') and "mark-winner" in by_name[name] and "★" not in by_name[name]
        assert "★" in by_name["Bob"] and not by_name["Bob"].startswith(' top"') and "mark-winner" not in by_name["Bob"]
        assert "★" not in by_name["Dee"] and "mark-winner" not in by_name["Dee"]

    def test_schedule_players_table_name_opens_player_popup(self):
        """Node harness: each player name in the table is `playerLink(player_id,
        player_name)` markup (the same markup app-globals.js `playerLink` returns),
        so it opens the player popup."""
        out = _run(_shown_open("""
  await toggleSchedulePlayers(201);
  out.s = snap();
  out.links = [[31, "Ann"], [32, "Bob"], [41, "Cid"], [42, "Dee"]].map(([i, n]) => playerLink(i, n));
"""))
        table = _table(out["s"]["content"], 201)
        for link in out["links"]:
            assert link in table
        assert "openPlayerModal(31)" in table

    def test_schedule_players_table_fits_phone_width(self):
        """style.css has the players-table rules before the `GUIDED TOUR (issue
        #144)` block, the table does not set a min-width wider than the screen and
        is width-bounded (`width: 100%` or `max-width: 100%`), and a
        `max-width: 479px` (or `< 480px`) media rule hides the hero column."""
        css = _css()
        tour = css.index("GUIDED TOUR (issue #144)")
        assert css.index(".game-players-table") < tour
        body = _rule(css, ".game-players-table")
        assert "width: 100%" in body or "max-width: 100%" in body
        assert "min-width" not in body
        media = _media_body(css, "max-width: 479px")
        assert css.index("@media (max-width: 479px)") < tour
        assert ".game-players-hero" in media and "display: none" in _rule(media, ".game-players-hero")

    def test_schedule_players_table_escapes_player_and_team_names(self):
        """Failure path. Node harness: a response whose player and team names hold
        `<img src=x onerror=alert(1)>` renders them only as `&lt;img ...` text; the
        raw tag never appears in the schedule content."""
        evil = _resp(201, teams=[
            {"team_id": 3, "team_name": _EVIL, "players": [_p(31, _EVIL, 4.0)]},
            {"team_id": 4, "team_name": "Delta", "players": [_p(41, "Cid", 2.0)]},
        ])
        out = _run(_shown_open("  await toggleSchedulePlayers(201);\n  out.s = snap();\n"), players={201: evil})
        content = out["s"]["content"]
        assert "<img src=x" not in content
        assert content.count("&lt;img src=x onerror=alert(1)&gt;") == 2
        text = "".join(_parse(_table(content, 201)).text)
        assert text.count(_EVIL) == 2


# ---------------------------------------------------------------------------
# Story 2: Player Tables Keep Results Hidden
# ---------------------------------------------------------------------------

class TestPlayerTablesKeepResultsHidden:

    def test_hidden_series_row_has_no_players_button_or_player_data(self):
        """Node harness with hide mode on: the hidden Charlie-Delta row has no
        Players button and no player name, K/D/A or points; the `hiddenRow`
        closure source in `loadSchedule` holds no "Players" or `/matches/`."""
        out = _run("""
  await loadSchedule();
  toggleScheduleGames(id("201,202,203"));
  out.s = snap();
""")
        row = _row(out["s"]["content"], "Charlie", "Delta")
        assert "result-hidden" in row
        assert not _buttons(out["s"]["content"]) and "game-players" not in out["s"]["content"]
        for leak in ("Players", "Ann", "3/2/7", "12.3", "★"):
            assert leak not in row
        src = _nested(_load_schedule(), "hiddenRow")
        assert "Players" not in src and "/matches/" not in src

    def test_hidden_series_loads_no_player_data(self):
        """Failure path. Node harness with hide mode on: after `loadSchedule()` and
        trying `toggleScheduleGames` / the players toggle for a hidden series'
        game, `fetches` holds no `/matches/.../players` call."""
        out = _run("""
  await loadSchedule();
  toggleScheduleGames(id("201,202,203"));
  await toggleSchedulePlayers(201);
  await toggleSchedulePlayers("202");
  out.s = snap();
""")
        assert _player_fetches(out["s"]["fetches"]) == []
        assert "game-players" not in out["s"]["content"]

    def test_revealed_series_game_rows_get_players_buttons(self):
        """Node harness: after `revealScheduleSeries(id(...))` and unfolding the
        games, each game row of that series has a working Players button (pressing
        it fetches and renders the table)."""
        out = _run("""
  await loadSchedule();
  revealScheduleSeries(id("201,202,203"));
  toggleScheduleGames(id("201,202,203"));
  out.before = snap();
  await toggleSchedulePlayers(203);
  out.s = snap();
""")
        assert len(_buttons(_row(out["before"]["content"], "Charlie", "Delta"))) == 3
        assert _player_fetches(out["s"]["fetches"]) == ["/matches/203/players"]
        assert _table(out["s"]["content"], 203) and "game-players-table" in _table(out["s"]["content"], 203)

    def test_hide_week_again_closes_open_player_tables(self):
        """Node harness: reveal week 2, unfold Charlie-Delta, open game 201's table,
        then `hideScheduleWeekAgain(1)`: the content holds no player table; after
        revealing the week again and unfolding, game 201's button is
        `aria-expanded="false"` and no table is shown."""
        out = _run("""
  await loadSchedule();
  revealScheduleWeek(1);
  toggleScheduleGames(id("201,202,203"));
  await toggleSchedulePlayers(201);
  out.open = snap();
  hideScheduleWeekAgain(1);
  out.hidden = snap();
  revealScheduleWeek(1);
  if (!snap().content.includes('class="game-row"')) toggleScheduleGames(id("201,202,203"));
  out.again = snap();
""")
        assert "game-players-table" in out["open"]["content"]
        assert "game-players" not in out["hidden"]["content"]
        again = out["again"]["content"]
        assert _buttons(again)[0]["aria-controls"] == "game-players-201"
        assert _buttons(again)[0]["aria-expanded"] == "false"
        assert "game-players-table" not in again

    def test_latest_result_card_games_button_unchanged(self):
        """The Latest result card still has its Games button calling
        `showScheduleLatestGames` and no player table or Players button of its own;
        after pressing it, the week's unfolded game rows carry Players buttons."""
        out = _run("""
  await loadSchedule();
  toggleScheduleHide();
  out.card = snap().now;
  showScheduleLatestGames(id("201,202,203"), 1);
  out.s = snap();
""")
        card = _now_card(out["card"], "latest")
        assert 'onclick="showScheduleLatestGames(this.dataset.key, 1)">Games</button>' in card
        assert "game-players" not in out["card"] and "Players" not in card
        assert len(_buttons(out["s"]["content"])) == 3


# ---------------------------------------------------------------------------
# Story 3: Partial and Unscored Games Are Labelled
# ---------------------------------------------------------------------------

class TestPartialAndUnscoredGamesAreLabelled:

    @pytest.mark.parametrize("status", ["unparsed", "unparseable"])
    def test_game_players_reports_parse_status(self, db, status):
        """`game_players` returns `parse_status == status` for a match stored with
        that status, and its players' raw points treat the missing stats as 0
        (equal to `fantasy_score` of the stored row)."""
        from schedule import game_players
        _weights(db)
        _seed_teams(db)
        _match(db, 910, parse=status)
        _stat(db, 1, 910, team=1, obs_placed=None, sen_placed=None, stuns=None,
              teamfight_participation=None, rune_pickups=None, camps_stacked=None)
        data = game_players(db, 910)
        assert data["parse_status"] == status
        assert _players(data)[0]["raw_points"] == _expected_raw(db, 910)[1]

    def test_game_players_excluded_match_still_returns_raw_points(self, db):
        """A match with `excluded_from_scoring=True` returns
        `excluded_from_scoring: True` and all its players with their raw points
        (not 0, not omitted)."""
        from schedule import game_players
        _seed_game(db, excluded=True)
        data = game_players(db, 900)
        assert data["excluded_from_scoring"] is True
        got = {p["player_id"]: p["raw_points"] for p in _players(data)}
        assert got == _expected_raw(db, 900) and len(got) == 10 and all(v > 0 for v in got.values())

    def test_game_players_match_without_stats_returns_no_players(self, db):
        """Failure path. A stored match with no `player_match_stats` rows returns
        its `match_id` and no player in any team entry (see the Ambiguity note in
        the module docstring).

        Settled in review: `teams` still holds the match's two teams (radiant, then
        dire), each with an empty `players` list."""
        from schedule import game_players
        _weights(db)
        _seed_teams(db)
        _match(db, 920)
        data = game_players(db, 920)
        assert data["match_id"] == 920
        assert data["teams"] == [{"team_id": 1, "team_name": "Reds", "players": []},
                                 {"team_id": 2, "team_name": "Blues", "players": []}]

    def test_schedule_players_table_partial_stats_badge_with_tooltip(self):
        """Node harness: a response with `parse_status` "unparsed" (and one with
        "unparseable") renders the "Partial stats" badge on the table with
        `title` equal to the escaped `_PARTIAL_STATS_TOOLTIP` text ("The replay has
        not been parsed, so wards, stuns, teamfight, runes and camps count as 0.")."""
        out = _run(_shown_open("""
  await toggleSchedulePlayers(201);
  await toggleSchedulePlayers(203);
  out.s = snap();
  out.tip = _PARTIAL_STATS_TOOLTIP;
"""), players={201: _resp(201, parse="unparsed"), 203: _resp(203, parse="unparseable")})
        assert out["tip"] == _PARTIAL_TIP
        for mid in (201, 203):
            table = _table(out["s"]["content"], mid)
            badges = [a for t, a in _parse(table).tags if t == "span" and "badge" in _classes(a)]
            assert [b["title"] for b in badges] == [_PARTIAL_TIP]
            assert ">Partial stats</span>" in table

    def test_schedule_players_table_parsed_game_has_no_partial_badge(self):
        """Failure path. Node harness: a response with `parse_status` "parsed" (or
        null) renders no "Partial stats" badge."""
        out = _run(_shown_open("""
  await toggleSchedulePlayers(201);
  await toggleSchedulePlayers(203);
  out.s = snap();
"""), players={201: _resp(201, parse="parsed"), 203: _resp(203, parse=None)})
        for mid in (201, 203):
            table = _table(out["s"]["content"], mid)
            assert "game-players-table" in table and "Partial stats" not in table

    def test_schedule_players_table_repeats_not_scored_badge(self):
        """Node harness: a response with `excluded_from_scoring: true` renders the
        players and their raw points plus a "Not scored" badge whose `title` is the
        escaped `_NOT_SCORED_TOOLTIP`."""
        out = _run(_shown_open("  await toggleSchedulePlayers(202);\n  out.s = snap();\n"),
                   players={202: _resp(202, excluded=True)})
        table = _table(out["s"]["content"], 202)
        badges = [a for t, a in _parse(table).tags if t == "span" and "badge" in _classes(a)]
        assert [b["title"] for b in badges] == [_NOT_SCORED_TIP]
        assert ">Not scored</span>" in table
        text = "".join(_parse(table).text)
        assert "Ann" in text and "12.3" in text and "5.0" in text

    def test_schedule_players_no_stats_message(self):
        """Node harness: a response with no players renders exactly "No player stats
        for this game yet." and no table rows."""
        empty = _resp(201, teams=[{"team_id": 3, "team_name": "Charlie", "players": []},
                                  {"team_id": 4, "team_name": "Delta", "players": []}])
        out = _run(_shown_open("  await toggleSchedulePlayers(201);\n  out.s = snap();\n"), players={201: empty})
        table = _table(out["s"]["content"], 201)
        assert "".join(_parse(table).text).strip() == "No player stats for this game yet."
        assert "<tr" not in table and "<table" not in table


# ---------------------------------------------------------------------------
# Story 4: Public Endpoint for One Game's Players
# ---------------------------------------------------------------------------

class TestPublicEndpointForOneGamesPlayers:

    def test_get_match_players_is_public_and_returns_shape(self, db):
        """`GET /matches/{id}/players` through `_client(db)` (players router, no
        session, no auth override) answers 200 with keys `match_id`,
        `parse_status`, `excluded_from_scoring`, `teams` (two entries with
        `team_id`, `team_name`, `players`)."""
        _seed_game(db)
        res = _client(db).get("/matches/900/players")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"match_id", "parse_status", "excluded_from_scoring", "teams"}
        assert body["match_id"] == 900 and body["parse_status"] == "parsed"
        assert len(body["teams"]) == 2
        assert all(set(t) == {"team_id", "team_name", "players"} for t in body["teams"])

    def test_get_match_players_reachable_on_main_app_without_login(self, db):
        """On `main.app` (TestClient, `get_db` overridden), an anonymous
        `GET /matches/{id}/players` answers 200 JSON, not the static mount's
        response or a 401/403."""
        from fastapi.testclient import TestClient
        import main
        from database import get_db
        _seed_game(db)

        def _get_db():
            yield db
        main.app.dependency_overrides[get_db] = _get_db
        try:
            res = TestClient(main.app).get("/matches/900/players")
        finally:
            main.app.dependency_overrides.pop(get_db, None)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
        assert res.json()["match_id"] == 900

    def test_get_match_players_unknown_match_404(self, db):
        """Failure path. `GET /matches/999999/players` for a match not in `matches`
        answers 404."""
        _seed_game(db)
        res = _client(db).get("/matches/999999/players")
        assert res.status_code == 404

    @pytest.mark.parametrize("bad_id", ["0", str(2**63), "-1"])
    def test_get_match_players_out_of_range_id_422(self, db, bad_id):
        """Failure path. A match id outside 1..2**63-1 answers 422, never a 500."""
        from fastapi.testclient import TestClient
        from routers import players
        from fastapi import FastAPI
        from database import get_db
        app = FastAPI()
        app.include_router(players.router)

        def _get_db():
            yield db
        app.dependency_overrides[get_db] = _get_db
        res = TestClient(app, raise_server_exceptions=False).get(f"/matches/{bad_id}/players")
        assert res.status_code == 422

    def test_get_match_players_returns_no_user_or_card_data(self, db):
        """With users, cards and card points seeded for the match's players, the
        response's top-level keys are exactly `match_id`, `parse_status`,
        `excluded_from_scoring`, `teams`; team keys exactly `team_id`, `team_name`,
        `players`; player keys exactly the ten listed in the plan (no `user_id`,
        `username`, `card_id`, `owner`, `fantasy_points`)."""
        pids = _seed_game(db)
        db.add(models.User(id=1, username="owner1", email="o@example.com", password_hash="x"))
        db.commit()
        for i, pid in enumerate(pids[:3]):
            db.add(models.Card(id=i + 1, player_id=pid, owner_id=1, card_type="rare", is_active=True))
            db.add(models.CardMatchPoints(card_id=i + 1, match_id=900, player_id=pid, points=9.9))
        db.commit()
        body = _client(db).get("/matches/900/players").json()
        assert set(body) == {"match_id", "parse_status", "excluded_from_scoring", "teams"}
        for t in body["teams"]:
            assert set(t) == {"team_id", "team_name", "players"}
            for p in t["players"]:
                assert set(p) == _PLAYER_KEYS
        raw = json.dumps(body)
        for leak in ("owner1", "user_id", "username", "card_id", "owner", "fantasy_points", "9.9"):
            assert leak not in raw

    def test_get_match_players_cached_per_match_and_cleared_by_bust_cache(self, db, monkeypatch):
        """A second call after changing a stat row directly returns the cached
        (old) values; after `schedule.bust_cache()` the call returns the new ones.
        A different match id is cached separately."""
        import schedule
        monkeypatch.setattr(schedule, "_hero_icon_cache", {})  # warm (empty) hero cache
        _seed_game(db, 900)
        _seed_game(db, 930)
        client = _client(db)
        first = client.get("/matches/900/players").json()
        other = client.get("/matches/930/players").json()
        row = db.query(models.PlayerMatchStats).filter_by(match_id=900, player_id=90009).one()
        row.kills = 40
        db.commit()
        cached = client.get("/matches/900/players").json()
        assert cached == first
        assert other["match_id"] == 930 and client.get("/matches/930/players").json() == other
        schedule.bust_cache()
        fresh = client.get("/matches/900/players").json()
        kills = {p["player_id"]: p["kills"] for p in _players(fresh)}
        assert kills[90009] == 40 and fresh != first

    def test_get_match_players_cache_expires_after_cache_ttl(self, db, monkeypatch):
        """Regression (Stage 3 review): league ingest, parse retries, enrichment and
        season reset don't call `bust_cache()`, so an entry expires after
        `schedule.CACHE_TTL` like the schedule. A fresh entry is served from the
        cache; one older than CACHE_TTL is rebuilt from the database."""
        import schedule
        monkeypatch.setattr(schedule, "_hero_icon_cache", {})
        clock = [1000.0]
        monkeypatch.setattr(schedule, "_monotonic", lambda: clock[0])
        _seed_game(db)
        client = _client(db)
        first = client.get("/matches/900/players").json()
        row = db.query(models.PlayerMatchStats).filter_by(match_id=900, player_id=90009).one()
        row.kills = 40
        db.commit()
        clock[0] += schedule.CACHE_TTL - 1
        assert client.get("/matches/900/players").json() == first
        clock[0] += 2
        fresh = client.get("/matches/900/players").json()
        assert {p["player_id"]: p["kills"] for p in _players(fresh)}[90009] == 40
        # The rebuilt entry is cached again from its own build time.
        row.kills = 41
        db.commit()
        clock[0] += schedule.CACHE_TTL - 1
        assert client.get("/matches/900/players").json() == fresh

    def test_mvp_change_shows_at_once(self, db, monkeypatch):
        """After the first call caches the match, setting a new MVP through the
        existing path that calls `bust_cache` (e.g. `apply_mvp_bonus_to_row` +
        commit + `schedule.bust_cache()`, as routers/admin_matches.py's admin MVP
        route does) makes the next call report the new player as `is_mvp`."""
        import schedule
        from scoring import apply_mvp_bonus_to_row
        monkeypatch.setattr(schedule, "_hero_icon_cache", {})
        pids = _seed_game(db)
        client = _client(db)
        before = {p["player_id"]: p["is_mvp"] for p in _players(client.get("/matches/900/players").json())}
        assert before[pids[4]] is True and before[pids[7]] is False
        weights = {w.key: w.value for w in db.query(models.Weight)}
        rows = {r.player_id: r for r in db.query(models.PlayerMatchStats).filter_by(match_id=900)}
        apply_mvp_bonus_to_row(rows[pids[4]], weights, False)
        apply_mvp_bonus_to_row(rows[pids[7]], weights, True)
        db.commit()
        schedule.bust_cache()
        after = {p["player_id"]: p["is_mvp"] for p in _players(client.get("/matches/900/players").json())}
        assert [pid for pid, v in after.items() if v] == [pids[7]]
