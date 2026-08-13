"""
Failing test stubs for plan-mvp-visibility.md (resolves GitHub issue #92).

Surfaces the existing `PlayerMatchStats.is_mvp` flag (already set by
`_apply_mvp_bonus()` in `backend/twitch.py` via `POST /twitch/mvp`) in three
places it currently isn't visible at all. No migration is needed anywhere in
this plan — `is_mvp`, `team_id`, and `matches.radiant_team_id`/`dire_team_id`
already exist.

Every stub below is a `pytest.fail("not yet implemented")` placeholder. The
backend-testable stubs are real pytest tests using the `db` fixture (and
`monkeypatch` where relevant) to seed players/teams/matches/player_match_stats
and exercise real endpoint/module functions once implemented — they are not
file-content-grep tests, since real SQL aggregates and joins are involved.
The frontend-only stubs use the `_extract_function()` brace-depth helper
established in `test_issue_89_fix_available_draws_count.py` and
`test_my_team_remove_move_buttons.py` to assert against
`frontend/app-players.js` / `frontend/index.html` file contents.

Covers three user stories from markdown/plans/plan-mvp-visibility.md:

  Story: MVP Count on the Players Tab
    - `GET /players` (list_players() in backend/routers/players.py) includes
      an `mvp_count` field per player: COUNT of that player's
      player_match_stats rows where is_mvp is true
    - A player who has never been MVP returns mvp_count: 0, not a missing key
    - The Players tab table (frontend/index.html) gains an "MVPs"
      `<th data-col="mvp_count">`, sortable like the existing columns
    - renderPlayers() (frontend/app-players.js) renders p.mvp_count in a new
      cell for every row

  Story: Match History Shows MVP, Opponent, and an OpenDota Link
    - `GET /players/{player_id}` (get_player() in
      backend/routers/players.py) match_history rows each include
      opponent_team_id/opponent_team_name, resolved from whichever of the
      match's radiant_team_id/dire_team_id is not the player's own team_id
      for that row (Team.id IS the OpenDota team_id)
    - A match_history row whose match has no resolvable opponent team (e.g.
      the non-owned side's team_id doesn't match any row in teams) surfaces
      opponent_team_id/opponent_team_name as None rather than raising
    - The match history table's first column becomes a dedicated MVP star
      (frontend/index.html thead + openPlayerModal()'s row builder in
      frontend/app-players.js), no longer an inline badge appended after
      Fantasy pts; an "Opponent" column (team-linked) and a final OpenDota
      link column are added, with the empty-state colspan updated to match

  Story: Schedule Tab Shows Match MVP
    - `GET /schedule`'s per-game entries (_build_games() in
      backend/schedule.py) include mvp_player_id/mvp_player_name, resolved
      from the player_match_stats row with is_mvp=1 for that match_id
    - A game whose match has no is_mvp=1 row surfaces mvp_player_id/
      mvp_player_name as None rather than raising or omitting the keys
    - Schedule tab game rows (gameRowsHtml builder in
      frontend/app-players.js) insert playerLink(g.mvp_player_id,
      g.mvp_player_name) as the first child of .game-row-meta, immediately
      before .game-row-duration, only when g.mvp_player_id is present
    - A game with no MVP set renders no MVP link in that position and no
      broken/empty gap in the row layout

Run with: cd backend && python -m pytest tests/test_mvp_visibility.py -v
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import Match, Player, PlayerMatchStats, Team
from routers import players as players_router
import schedule


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
APP_PLAYERS_JS_PATH = os.path.join(FRONTEND_DIR, "app-players.js")
INDEX_HTML_PATH = os.path.join(FRONTEND_DIR, "index.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_function(js, name):
    """Return the full source of a top-level `async function {name}() { ... }`
    or `function {name}() { ... }` block, matched by brace-depth counting so
    nested braces inside the function body don't truncate the match."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", js)
    assert m, f"{name}() not found in source"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    return js[start:i - 1]


# ---------------------------------------------------------------------------
# Story: MVP Count on the Players Tab
# ---------------------------------------------------------------------------

class TestMvpCountOnThePlayersTab:

    def test_list_players_includes_mvp_count_for_player_with_mvp_matches(self, db):
        """GET /players (list_players()) returns an mvp_count field per player:
        seed one player with 3 player_match_stats rows, 2 of them is_mvp=True,
        and assert the returned dict for that player has mvp_count == 2 (a
        COUNT of is_mvp=true rows, alongside the existing matches/avg_points/
        total_points aggregates from the same LEFT JOIN player_match_stats)."""
        db.add(Player(id=1, name="PlayerOne"))
        db.add(Team(id=10, name="TeamA"))
        db.add(Match(match_id=1, radiant_team_id=10, dire_team_id=20, start_time=1000))
        db.add(Match(match_id=2, radiant_team_id=10, dire_team_id=20, start_time=2000))
        db.add(Match(match_id=3, radiant_team_id=10, dire_team_id=20, start_time=3000))
        db.add(PlayerMatchStats(player_id=1, match_id=1, team_id=10, fantasy_points=10, is_mvp=True))
        db.add(PlayerMatchStats(player_id=1, match_id=2, team_id=10, fantasy_points=10, is_mvp=True))
        db.add(PlayerMatchStats(player_id=1, match_id=3, team_id=10, fantasy_points=10, is_mvp=False))
        db.commit()

        results = players_router.list_players(db=db)
        row = next(r for r in results if r["id"] == 1)
        assert row["mvp_count"] == 2

    def test_list_players_mvp_count_zero_for_player_never_mvp(self, db):
        """A player with recorded matches but no is_mvp=True row anywhere
        returns mvp_count: 0 from list_players(), not a missing/null key —
        seed a player with 2 player_match_stats rows, both is_mvp=False (or
        unset), and assert mvp_count == 0 in the GET /players response."""
        db.add(Player(id=2, name="PlayerTwo"))
        db.add(Team(id=11, name="TeamB"))
        db.add(Match(match_id=4, radiant_team_id=11, dire_team_id=21, start_time=1000))
        db.add(Match(match_id=5, radiant_team_id=11, dire_team_id=21, start_time=2000))
        db.add(PlayerMatchStats(player_id=2, match_id=4, team_id=11, fantasy_points=5, is_mvp=False))
        db.add(PlayerMatchStats(player_id=2, match_id=5, team_id=11, fantasy_points=5))
        db.commit()

        results = players_router.list_players(db=db)
        row = next(r for r in results if r["id"] == 2)
        assert row["mvp_count"] == 0

    def test_players_table_header_has_sortable_mvps_column(self):
        """frontend/index.html's Players tab thead (#playersTableHead) gains
        a new `<th data-col="mvp_count">` with a "MVPs" label, following the
        existing sortable-header pattern used for matches/avg_points/
        total_points (data-col attribute + default-dir), positioned per the
        plan's column ordering."""
        html = _read(INDEX_HTML_PATH)
        m = re.search(r'<thead><tr id="playersTableHead">.*?</tr></thead>', html, re.S)
        assert m, "playersTableHead not found"
        head = m.group(0)
        assert re.search(r'<th\s+data-col="mvp_count"\s+data-default-dir="desc">\s*MVPs\s*</th>', head)
        assert head.index('data-col="total_points"') < head.index('data-col="mvp_count"')

    def test_render_players_displays_mvp_count_cell_for_every_row(self):
        """renderPlayers() in frontend/app-players.js renders a new `<td>`
        containing p.mvp_count for every player row (including 0, not a
        blank cell), matching the existing cell pattern used for p.matches/
        p.avg_points/p.total_points."""
        js = _read(APP_PLAYERS_JS_PATH)
        fn = _extract_function(js, "renderPlayers")
        assert "p.mvp_count" in fn


# ---------------------------------------------------------------------------
# Story: Match History Shows MVP, Opponent, and an OpenDota Link
# ---------------------------------------------------------------------------

class TestMatchHistoryShowsMvpOpponentAndOpenDotaLink:

    def test_get_player_match_history_includes_resolved_opponent_team(self, db):
        """GET /players/{player_id} (get_player()) match_history rows each
        include opponent_team_id/opponent_team_name: seed a player whose
        player_match_stats.team_id equals a match's radiant_team_id, with a
        second Team row for the match's dire_team_id, and assert the
        corresponding match_history row's opponent_team_id/opponent_team_name
        equal the dire team's id/name (and the mirror case where the
        player's team_id equals dire_team_id resolves to the radiant team)."""
        db.add(Player(id=1, name="P1"))
        db.add(Team(id=10, name="TeamA"))
        db.add(Team(id=20, name="TeamB"))
        # Player's team_id (10) is the radiant side of this match -> opponent is dire (20)
        db.add(Match(match_id=100, radiant_team_id=10, dire_team_id=20, start_time=1000))
        db.add(PlayerMatchStats(player_id=1, match_id=100, team_id=10, fantasy_points=10))
        # Mirror case: player's team_id (10) is the dire side -> opponent is radiant (20)
        db.add(Match(match_id=101, radiant_team_id=20, dire_team_id=10, start_time=2000))
        db.add(PlayerMatchStats(player_id=1, match_id=101, team_id=10, fantasy_points=12))
        db.commit()

        result = players_router.get_player(1, db=db)
        history_by_match = {r["match_id"]: r for r in result["match_history"]}
        assert history_by_match[100]["opponent_team_id"] == 20
        assert history_by_match[100]["opponent_team_name"] == "TeamB"
        assert history_by_match[101]["opponent_team_id"] == 20
        assert history_by_match[101]["opponent_team_name"] == "TeamB"

    def test_get_player_match_history_opponent_null_when_unresolvable(self, db):
        """A match_history row whose match's non-owned team_id does not
        correspond to any row in teams (e.g. the opposing team was never
        ingested) surfaces opponent_team_id/opponent_team_name as None
        rather than raising or omitting the keys — seed a match with only
        one of radiant_team_id/dire_team_id backed by a Team row."""
        db.add(Player(id=2, name="P2"))
        db.add(Team(id=10, name="TeamA"))
        # dire_team_id=99 has no corresponding Team row
        db.add(Match(match_id=200, radiant_team_id=10, dire_team_id=99, start_time=1000))
        db.add(PlayerMatchStats(player_id=2, match_id=200, team_id=10, fantasy_points=5))
        db.commit()

        result = players_router.get_player(2, db=db)
        row = result["match_history"][0]
        assert "opponent_team_id" in row and "opponent_team_name" in row
        assert row["opponent_team_id"] is None
        assert row["opponent_team_name"] is None

    def test_match_history_thead_has_leading_mvp_star_and_trailing_columns(self):
        """frontend/index.html's match history table thead (feeding
        #playerModalHistory) gains a leading MVP-star column as the very
        first `<th>` (not appended after Fantasy pts as before), a new
        "Opponent" column, and a final OpenDota-link column; the empty-state
        `<td colspan='6'>No matches yet</td>` row's colspan is updated to
        match the new total column count."""
        html = _read(INDEX_HTML_PATH)
        m = re.search(r'<thead><tr>(<th>[^<]*</th>)+</tr></thead>\s*<tbody id="playerModalHistory">', html, re.S)
        assert m, "match history thead not found"
        thead = m.group(0)
        headers = re.findall(r"<th>(.*?)</th>", thead)
        assert headers[0].strip().upper() == "MVP", f"expected MVP as first column, got {headers}"
        assert "Opponent" in headers
        assert headers[-1] != headers[0]

        empty_row = re.search(r"No matches yet", _read(APP_PLAYERS_JS_PATH))
        assert empty_row, "empty-state row not found"
        colspan_match = re.search(r"colspan='(\d+)'\s*style='color:#444'>No matches yet", _read(APP_PLAYERS_JS_PATH))
        assert colspan_match, "colspan on empty-state row not found"
        assert int(colspan_match.group(1)) == len(headers)

    def test_open_player_modal_history_row_mvp_star_is_first_column(self):
        """openPlayerModal()'s match-history row builder in
        frontend/app-players.js renders the MVP indicator as the row's first
        `<td>` (populated only when m.is_mvp is true), not as an inline badge
        appended after the Fantasy pts `<td>` — the string ' <span
        style=\"font-size:0.7rem;color:#f5c842' inline-badge pattern used
        today must no longer appear after the fantasy_points cell."""
        js = _read(APP_PLAYERS_JS_PATH)
        fn = _extract_function(js, "openPlayerModal")
        assert ' <span style="font-size:0.7rem;color:#f5c842' not in fn
        assert "m.is_mvp" in fn
        # The row template's first <td> must be the MVP indicator, before the date <td>.
        row_template = re.search(r"return `<tr>(.*?)</tr>`;", fn, re.S)
        assert row_template, "match-history row template not found"
        tds = re.findall(r"<td>(.*?)</td>", row_template.group(1), re.S)
        assert "mvpStar" in tds[0] or "is_mvp" in tds[0]
        assert "date" in tds[1]

    def test_open_player_modal_history_row_has_opponent_and_opendota_link_cells(self):
        """openPlayerModal()'s match-history row builder adds an "Opponent"
        `<td>` using teamLink(m.opponent_team_id, m.opponent_team_name)
        (falling back to plain text when opponent_team_id is null, matching
        teamLink()'s existing null-handling), and a final `<td>` containing a
        link to https://www.opendota.com/matches/{m.match_id} with
        target="_blank" rel="noopener", mirroring the Schedule tab's
        per-game OpenDota link attributes."""
        js = _read(APP_PLAYERS_JS_PATH)
        fn = _extract_function(js, "openPlayerModal")
        assert "m.opponent_team_id" in fn and "m.opponent_team_name" in fn
        assert "teamLink(m.opponent_team_id, m.opponent_team_name)" in fn
        assert "https://www.opendota.com/matches/${m.match_id}" in fn
        assert 'target="_blank"' in fn and 'rel="noopener' in fn


# ---------------------------------------------------------------------------
# Story: Schedule Tab Shows Match MVP
# ---------------------------------------------------------------------------

class TestScheduleTabShowsMatchMvp:

    def test_build_games_includes_mvp_player_id_and_name_when_set(self, db, monkeypatch):
        """_build_games() in backend/schedule.py attaches mvp_player_id/
        mvp_player_name to a game entry, resolved from the
        player_match_stats row with is_mvp=1 for that match_id: seed a
        match with two PlayerMatchStats rows, one is_mvp=True, and assert
        the corresponding games[] entry's mvp_player_id/mvp_player_name
        equal that player's id/name."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Player(id=301, name="StarPlayer"))
        db.add(Player(id=302, name="OtherPlayer"))
        db.add(Match(match_id=5001, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000, duration=1800))
        db.add(PlayerMatchStats(player_id=301, match_id=5001, team_id=1, kills=10, is_mvp=True))
        db.add(PlayerMatchStats(player_id=302, match_id=5001, team_id=2, kills=5, is_mvp=False))
        db.commit()

        games = schedule._build_games(db, [5001], 1, 2)
        assert games[0]["mvp_player_id"] == 301
        assert games[0]["mvp_player_name"] == "StarPlayer"

    def test_build_games_mvp_fields_null_when_no_mvp_set_for_match(self, db, monkeypatch):
        """A game whose match has no is_mvp=1 row in player_match_stats (MVP
        never confirmed via POST /twitch/mvp) surfaces mvp_player_id: None
        and mvp_player_name: None in its games[] entry, rather than raising
        or omitting the keys — matches with no PlayerMatchStats rows at all
        must also degrade cleanly to null MVP fields."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(match_id=5002, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000, duration=1800))
        db.commit()

        games = schedule._build_games(db, [5002], 1, 2)
        assert "mvp_player_id" in games[0] and "mvp_player_name" in games[0]
        assert games[0]["mvp_player_id"] is None
        assert games[0]["mvp_player_name"] is None

    def test_schedule_game_row_inserts_mvp_playerlink_before_duration(self):
        """The gameRowsHtml builder in frontend/app-players.js's Schedule tab
        rendering inserts playerLink(g.mvp_player_id, g.mvp_player_name) as
        the first child of .game-row-meta, immediately before the existing
        `<span class="game-row-duration">` element, when g.mvp_player_id is
        present — matching the existing playerLink() pattern used elsewhere
        for clickable player names."""
        js = _read(APP_PLAYERS_JS_PATH)
        fn = _extract_function(js, "loadSchedule")
        meta_match = re.search(
            r'<span class="game-row-meta">(.*?)<span class="game-row-duration">',
            fn, re.S,
        )
        assert meta_match, ".game-row-meta block not found before .game-row-duration"
        prefix = meta_match.group(1)
        assert "g.mvp_player_id" in prefix
        assert "playerLink(g.mvp_player_id, g.mvp_player_name)" in prefix

    def test_schedule_game_row_no_mvp_link_or_gap_when_mvp_unset(self):
        """When g.mvp_player_id is null, the gameRowsHtml builder renders no
        MVP playerLink in .game-row-meta and leaves no visibly broken gap or
        layout shift in that position — the conditional insertion must not
        emit an empty wrapper element when there is no MVP for that game."""
        js = _read(APP_PLAYERS_JS_PATH)
        fn = _extract_function(js, "loadSchedule")
        meta_match = re.search(
            r'<span class="game-row-meta">(.*?)<span class="game-row-duration">',
            fn, re.S,
        )
        assert meta_match
        prefix = meta_match.group(1)
        # Must be a ternary that renders "" (no element at all) when absent,
        # not an always-present wrapper span around the conditional link.
        # The truthy branch may prepend a star marker before playerLink(...)
        # (added later to visually flag what the linked name represents), so
        # only the ternary's gating condition, the playerLink(...) call
        # somewhere in the truthy branch, and the "" fallback are pinned.
        assert re.search(
            r"g\.mvp_player_id\s*\?.*?playerLink\(g\.mvp_player_id,\s*g\.mvp_player_name\).*?:\s*[\"']{2}",
            prefix, re.S,
        )
