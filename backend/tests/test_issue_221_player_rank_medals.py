"""
Tests for plan-issue-221-player-rank-medals.md (resolves GitHub issue #221).

Each pool player's Dota 2 rank medal (`rank_tier`, `leaderboard_rank`) is taken
from the OpenDota `GET /players/{account_id}` response the app already fetches,
stored on `players` with `rank_fetched_at`, refreshed by the background profile
enrichment, returned by `GET /players/{id}` and the card lists, and shown as a
medal badge in the player popup and the card viewer.

  Story 1: Store Each Player's Rank Medal          (TestStorePlayerRankMedal)
  Story 2: See a Player's Medal in the Player Popup (TestPlayerPopupMedal)
  Story 3: See the Medal on a Card                  (TestCardMedal)

Not stubbed: "the PNG draws the medal in the #218 rank slot" (Story 3) -- the
plan builds `image.py::_draw_rank_medal` with the #218 templates; its tests
belong to #218.

Approach notes:

- `db` fixture from conftest (in-memory SQLite). Import `models` at module level
  so every table exists before the fixture runs.
- Parsing: `player_rank.parse_rank(data) -> (rank_tier, leaderboard_rank)` and
  `player_rank.medal_name(rank_tier, leaderboard_rank) -> str | None` (new module).
  Cases from the plan: 10, 54, 75, 80 with and without a leaderboard place; null,
  0, 9, 81, 95 and strings.
- Migration: run `migrate.run_migrations()` on a `players` table without the three
  columns (pattern in tests/test_migrate.py).
- OpenDota calls are stubbed (monkeypatch `opendota_get_json` / the fetch used by
  `enrich_players`, `routers/admin_players.py::add_player` and `_bulk_add_stream`).
  Use the trimmed response fixture recorded in plan Step 1.
- Enrichment: `enrich.run_profile_enrichment` rank phase; cooldown is
  `enrich._COOLDOWN_HOURS` (`PROFILE_ENRICHMENT_COOLDOWN_HOURS`); result dict has
  `rank_updated`.
- API: call route functions directly with `db=db` (as in other issue tests).
- Frontend: static checks / Node harness of `frontend/app-players.js`
  (`rankMedalHtml(tier, lb)`), `frontend/app-cards.js` and `frontend/style.css`
  (`.rank-medal`, `--medal-*` tokens). Reuse `_read`, `_fn_body` helpers from
  test_issue_151_weekly_report_aesthetics.py and `_node()` from
  test_issue_159_flicker_free_tab_switching.py.

Run with: cd backend && python -m pytest tests/test_issue_221_player_rank_medals.py -v
"""

import json
import os
import re
import subprocess
import time

import pytest
from sqlalchemy import create_engine, inspect, text

import enrich
import models  # noqa: F401  -- register all tables before the db fixture runs
import player_rank
from models import Card, Player, PlayerMatchStats, Team, User
from routers import admin_ingest, admin_players, cards as cards_router, players as players_router
from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _fn_body, _read
from tests.test_issue_159_flicker_free_tab_switching import _node

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
GLOBALS_JS = os.path.join(FRONTEND_DIR, "app-globals.js")
PLAYERS_JS = os.path.join(FRONTEND_DIR, "app-players.js")
CARDS_JS = os.path.join(FRONTEND_DIR, "app-cards.js")
STYLE_CSS = os.path.join(FRONTEND_DIR, "style.css")
TOKENS_CSS = os.path.join(FRONTEND_DIR, "colors_and_type.css")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")

ADMIN = {"user_id": 1, "username": "admin"}
MEDAL_KEYS = ("herald", "guardian", "crusader", "archon", "legend", "ancient", "divine", "immortal")


def _od_player(account_id, rank_tier=None, leaderboard_rank=None, name=None):
    """Trimmed OpenDota GET /players/{account_id} response (documented shape; the live
    API is not reachable from the test environment). rank fields are top-level."""
    return {
        "profile": {"account_id": account_id, "personaname": name or f"P{account_id}",
                    "avatarfull": f"https://avatars.example/{account_id}.jpg"},
        "rank_tier": rank_tier,
        "leaderboard_rank": leaderboard_rank,
    }


def _fake_opendota(responses, calls=None):
    """get_json stand-in: /players/{id} answers from `responses` (missing or None = failed
    request); every other URL (constants/heroes) answers None."""
    def fake(url, **kwargs):
        m = re.search(r"/players/(\d+)$", url)
        if calls is not None:
            calls.append(url)
        if not m:
            return None
        return responses.get(int(m.group(1)))
    return fake


def _use_db(monkeypatch, db, responses, calls=None):
    monkeypatch.setattr(enrich, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(enrich, "opendota_get_json", _fake_opendota(responses, calls))
    monkeypatch.setattr(enrich.time, "sleep", lambda s: None)


def _cooldown_secs():
    return int(enrich._COOLDOWN_HOURS * 3600)


def _medal_js(steps):
    """Run rankMedalHtml (with _RANK_MEDALS and _escHtml) from app-globals.js under Node."""
    node = _node()
    if not node:
        pytest.skip("node not installed")
    js = _read(GLOBALS_JS)
    const = js[js.index("const _RANK_MEDALS"):js.index("};", js.index("const _RANK_MEDALS")) + 2]
    script = "\n".join([const, _fn_body(js, "_escHtml") + "\n}\n", _fn_body(js, "rankMedalHtml") + "\n}\n",
                        "const out = {};", steps, "console.log(JSON.stringify(out));"])
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _seed_card(db, player_kw, owner_id=1, card_type="rare", is_active=True, slot_index=0):
    db.add(User(id=owner_id, username=f"u{owner_id}", tokens=5))
    db.add(Team(id=7, name="Team Seven"))
    db.add(Player(is_active=True, **player_kw))
    db.flush()
    db.add(PlayerMatchStats(player_id=player_kw["id"], match_id=1, team_id=7, fantasy_points=10.0))
    card = Card(card_type=card_type, player_id=player_kw["id"], owner_id=owner_id,
                is_active=is_active, slot_index=slot_index, generation=1)
    db.add(card)
    db.commit()
    return card


# ---------------------------------------------------------------------------
# Story 1: Store Each Player's Rank Medal
# ---------------------------------------------------------------------------

class TestStorePlayerRankMedal:

    def test_player_model_has_nullable_rank_columns(self, db):
        """`players` gains nullable `rank_tier`, `leaderboard_rank` and `rank_fetched_at`."""
        cols = {c["name"]: c for c in inspect(db.get_bind()).get_columns("players")}
        for name in ("rank_tier", "leaderboard_rank", "rank_fetched_at"):
            assert name in cols
            assert cols[name]["nullable"] is True
        db.add(Player(id=1, name="A"))
        db.commit()
        p = db.get(Player, 1)
        assert (p.rank_tier, p.leaderboard_rank, p.rank_fetched_at) == (None, None, None)

    def test_run_migrations_adds_rank_columns_to_existing_players_table(self):
        """A numbered migration adds the three rank columns to an existing `players` table."""
        from migrate import MIGRATIONS, run_migrations
        assert "040_players_rank" in [m for m, _ in MIGRATIONS]
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, avatar_url TEXT, "
                              "is_active INTEGER NOT NULL DEFAULT 1)"))
            conn.execute(text("INSERT INTO players (id, name) VALUES (5, 'Old')"))
            conn.commit()
        run_migrations(engine)
        with engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(players)"))}
            row = conn.execute(text("SELECT rank_tier, leaderboard_rank, rank_fetched_at FROM players "
                                    "WHERE id = 5")).one()
        assert {"rank_tier", "leaderboard_rank", "rank_fetched_at"} <= cols
        assert tuple(row) == (None, None, None)
        run_migrations(engine)  # idempotent

    def test_parse_rank_valid_tiers_and_leaderboard(self):
        """`parse_rank` returns (54, None) for Legend 4, (80, 123) for Immortal #123, and keeps 10 and 75."""
        parse = player_rank.parse_rank
        assert parse({"rank_tier": 54}) == (54, None)
        assert parse({"rank_tier": 80, "leaderboard_rank": 123}) == (80, 123)
        assert parse({"rank_tier": 80, "leaderboard_rank": None}) == (80, None)
        assert parse({"rank_tier": 10}) == (10, None)
        assert parse({"rank_tier": 75, "leaderboard_rank": None}) == (75, None)

    def test_parse_rank_out_of_range_or_invalid_tier_is_none(self):
        """A `rank_tier` outside 10-80 (0, 9, 81, 95), null or a string is parsed as None."""
        parse = player_rank.parse_rank
        for bad in (0, 9, 81, 95, None, "54", "abc", 54.0, True):
            assert parse({"rank_tier": bad, "leaderboard_rank": 5}) == (None, None), bad
        assert parse({}) == (None, None)
        assert parse(None) == (None, None)

    def test_parse_rank_leaderboard_ignored_unless_immortal(self):
        """`leaderboard_rank` is kept only for a valid positive place on an Immortal (80) tier."""
        parse = player_rank.parse_rank
        assert parse({"rank_tier": 75, "leaderboard_rank": 12}) == (75, None)
        assert parse({"rank_tier": 80, "leaderboard_rank": 0}) == (80, None)
        assert parse({"rank_tier": 80, "leaderboard_rank": -3}) == (80, None)
        assert parse({"rank_tier": 80, "leaderboard_rank": "12"}) == (80, None)
        assert parse({"rank_tier": 80, "leaderboard_rank": 1}) == (80, 1)

    def test_medal_name_formats_medal_and_stars(self):
        """`medal_name`: 54 -> "Legend 4", 80 -> "Immortal", (80, 123) -> "Immortal #123", None -> None."""
        name = player_rank.medal_name
        assert name(54) == "Legend 4"
        assert name(10) == "Herald"
        assert name(11) == "Herald 1"
        assert name(75) == "Divine 5"
        assert name(80) == "Immortal"
        assert name(80, 123) == "Immortal #123"
        assert name(None) is None

    def test_add_player_stores_rank_from_opendota_response(self, db, monkeypatch):
        """Adding a single player stores `rank_tier`, `leaderboard_rank` and `rank_fetched_at` from the response it fetches."""
        monkeypatch.setattr(admin_players, "opendota_get_json",
                            _fake_opendota({101: _od_player(101, 54)}))
        before = int(time.time())
        out = admin_players.add_player(admin_players.AddPlayerBody(player_id=101), db=db, admin=ADMIN)
        assert out == {"id": 101, "name": "P101"}
        p = db.get(Player, 101)
        assert (p.rank_tier, p.leaderboard_rank) == (54, None)
        assert p.rank_fetched_at is not None and p.rank_fetched_at >= before

    def test_bulk_add_players_stores_rank_from_opendota_response(self, db, monkeypatch):
        """Bulk add stores each player's `rank_tier` and `leaderboard_rank` from the response it fetches."""
        monkeypatch.setattr(admin_players, "opendota_get_json", _fake_opendota({
            201: _od_player(201, 80, 42), 202: _od_player(202, None), 203: _od_player(203, 33),
        }))
        lines = [json.loads(l) for l in admin_players._bulk_add_stream(["201", "202", "203"], db, ADMIN)]
        assert lines[-1]["added"] == 3
        assert (db.get(Player, 201).rank_tier, db.get(Player, 201).leaderboard_rank) == (80, 42)
        assert (db.get(Player, 202).rank_tier, db.get(Player, 202).leaderboard_rank) == (None, None)
        assert db.get(Player, 203).rank_tier == 33
        assert all(db.get(Player, pid).rank_fetched_at for pid in (201, 202, 203))

    def test_enrich_players_stores_rank(self, db, monkeypatch):
        """`enrich_players` stores the rank from the profile response and sets `rank_fetched_at`."""
        db.add(Player(id=301, name=None, avatar_url=None))
        db.commit()
        _use_db(monkeypatch, db, {301: _od_player(301, 62)})
        assert enrich.enrich_players() == 1
        p = db.get(Player, 301)
        assert p.name == "P301"
        assert p.rank_tier == 62 and p.leaderboard_rank is None
        assert p.rank_fetched_at is not None

    def test_run_profile_enrichment_refreshes_only_stale_ranks(self, db, monkeypatch):
        """The rank phase refreshes players whose `rank_fetched_at` is null or older than the cooldown, and skips fresh ones."""
        now = int(time.time())
        db.add_all([
            Player(id=1, name="never", is_active=True),
            Player(id=2, name="stale", is_active=True, rank_tier=41, rank_fetched_at=now - _cooldown_secs() - 60),
            Player(id=3, name="fresh", is_active=True, rank_tier=41, rank_fetched_at=now - 60),
            Player(id=4, name="removed", is_active=False),
        ])
        db.commit()
        calls = []
        _use_db(monkeypatch, db, {i: _od_player(i, 55) for i in (1, 2, 3, 4)}, calls)
        result = enrich.run_profile_enrichment(batch_size=10)
        assert result["rank_updated"] == 2
        assert db.get(Player, 1).rank_tier == 55
        assert db.get(Player, 2).rank_tier == 55
        assert db.get(Player, 3).rank_tier == 41  # fresh: not refetched
        assert db.get(Player, 4).rank_tier is None  # not in the pool
        player_calls = [c for c in calls if "/players/" in c]
        assert sorted(player_calls) == sorted([f"{enrich.OPEN_DOTA_URL}/players/{i}" for i in (1, 2)])

    def test_run_profile_enrichment_includes_players_without_matches(self, db, monkeypatch):
        """The rank phase covers every active pool player, including players with no ingested matches."""
        db.add_all([Player(id=11, name="no matches", is_active=True),
                    Player(id=12, name="has matches", is_active=True)])
        db.add(Team(id=7, name="T"))
        db.flush()
        db.add(PlayerMatchStats(player_id=12, match_id=1, team_id=7, fantasy_points=5.0))
        db.commit()
        _use_db(monkeypatch, db, {11: _od_player(11, 23), 12: _od_player(12, 80, 7)})
        monkeypatch.setattr(enrich, "crawl_player_facts", lambda *a, **k: None)
        result = enrich.run_profile_enrichment(batch_size=5)
        assert result["rank_updated"] == 2
        assert db.get(Player, 11).rank_tier == 23
        assert (db.get(Player, 12).rank_tier, db.get(Player, 12).leaderboard_rank) == (80, 7)

    def test_run_profile_enrichment_reports_rank_updated_count(self, db, monkeypatch):
        """`run_profile_enrichment` and `POST /admin/enrich-profiles` return `rank_updated`."""
        db.add_all([Player(id=21, name="a", is_active=True), Player(id=22, name="b", is_active=True)])
        db.commit()
        _use_db(monkeypatch, db, {21: _od_player(21, 44), 22: _od_player(22, 45)})
        result = enrich.run_profile_enrichment(batch_size=1)
        assert result == {"enriched": 0, "skipped": 0, "errors": 0, "rank_updated": 1}
        route = admin_ingest.admin_enrich_profiles(db=db, admin=ADMIN)
        assert route["rank_updated"] == 1
        assert {db.get(Player, 21).rank_tier, db.get(Player, 22).rank_tier} == {44, 45}

    def test_run_profile_enrichment_null_rank_from_opendota_clears_rank(self, db, monkeypatch):
        """A null rank from OpenDota is stored as null (medal hidden) and `rank_fetched_at` is set."""
        old = int(time.time()) - _cooldown_secs() - 60
        db.add(Player(id=31, name="private", is_active=True, rank_tier=80, leaderboard_rank=9, rank_fetched_at=old))
        db.commit()
        _use_db(monkeypatch, db, {31: _od_player(31, None, None)})
        result = enrich.run_profile_enrichment(batch_size=5)
        p = db.get(Player, 31)
        assert result["rank_updated"] == 1
        assert (p.rank_tier, p.leaderboard_rank) == (None, None)
        assert p.rank_fetched_at > old

    def test_run_profile_enrichment_failed_request_keeps_previous_rank(self, db, monkeypatch):
        """A failed OpenDota request keeps the previous rank and timestamp, so the player is retried next cycle."""
        old = int(time.time()) - _cooldown_secs() - 60
        db.add(Player(id=41, name="flaky", is_active=True, rank_tier=52, leaderboard_rank=None, rank_fetched_at=old))
        db.commit()
        _use_db(monkeypatch, db, {41: None})
        result = enrich.run_profile_enrichment(batch_size=5)
        p = db.get(Player, 41)
        assert result["rank_updated"] == 0
        assert (p.rank_tier, p.rank_fetched_at) == (52, old)

    @pytest.mark.parametrize("body", [{}, {"profile": None}, {"error": "rate limit"}])
    def test_run_profile_enrichment_empty_body_keeps_previous_rank(self, db, monkeypatch, body):
        """An empty or error body (no profile) is a failed request, not "unranked": the old rank stays."""
        old = int(time.time()) - _cooldown_secs() - 60
        db.add(Player(id=42, name="empty", is_active=True, rank_tier=63, leaderboard_rank=None, rank_fetched_at=old))
        db.commit()
        _use_db(monkeypatch, db, {42: body})
        result = enrich.run_profile_enrichment(batch_size=5)
        p = db.get(Player, 42)
        assert result["rank_updated"] == 0
        assert (p.rank_tier, p.rank_fetched_at) == (63, old)

    def test_add_player_out_of_range_rank_tier_stored_as_null(self, db, monkeypatch):
        """A `rank_tier` outside 10-80 in the add-player response is stored as null."""
        monkeypatch.setattr(admin_players, "opendota_get_json",
                            _fake_opendota({102: _od_player(102, 95, 3)}))
        admin_players.add_player(admin_players.AddPlayerBody(player_id=102), db=db, admin=ADMIN)
        p = db.get(Player, 102)
        assert (p.rank_tier, p.leaderboard_rank) == (None, None)
        assert p.rank_fetched_at is not None


# ---------------------------------------------------------------------------
# Story 2: See a Player's Medal in the Player Popup
# ---------------------------------------------------------------------------

class TestPlayerPopupMedal:

    def test_get_player_returns_rank_fields(self, db):
        """`GET /players/{id}` returns `rank_tier`, `leaderboard_rank` and `rank_fetched_at`."""
        db.add(Player(id=51, name="R", is_active=True, rank_tier=80, leaderboard_rank=123, rank_fetched_at=1700000000))
        db.commit()
        out = players_router.get_player(51, db=db)
        assert (out["rank_tier"], out["leaderboard_rank"], out["rank_fetched_at"]) == (80, 123, 1700000000)

    def test_get_player_without_rank_returns_nulls(self, db):
        """`GET /players/{id}` for an unranked player returns null rank fields."""
        db.add(Player(id=52, name="U", is_active=True))
        db.commit()
        out = players_router.get_player(52, db=db)
        assert (out["rank_tier"], out["leaderboard_rank"], out["rank_fetched_at"]) == (None, None, None)

    def test_rank_medal_html_shows_medal_name_with_stars(self):
        """`rankMedalHtml(54)` renders a `.rank-medal` badge with the text "Legend 4"."""
        out = _medal_js('out.h = rankMedalHtml(54);')
        assert 'class="rank-medal rank-medal--legend"' in out["h"]
        assert ">Legend 4<" in out["h"]
        assert out["h"].count("★") == 4

    def test_rank_medal_html_immortal_with_leaderboard_place(self):
        """`rankMedalHtml(80, 123)` shows "Immortal" with "#123"."""
        out = _medal_js('out.h = rankMedalHtml(80, 123); out.n = rankMedalHtml(80, null);')
        assert "rank-medal--immortal" in out["h"] and ">Immortal #123<" in out["h"]
        assert ">Immortal<" in out["n"] and "#" not in re.sub(r"&#\d+;", "", out["n"])
        assert "★" not in out["h"]

    def test_popup_header_includes_rank_medal(self):
        """The popup header in app-players.js renders the medal badge next to the team name."""
        body = _fn_body(_read(PLAYERS_JS), "openPlayerModal")
        call = "rankMedalHtml(p.rank_tier, p.leaderboard_rank, p.rank_fetched_at)"
        assert call in body
        team = body.index('document.getElementById("playerModalTeam").innerHTML = p.team_id')
        medal = body.index(call)
        assert team < medal
        assert 'getElementById("playerModalTeam").insertAdjacentHTML("beforeend"' in body[team:medal]

    def test_rank_medal_html_has_approximate_rank_tooltip_with_date(self):
        """The badge's title says "Last known rank from OpenDota" with the fetch date."""
        out = _medal_js('out.h = rankMedalHtml(54, null, 1700000000);'
                        'out.d = new Date(1700000000 * 1000).toLocaleDateString();'
                        'out.n = rankMedalHtml(54);')
        assert f'title="Last known rank from OpenDota, {out["d"]}"' in out["h"]
        assert 'title="Last known rank from OpenDota"' in out["n"]

    def test_rank_medal_html_null_rank_renders_nothing(self):
        """`rankMedalHtml(null)` returns an empty string: no medal and no empty space."""
        out = _medal_js('out.a = rankMedalHtml(null); out.b = rankMedalHtml(undefined, 5);'
                        'out.c = rankMedalHtml(95); out.d = rankMedalHtml("x");')
        assert out == {"a": "", "b": "", "c": "", "d": ""}

    def test_rank_medal_html_has_screen_reader_text(self):
        """The medal has a text equivalent for screen readers (`aria-label` or visible text)."""
        out = _medal_js('out.h = rankMedalHtml(33); out.i = rankMedalHtml(80, 7);')
        assert 'role="img"' in out["h"] and 'aria-label="Rank: Crusader 3"' in out["h"]
        assert 'aria-label="Rank: Immortal #7"' in out["i"]
        assert 'class="rank-medal-icon" aria-hidden="true"' in out["h"]

    def test_style_css_medal_colours_are_tokens(self):
        """Medal colours are `--medal-herald` ... `--medal-immortal` tokens in style.css, no raw hex in `.rank-medal` rules."""
        tokens = _read(TOKENS_CSS)
        css = _read(STYLE_CSS)
        for key in MEDAL_KEYS:
            assert re.search(rf"--medal-{key}:\s*#[0-9a-fA-F]{{6}};", tokens), key
            assert f"var(--medal-{key})" in css
        rules = _css_blocks(css, r"\.rank-medal|\.reveal-rank")
        assert rules
        for sel, rule in rules:
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rule), sel
            assert "rgb" not in rule, sel
        assert css.index(".rank-medal {") < css.index("GUIDED TOUR (issue #144)")


# ---------------------------------------------------------------------------
# Story 3: See the Medal on a Card
# ---------------------------------------------------------------------------

class TestCardMedal:

    def test_roster_cards_include_rank_fields(self, db):
        """The My Team card list includes each card player's `rank_tier` and `leaderboard_rank`."""
        _seed_card(db, {"id": 61, "name": "Ranked", "rank_tier": 72, "leaderboard_rank": None})
        out = cards_router._build_roster_response(db, 1, None)
        card = (out["active"] + out["bench"])[0]
        assert (card["rank_tier"], card["leaderboard_rank"]) == (72, None)

    def test_draw_reveal_card_includes_rank_fields(self, db):
        """The draw reveal card data includes the player's `rank_tier` and `leaderboard_rank`."""
        db.add(User(id=1, username="drawer", tokens=3))
        db.add(Player(id=62, name="Immortal", is_active=True, rank_tier=80, leaderboard_rank=55))
        db.commit()
        out = cards_router.draw_card(db=db, current_user={"user_id": 1, "username": "drawer"})
        assert out["player_id"] == 62
        assert (out["rank_tier"], out["leaderboard_rank"]) == (80, 55)

    def test_card_viewer_data_includes_rank_fields(self, db):
        """The card viewer data includes the player's `rank_tier` and `leaderboard_rank`."""
        card = _seed_card(db, {"id": 63, "name": "Viewer", "rank_tier": 45, "leaderboard_rank": None},
                          is_active=False, slot_index=None)
        viewer = cards_router.get_card(card.id, db=db, current_user={"user_id": 1})
        assert (viewer["rank_tier"], viewer["leaderboard_rank"]) == (45, None)
        bench = cards_router._build_roster_response(db, 1, None)["bench"]
        assert (bench[0]["rank_tier"], bench[0]["leaderboard_rank"]) == (45, None)

    def test_card_lists_unranked_player_returns_null_rank(self, db):
        """A card for a player with no rank returns null `rank_tier` and `leaderboard_rank`."""
        card = _seed_card(db, {"id": 64, "name": "Unranked"})
        roster = cards_router._build_roster_response(db, 1, None)
        c = (roster["active"] + roster["bench"])[0]
        assert "rank_tier" in c and (c["rank_tier"], c["leaderboard_rank"]) == (None, None)
        viewer = cards_router.get_card(card.id, db=db, current_user={"user_id": 1})
        assert (viewer["rank_tier"], viewer["leaderboard_rank"]) == (None, None)

    def test_card_viewer_shows_medal_under_card_image(self):
        """app-cards.js renders the medal badge and name under the card image in the card viewer."""
        js = _read(CARDS_JS)
        helper = _fn_body(js, "_renderRevealRank")
        assert "rankMedalHtml(card.rank_tier, card.leaderboard_rank)" in helper
        assert 'getElementById("revealRank")' in helper
        assert "_renderRevealRank(card);" in _fn_body(js, "showCard")
        html = _read(INDEX_HTML)
        img = html.index('id="revealCardImg"')
        rank = html.index('id="revealRank"')
        assert img < rank < html.index('id="revealDestination"')

    def test_card_viewer_null_rank_shows_no_medal(self):
        """The card viewer shows no medal for a card whose player has no rank."""
        node = _node()
        if not node:
            pytest.skip("node not installed")
        js = _read(CARDS_JS)
        script = "\n".join([
            "const el = { innerHTML: 'stale' };",
            "const document = { getElementById: id => id === 'revealRank' ? el : null };",
            "const calls = [];",
            "function rankMedalHtml(t, lb) { calls.push([t, lb]); return t == null ? '' : '<b>m</b>'; }",
            _fn_body(js, "_renderRevealRank") + "\n}\n",
            "_renderRevealRank({ rank_tier: null, leaderboard_rank: null });",
            "const a = el.innerHTML;",
            "_renderRevealRank({ rank_tier: 54 });",
            "console.log(JSON.stringify({ a, b: el.innerHTML, calls }));",
        ])
        res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout)
        assert out["a"] == "" and out["b"] == "<b>m</b>"
        hidden = [body for sel, body in _css_blocks(_read(STYLE_CSS), r"\.reveal-rank:empty")]
        assert hidden and "display: none" in hidden[0]

    def test_medal_uses_no_dota_cdn_image_or_league_name(self):
        """The medal badge loads no image from a Dota CDN and shows no league name."""
        js = _read(GLOBALS_JS)
        body = _fn_body(js, "rankMedalHtml") + js[js.index("const _RANK_MEDALS"):js.index("function rankMedalHtml(")]
        for banned in ("<img", "url(", "cdn", "steamstatic", "dota2.com", "valve", "league"):
            assert banned not in body.lower(), banned
        for sel, rule in _css_blocks(_read(STYLE_CSS), r"\.rank-medal|\.reveal-rank"):
            assert "url(" not in rule, sel
        out = _medal_js("out.all = [10,21,32,43,54,65,76,80].map(t => rankMedalHtml(t, 3)).join('');")
        assert "<img" not in out["all"] and "league" not in out["all"].lower()
