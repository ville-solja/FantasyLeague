"""
Tests for plan-issue-151-weekly-report-aesthetics.md (resolves GitHub issue #151).

The Weekly Report popup becomes a wide, two-column view under the week tabs:
"My roster" (left, ~480 px) and "Match results" (right), each with a fixed header
and its own `.k-scroll` body. `_build_week_summary` gains a `roster` block (built
from `routers.cards._build_roster_response`, locked-week branch) with per-card
`games`, and result players gain `card_points`. A new "recap is ready" popup is
driven by `WeeklySummarySeen.last_prompted_week_id` (migration 030),
`show_prompt` / `latest_week` on `GET /weekly-summary`, and
`POST /weekly-summary/prompted`.

  Story 1: Side-by-Side Weekly Report
  Story 2: My Roster Panel
  Story 3: Your Cards in the Match Results
  Story 4: Links Work as Everywhere Else
  Story 5: Reveal and Substitution States
  Story 6: New Recap Popup

Approach notes for the implementer:

- `db` fixture from conftest (in-memory SQLite). `import models` at module level so
  every table is registered before the fixture runs (lessons-learned 2026-10-01).
- Seeding: users / players / teams / cards / weeks / matches / stats / weights, then
  lock the week (`weeks._snapshot_week(db, week)`) and call
  `card_points.rebuild_all(db)` so stored `card_match_points` rows exist — every
  reader sums stored rows (see `_seed` in test_issue_129_automatic_bench_substitution.py,
  which also has the canonical substitution scenario: active A played, B 0 matches,
  bench C (slot_index 0) and D (slot_index 1) played -> B subbed_out, C subbed_in).
  Run `weeks.run_substitutions(db, week)` (with the clock patched past the delay)
  for the substitution tests.
- Backend readers are called directly: `routers.weekly_summary._build_week_summary(
  db, week, revealed, user_id)`, `list_weekly_summaries(db=db, current_user=...)`,
  `mark_weekly_summary_seen(...)`, the new prompted endpoint function,
  `routers.cards._build_roster_response(db, user_id, week_id)`,
  `routers.leaderboard.weekly_leaderboard(week_id=..., db=db)`.
- Points are rounded with `scoring.display_points` (#149): compare reader output to
  `display_points(exact_sum)`, not raw sums.
- Auth tests: minimal FastAPI app with the weekly_summary + auth routers on a
  StaticPool engine (see `session_env` in test_issue_117_longer_sessions.py); never
  import or reload `main` in-process.
- Migration tests: legacy engine and `migrate.run_migrations`, recording earlier
  migrations first (see `_legacy_engine` in test_issue_129_...).
- Frontend criteria are static text checks of `frontend/index.html`,
  `frontend/style.css`, `frontend/app-weekly-summary.js`.

Manual-only (need a real browser, see the plan's Verification section): columns
scrolling independently, scroll positions preserved after closing a popup, no
horizontal scroll at 375 px, focus trap behaviour at runtime.

STATUS: implemented.

Run with: cd backend && python -m pytest tests/test_issue_151_weekly_report_aesthetics.py -v
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

import models  # noqa: F401  (registers every table on Base before the db fixture runs)
import card_points
import migrate
import weeks
from auth import hash_password
from database import Base
from models import (
    Card, CardMatchPoints, Match, Player, PlayerMatchStats, Team, User, Week,
    WeeklySummary, WeeklySummarySeen, Weight,
)
from routers.cards import _build_roster_response
from routers.leaderboard import weekly_leaderboard
from routers.weekly_summary import (
    _build_week_summary, _group_into_series, list_weekly_summaries,
    mark_weekly_summary_prompted, mark_weekly_summary_seen,
)
from scoring import display_points, fantasy_score

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
_STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")
_APP_WEEKLY_SUMMARY_JS_PATH = os.path.join(_FRONTEND_DIR, "app-weekly-summary.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _css_blocks(css, selector_re):
    """(selector, body) for every rule whose selector matches selector_re."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if re.search(selector_re, m.group(1))]


def _css_rule(css, selector):
    """Body of the first rule whose selector is exactly `selector`."""
    for sel, body in _css_blocks(css, re.escape(selector)):
        if sel == selector:
            return body
    raise AssertionError(f"no CSS rule for {selector}")


def _media_body(css, query):
    start = css.index(f"@media ({query})")
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1:j]
    raise AssertionError(query)


def _fn_body(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start)]


def _modal_markup(html, modal_id, next_marker):
    start = html.rindex("<div", 0, html.index(f'id="{modal_id}"'))
    return html[start:html.index(next_marker, start)]


def _summary_markup():
    return _modal_markup(_read(_INDEX_HTML_PATH), "weeklySummaryModal", 'id="weeklyRecapPrompt"')


def _prompt_markup():
    return _modal_markup(_read(_INDEX_HTML_PATH), "weeklyRecapPrompt", 'id="loginModal"')


# ---------------------------------------------------------------------------
# Seeding (canonical #129 scenario: A played, B 0 matches, bench C then D played)
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "kills": 0.3, "gold_per_min": 0.002,
    "death_pool": 3.0, "death_deduction": 0.3, "mvp_bonus_pct": 10.0,
    "rarity_common": 0.0, "rarity_rare": 1.0, "rarity_epic": 2.0, "rarity_legendary": 3.0,
    "modifier_count_common": 0.0, "modifier_count_rare": 1.0, "modifier_count_epic": 2.0,
    "modifier_count_legendary": 3.0, "modifier_bonus_pct": 10.0, "team_booster_cost": 3.0,
}
A, B, C, D, E = 101, 102, 103, 104, 105
HALLA, KUURA, VARJO = 1, 2, 3
WEEK_END = 1000

# (match_id, start, radiant, dire, radiant_win, excluded, {pid: (team, kills, deaths, gpm, mvp)})
_BASE_MATCHES = [
    (1, 100, HALLA, KUURA, True, False,
     {A: (HALLA, 5, 2, 437, False), C: (HALLA, 3, 1, 391, False),
      D: (HALLA, 6, 0, 512, False), E: (KUURA, 2, 4, 350, False)}),
    (2, 200, HALLA, KUURA, False, False,
     {A: (HALLA, 2, 1, 403, True), C: (HALLA, 4, 0, 455, False),
      D: (HALLA, 1, 3, 377, False), E: (KUURA, 7, 0, 520, False)}),
]


def _add_match(db, match_id, start, radiant, dire, radiant_win, excluded, players):
    db.add(Match(match_id=match_id, radiant_team_id=radiant, dire_team_id=dire,
                 start_time=start, radiant_win=radiant_win, league_id=1,
                 excluded_from_scoring=excluded))
    for pid, (team, kills, deaths, gpm, mvp) in players.items():
        stats = {"kills": kills, "deaths": deaths, "gold_per_min": gpm}
        db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=team,
                                fantasy_points=round(fantasy_score(stats, _WEIGHTS), 4),
                                is_mvp=mvp, **stats))


def _seed(db, matches=None, extra_matches=(), substitute=False, b_plays=False):
    """alice (1): active A (card 1, slot 0), B (card 2, slot 1); bench C (card 3),
    D (card 4). Week 1 locked with a generated report."""
    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.add(User(id=1, username="alice", email="a@test", password_hash=hash_password("pw-123456"),
                tokens=5))
    db.add(Team(id=HALLA, name="Halla"))
    db.add(Team(id=KUURA, name="Kuura"))
    db.add(Team(id=VARJO, name="Varjo"))
    for pid in (A, B, C, D, E):
        db.add(Player(id=pid, name=f"P{pid}", is_active=True))
    for cid, pid, active, slot in ((1, A, True, 0), (2, B, True, 1), (3, C, False, 0), (4, D, False, 1)):
        db.add(Card(id=cid, player_id=pid, owner_id=1, card_type="rare" if cid == 1 else "common",
                    is_active=active, slot_index=slot))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=WEEK_END, is_locked=False))
    db.add(Week(id=2, label="Week 2", start_time=1001, end_time=2000, is_locked=False))
    matches = [list(m) for m in (matches or _BASE_MATCHES)]
    if b_plays:
        matches[0][6] = {**matches[0][6], B: (HALLA, 1, 1, 300, False)}
    for m in list(matches) + list(extra_matches):
        _add_match(db, *m)
    db.commit()
    card_points.rebuild_all(db)
    week = db.get(Week, 1)
    weeks._snapshot_week(db, week)
    week.is_locked = True
    db.add(WeeklySummary(week_id=1, generated_at=int(time.time())))
    db.commit()
    if substitute:
        weeks.run_substitutions(db, week)
        db.commit()
    return week


def _summary(db, revealed=True):
    return _build_week_summary(db, db.get(Week, 1), revealed, 1)


def _cmp(db, card_id, match_id):
    row = db.query(CardMatchPoints).filter_by(card_id=card_id, match_id=match_id).one()
    return row.points


def _players(summary):
    for s in summary["series"]:
        for m in s["matches"]:
            for p in m.get("players", []):
                yield m["match_id"], p


def _user():
    return {"user_id": 1, "username": "alice", "is_admin": False}


# ---------------------------------------------------------------------------
# Story 1: Side-by-Side Weekly Report
# ---------------------------------------------------------------------------
class TestSideBySideWeeklyReport:
    def test_weekly_summary_modal_has_two_column_markup(self):
        """index.html: #weeklySummaryModal carries class `weekly-summary-modal` and holds a
        `.weekly-summary-columns` container with two <section> elements, each with a header
        div and a `div.k-scroll` body; the bodies are #weeklySummaryRoster (first) and
        #weeklySummaryContent (second)."""
        html = _summary_markup()
        assert 'class="modal weekly-summary-modal k-scroll"' in html
        cols = html[html.index('class="weekly-summary-columns"'):]
        sections = re.findall(r"<section\b(.*?)</section>", cols, re.S)
        assert len(sections) == 2
        for sec, body_id in zip(sections, ("weeklySummaryRoster", "weeklySummaryContent")):
            assert 'class="weekly-summary-col-head"' in sec
            assert re.search(rf'<div class="k-scroll[^"]*" id="{body_id}"', sec)
        assert cols.index('id="weeklySummaryRoster"') < cols.index('id="weeklySummaryContent"')

    def test_week_tabs_are_the_only_tabs_in_weekly_summary_modal(self):
        """index.html / app-weekly-summary.js: the week tabs row is the only tab row in the
        popup — no roster/results view-switching tabs exist (no second tablist inside
        #weeklySummaryModal)."""
        html = _summary_markup()
        assert html.count('id="weeklySummaryTabs"') == 1
        assert 'role="tablist"' not in html and 'role="tab"' not in html
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert js.count("className = 'weekly-summary-tab-btn'") == 1
        assert "tablist" not in js

    def test_weekly_summary_modal_has_no_inline_overflow_or_height_styles(self):
        """Failure path: index.html — #weeklySummaryModal and its descendants contain no
        inline `style=` attribute setting `overflow`, `max-height` or `height`; these moved to
        classes in style.css."""
        styles = re.findall(r'style="([^"]*)"', _summary_markup())
        assert not [s for s in styles if re.search(r"overflow|height", s)]

    def test_weekly_summary_modal_size_rules(self):
        """style.css: `.weekly-summary-modal` sets `width: min(1280px, ...)` (at most 1280 px)
        and `max-height: 85vh`, with `display: flex; flex-direction: column`."""
        body = _css_rule(_read(_STYLE_CSS_PATH), ".weekly-summary-modal")
        assert re.search(r"width:\s*min\(1280px,", body)
        assert re.search(r"max-height:\s*85vh", body)
        assert re.search(r"display:\s*flex", body)
        assert re.search(r"flex-direction:\s*column", body)

    def test_weekly_summary_columns_grid_480px_and_rest(self):
        """style.css: `.weekly-summary-columns` is `display: grid` with
        `grid-template-columns: 480px minmax(0, 1fr)` and `min-height: 0`."""
        body = _css_rule(_read(_STYLE_CSS_PATH), ".weekly-summary-columns")
        assert re.search(r"display:\s*grid", body)
        assert re.search(r"grid-template-columns:\s*480px minmax\(0, 1fr\)", body)
        assert re.search(r"min-height:\s*0", body)

    def test_column_headers_show_titles_and_counts(self):
        """index.html / app-weekly-summary.js: roster column header text includes "My roster",
        the counted-cards and substitutions count, and the week total (`roster.week_total`);
        results column header includes "Match results" and the number of series and games."""
        html = _summary_markup()
        assert ">My roster<" in html and ">Match results<" in html
        assert 'id="weeklySummaryRosterTotal"' in html and 'id="weeklySummaryRosterMeta"' in html
        assert 'id="weeklySummaryResultsMeta"' in html
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        header = _fn_body(js, "_renderWeeklySummaryRosterHeader")
        assert "roster.week_total" in header and "Week total" in header
        assert "counted" in header and "substitution" in header
        render = _fn_body(js, "renderWeeklySummaryContent")
        assert "weeklySummaryResultsMeta" in render
        assert "series ·" in render and "'games'" in render

    def test_k_scroll_rules_use_tokens_only(self):
        """style.css: `.k-scroll` rules set a thin scrollbar (`scrollbar-width: thin`), thumb
        `var(--border)` and `var(--fg-dim)` on hover, transparent track, `var(--r-xs)`
        corners, `scrollbar-gutter: stable`, and >= 12 px spacing between content and
        scrollbar (padding-right / padding-inline-end)."""
        css = _read(_STYLE_CSS_PATH)
        base = _css_rule(css, ".k-scroll")
        assert "scrollbar-width: thin" in base
        assert "scrollbar-color: var(--border) transparent" in base
        assert "scrollbar-gutter: stable" in base
        pad = re.search(r"padding-(?:right|inline-end):\s*([^;]+);", base).group(1).strip()
        assert pad == "var(--s-3)" or int(pad.rstrip("px")) >= 12  # --s-3 is 12px
        assert "--s-3: 12px" in _read(os.path.join(_FRONTEND_DIR, "colors_and_type.css"))
        assert "var(--fg-dim)" in _css_rule(css, ".k-scroll:hover")
        assert "transparent" in _css_rule(css, ".k-scroll::-webkit-scrollbar-track")
        thumb = _css_rule(css, ".k-scroll::-webkit-scrollbar-thumb")
        assert "var(--border)" in thumb and "var(--r-xs)" in thumb
        assert "var(--fg-dim)" in _css_rule(css, ".k-scroll::-webkit-scrollbar-thumb:hover")

    def test_k_scroll_rules_contain_no_hardcoded_colours(self):
        """Failure path: style.css — no `.k-scroll` rule block (incl. ::-webkit-scrollbar
        pseudo-elements) contains a hex colour (`#[0-9a-fA-F]{3,8}`), `rgb(` or `hsl(`."""
        blocks = _css_blocks(_read(_STYLE_CSS_PATH), r"\.k-scroll")
        assert len(blocks) >= 5
        for sel, body in blocks:
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", body), sel

    def test_card_grid_uses_k_scroll_instead_of_own_scrollbar_rules(self):
        """style.css has no `.card-grid::-webkit-scrollbar` (or `.card-grid` scrollbar-color)
        rules any more, and the element(s) with class `card-grid` in index.html / JS also carry
        the `k-scroll` class."""
        css = _read(_STYLE_CSS_PATH)
        assert ".card-grid::-webkit-scrollbar" not in css
        for sel, body in _css_blocks(css, r"\.card-grid"):
            assert "scrollbar-color" not in body and "scrollbar-width" not in body, sel
        classes = re.findall(r'class="([^"]*\bcard-grid\b[^"]*)"', _read(_INDEX_HTML_PATH))
        assert len(classes) == 2
        assert all("k-scroll" in c.split() for c in classes)
        for name in os.listdir(_FRONTEND_DIR):
            if name.endswith(".js"):
                assert not re.search(r"""className\s*=\s*['"]card-grid['"]""",
                                     _read(os.path.join(_FRONTEND_DIR, name))), name

    def test_columns_stack_below_1100px(self):
        """style.css: a `@media (max-width: 1100px)` block sets `.weekly-summary-columns` to a
        single column (roster first), the column bodies to `overflow: visible`, and lets the
        modal itself scroll (`overflow-y: auto`)."""
        media = _media_body(_read(_STYLE_CSS_PATH), "max-width: 1100px")
        assert re.search(r"\.weekly-summary-columns\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);", media)
        assert re.search(r"\.weekly-summary-col-body\s*\{[^}]*overflow:\s*visible", media)
        assert re.search(r"\.weekly-summary-modal\s*\{[^}]*overflow-y:\s*auto", media)
        # Roster first: its section precedes the results section in the markup, and no
        # `order` reshuffles them.
        html = _summary_markup()
        assert html.index("weekly-summary-col-roster") < html.index("weekly-summary-col-results")
        assert "order:" not in media

    def test_reveal_footer_docked_after_columns(self):
        """index.html: the "Reveal results" footer element sits after `.weekly-summary-columns`
        inside #weeklySummaryModal, outside both `.k-scroll` bodies, so it stays under both
        columns."""
        html = _summary_markup()
        cols_end = html.rindex("</section>")
        footer = html.index('id="weeklySummaryRevealFooter"')
        assert footer > cols_end
        between = html[cols_end:footer]
        assert between.count("</div>") == 1  # only .weekly-summary-columns closes in between
        assert "Reveal results" in html[footer:]


# ---------------------------------------------------------------------------
# Story 2: My Roster Panel
# ---------------------------------------------------------------------------
_CARD_KEYS = {"card_id", "card_type", "player_id", "player_name", "avatar_url", "team_id",
              "team_name", "counted", "subbed_in", "subbed_out", "subbed_in_for", "modifiers",
              "week_points", "games"}


class TestMyRosterPanel:
    def test_build_week_summary_roster_cards_match_roster_response_order(self, db):
        """Revealed week, no substitution: `_build_week_summary(...)["roster"]["cards"]` card_ids
        equal `_build_roster_response(db, user_id, week_id)["active"]` card_ids in the same order;
        each card has card_id, card_type, player_id, player_name, avatar_url, team_id,
        team_name, counted, subbed_in, subbed_out, subbed_in_for, modifiers, week_points, games."""
        _seed(db, b_plays=True)
        cards = _summary(db)["roster"]["cards"]
        assert [c["card_id"] for c in cards] == [c["id"] for c in _build_roster_response(db, 1, 1)["active"]]
        assert [c["card_id"] for c in cards] == [1, 2]
        for c in cards:
            assert set(c) == _CARD_KEYS | {"breakdown"}  # breakdown added by issue #152
            assert c["counted"] is True

    def test_build_roster_response_returns_team_id_per_card(self, db):
        """`_build_roster_response` returns `team_id` on every active and bench card (from the
        latest-team subquery), matching the player's team; roster cards in the summary carry it."""
        _seed(db, b_plays=True)
        r = _build_roster_response(db, 1, 1)
        assert {c["id"]: c["team_id"] for c in r["active"] + r["bench"]} == {
            1: HALLA, 2: HALLA, 3: HALLA, 4: HALLA}
        for c in _summary(db)["roster"]["cards"]:
            assert (c["team_id"], c["team_name"]) == (HALLA, "Halla")

    def test_subbed_in_card_takes_replaced_card_slot(self, db):
        """Substitution scenario (B subbed out, C subbed in): in `roster.cards`, C appears at B's
        slot position with `counted: True`, `subbed_in: True` and `subbed_in_for` naming B's
        player."""
        _seed(db, substitute=True)
        cards = _summary(db)["roster"]["cards"]
        assert cards[1]["card_id"] == 3
        assert (cards[1]["counted"], cards[1]["subbed_in"], cards[1]["subbed_in_for"]) == (True, True, f"P{B}")

    def test_subbed_out_card_listed_after_counted_cards(self, db):
        """Substitution scenario: B appears after every counted card in `roster.cards` with
        `subbed_out: True` and `counted: False`; the subbed-out entries keep
        `_build_roster_response`'s `bench` order."""
        _seed(db, substitute=True)
        cards = _summary(db)["roster"]["cards"]
        assert [c["card_id"] for c in cards] == [1, 3, 2]
        assert (cards[2]["subbed_out"], cards[2]["counted"]) == (True, False)
        bench_out = [c["id"] for c in _build_roster_response(db, 1, 1)["bench"] if c["subbed_out"]]
        assert [c["card_id"] for c in cards if c["subbed_out"]] == bench_out

    def test_unused_bench_cards_not_in_roster(self, db):
        """Failure path: bench card D (not subbed in) and any bench card without
        `subbed_out` are absent from `roster.cards`."""
        _seed(db, substitute=True)
        ids = [c["card_id"] for c in _summary(db)["roster"]["cards"]]
        assert 4 not in ids
        _bench = [c for c in _build_roster_response(db, 1, 1)["bench"] if not c["subbed_out"]]
        assert _bench and not {c["id"] for c in _bench} & set(ids)

    def test_no_did_not_play_entries_without_substitution(self, db):
        """Failure path: with no substitution, `roster.cards` contains no card with
        `subbed_out: True` (so the frontend renders no "Did not play" group)."""
        _seed(db)  # B played nothing, but substitutions have not run yet
        cards = _summary(db)["roster"]["cards"]
        assert [c["card_id"] for c in cards] == [1, 2]
        assert not any(c["subbed_out"] for c in cards)

    def test_card_games_rows_fields_and_points(self, db):
        """Each `roster.cards[i].games` row has match_id, start_time, game_number,
        opponent_team_id, opponent_name, won, is_mvp, points, scored; `points` equals
        `display_points` of that card's `card_match_points` row for the match; `won`,
        `is_mvp` and `opponent_team_id` match the seeded Match / PlayerMatchStats."""
        _seed(db)
        card_a = _summary(db)["roster"]["cards"][0]
        games = card_a["games"]
        assert [g["match_id"] for g in games] == [1, 2]
        for g in games:
            assert set(g) == {"match_id", "start_time", "game_number", "opponent_team_id",
                              "opponent_name", "won", "is_mvp", "points", "scored"}
            assert g["points"] == display_points(_cmp(db, 1, g["match_id"]))
            assert g["scored"] is True
            assert (g["opponent_team_id"], g["opponent_name"]) == (KUURA, "Kuura")
        assert [g["won"] for g in games] == [True, False]
        assert [g["is_mvp"] for g in games] == [False, True]
        assert [g["start_time"] for g in games] == [100, 200]

    def test_game_number_follows_series_grouping(self, db):
        """`games[i].game_number` matches the game's position in its series as grouped by
        `_group_into_series` (two games vs the same opponent -> 1 then 2)."""
        extra = [(3, 500, VARJO, HALLA, True, False, {A: (HALLA, 1, 1, 300, False)})]
        _seed(db, extra_matches=extra)
        summary = _summary(db)
        positions = {m["match_id"]: i for s in summary["series"]
                     for i, m in enumerate(s["matches"], start=1)}
        games = summary["roster"]["cards"][0]["games"]
        assert [(g["match_id"], g["game_number"]) for g in games] == [(1, 1), (2, 2), (3, 1)]
        assert all(g["game_number"] == positions[g["match_id"]] for g in games)
        assert games[2]["opponent_team_id"] == VARJO and games[2]["won"] is False
        assert len(_group_into_series([m for s in summary["series"] for m in s["matches"]])) == 2

    def test_won_is_none_when_radiant_win_unknown(self, db):
        """Failure path: a match with `radiant_win = None` yields `won: None` in the game row."""
        extra = [(3, 500, HALLA, VARJO, None, False, {A: (HALLA, 1, 1, 300, False)})]
        _seed(db, extra_matches=extra)
        games = {g["match_id"]: g for g in _summary(db)["roster"]["cards"][0]["games"]}
        assert games[3]["won"] is None
        assert games[1]["won"] is True

    def test_excluded_match_shows_not_scored(self, db):
        """Failure path: a match with `excluded_from_scoring = True` appears in `games` with
        `points: None` and `scored: False`."""
        extra = [(3, 500, HALLA, VARJO, True, True, {A: (HALLA, 9, 0, 700, False)})]
        _seed(db, extra_matches=extra)
        card_a = _summary(db)["roster"]["cards"][0]
        games = {g["match_id"]: g for g in card_a["games"]}
        assert (games[3]["points"], games[3]["scored"]) == (None, False)
        assert card_a["week_points"] == display_points(_cmp(db, 1, 1) + _cmp(db, 1, 2))

    def test_week_total_equals_counted_cards_sum_and_leaderboard(self, db):
        """`roster.week_total` equals `roster_response["combined_value"]`, equals the sum of the
        counted cards' `week_points` (within ~0.1 rounding), and equals the user's `week_points`
        in `weekly_leaderboard(week_id=..., db=db)`; subbed-out card points are not included."""
        _seed(db, substitute=True)
        roster = _summary(db)["roster"]
        assert roster["week_total"] == _build_roster_response(db, 1, 1)["combined_value"]
        counted = sum(c["week_points"] for c in roster["cards"] if c["counted"])
        assert abs(roster["week_total"] - counted) <= 0.1 + 1e-9
        lb = {r["id"]: r["week_points"] for r in weekly_leaderboard(week_id=1, db=db)}
        assert roster["week_total"] == lb[1]
        exact = sum(_cmp(db, cid, mid) for cid in (1, 3) for mid in (1, 2))
        assert roster["week_total"] == display_points(exact)

    def test_roster_html_renders_subbed_in_and_did_not_play_copy(self):
        """app-weekly-summary.js: `_weeklySummaryRosterHtml` exists and contains the "SUBBED IN"
        tag, "From your bench, for", "who did not play this week", the "Did not play" group
        heading and "No matches this week. Replaced by"."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "function _weeklySummaryRosterHtml(roster, revealed" in js
        card = _fn_body(js, "_weeklySummaryRosterCardHtml")
        for phrase in ("SUBBED IN", "From your bench, for", "who did not play this week",
                       "No matches this week. Replaced by"):
            assert phrase in card, phrase
        roster = _fn_body(js, "_weeklySummaryRosterHtml")
        assert '"weekly-summary-roster-group">Did not play<' in roster
        assert "didNotPlay.length" in roster

    def test_roster_html_renders_not_scored_label(self):
        """app-weekly-summary.js: game rows render "Not scored" when `scored` is false instead of
        the points value, and "WIN" / "LOSS" and an "MVP" tag otherwise."""
        game = _fn_body(_read(_APP_WEEKLY_SUMMARY_JS_PATH), "_weeklySummaryGameHtml")
        assert "g.scored" in game and "Not scored" in game
        assert "'WIN'" in game and "'LOSS'" in game
        assert ">MVP<" in game and "g.is_mvp" in game
        assert "teamLink(g.opponent_team_id" in game

    def test_roster_styles_use_accent_ghost_not_left_border(self):
        """style.css: no `border-left` accent on roster cards; the "Did not play" card uses a
        dashed border and greyed-out style. (Issue #152 removed the subbed-in card's
        `var(--accent-ghost)` tint: the "SUBBED IN" tag alone marks it, see
        test_issue_152_weekly_recap_animations.py.)"""
        css = _read(_STYLE_CSS_PATH)
        assert not any(sel == ".weekly-summary-roster-card.subbed-in"
                       for sel, _ in _css_blocks(css, r"subbed-in"))
        for sel, body in _css_blocks(css, r"\.weekly-summary-roster"):
            assert "border-left" not in body, sel
        out = _css_rule(css, ".weekly-summary-roster-card.subbed-out")
        assert "dashed" in out and "opacity" in out

    def test_thumbnail_button_opens_show_card_with_week_points_footer(self):
        """app-weekly-summary.js: the roster thumbnail is a <button> wrapping
        `<img src=cardImageUrl(card_id)>` with `_cardImgFallback` on error, and its handler calls
        `showCard({...card, id: card_id}, `${week_points} wk pts`)` (footer reads "wk pts")."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        card = _fn_body(js, "_weeklySummaryRosterCardHtml")
        thumb = card[card.index('<button type="button" class="weekly-summary-roster-thumb"'):]
        thumb = thumb[:thumb.index("</button>")]
        assert '<img src="${cardImageUrl(c.card_id)}"' in thumb
        assert 'onerror="_cardImgFallback(this)"' in thumb
        assert "_weeklySummaryShowCard(" in thumb
        show = _fn_body(js, "_weeklySummaryShowCard")
        assert "showCard({...card, id: card.card_id}, footer)" in show
        assert "toFixed(1)} wk pts`" in show

    def test_roster_html_escapes_strings(self):
        """Failure path: `_weeklySummaryRosterHtml` passes player/team names and other strings
        through `_escHtml` (or playerLink/teamLink, which escape) — no raw `${card.player_name}`
        interpolation."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        roster_src = "".join(_fn_body(js, f) for f in (
            "_weeklySummaryRosterHtml", "_weeklySummaryRosterCardHtml", "_weeklySummaryGameHtml"))
        interpolations = re.findall(r"\$\{([^}]*)\}", roster_src)
        raw = [i for i in interpolations
               if re.search(r"\b(name|player_name|team_name|subbed_in_for|card_type|opponent_name|rarity)\b", i)
               and not re.match(r"\s*(_escHtml|playerLink|teamLink)\(", i)]
        assert raw == []
        assert "playerLink(c.player_id, c.player_name)" in roster_src
        assert "teamLink(c.team_id" in roster_src


# ---------------------------------------------------------------------------
# Story 3: Your Cards in the Match Results
# ---------------------------------------------------------------------------
class TestYourCardsInMatchResults:
    def test_card_points_set_for_counted_players(self, db):
        """Revealed week: for each result player on the user's counted roster, `card_points`
        equals `display_points` of the sum of the user's counted cards' `card_match_points` for
        that player and match; `on_roster` is still present."""
        _seed(db)
        owned = [(mid, p) for mid, p in _players(_summary(db)) if p["player_id"] == A]
        assert len(owned) == 2
        for mid, p in owned:
            assert p["card_points"] == display_points(_cmp(db, 1, mid))
            assert p["on_roster"] is True

    def test_card_points_null_for_non_roster_players(self, db):
        """Failure path: result players not on the user's counted roster — including the
        subbed-out card's player and unused bench players — have `card_points: None`."""
        _seed(db, substitute=True, b_plays=False)
        for _, p in _players(_summary(db)):
            if p["player_id"] in (D, E, B):
                assert p["card_points"] is None, p
                assert "on_roster" in p

    def test_card_points_set_for_subbed_in_player(self, db):
        """Substitution scenario: the subbed-in card's player has `card_points` set in its
        match results (it counts toward the roster)."""
        _seed(db, substitute=True)
        subs = [(mid, p) for mid, p in _players(_summary(db)) if p["player_id"] == C]
        assert len(subs) == 2
        for mid, p in subs:
            assert p["card_points"] == display_points(_cmp(db, 3, mid))

    def test_player_html_marks_owned_tile(self):
        """app-weekly-summary.js: `_weeklySummaryPlayerHtml` adds class `weekly-summary-owned` and
        a "YOUR CARD" label (or "YOUR SUB" for a subbed-in card) when `p.card_points != null`, and
        shows `card_points` instead of match points."""
        fn = _fn_body(_read(_APP_WEEKLY_SUMMARY_JS_PATH), "_weeklySummaryPlayerHtml")
        assert "p.card_points != null" in fn
        assert "weekly-summary-owned" in fn
        assert "'YOUR CARD'" in fn and "'YOUR SUB'" in fn
        assert "if (owned) pts = Number(p.card_points).toFixed(1);" in fn
        assert fn.index("Number(p.card_points)") < fn.index("Number(p.points)")

    def test_owned_tile_uses_filled_accent_ghost(self):
        """style.css: `.weekly-summary-owned` sets a `var(--accent-ghost)` background (filled
        shape, not colour alone) and does not remove the MVP outline, so both can co-exist."""
        css = _read(_STYLE_CSS_PATH)
        owned = _css_rule(css, ".weekly-summary-owned")
        assert "background: var(--accent-ghost)" in owned
        assert "outline" not in owned
        assert "outline: 2px solid var(--accent)" in _css_rule(css, ".weekly-summary-mvp")
        fn = _fn_body(_read(_APP_WEEKLY_SUMMARY_JS_PATH), "_weeklySummaryPlayerHtml")
        assert "${mvpClass}${ownedClass}" in fn


# ---------------------------------------------------------------------------
# Story 4: Links Work as Everywhere Else
# ---------------------------------------------------------------------------
class TestLinksWorkAsEverywhereElse:
    def test_weekly_summary_js_uses_player_and_team_links(self):
        """app-weekly-summary.js calls `playerLink(` for roster card and result tile player
        names and `teamLink(` for roster card team, game opponent and series team names."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "playerLink(c.player_id, c.player_name)" in _fn_body(js, "_weeklySummaryRosterCardHtml")
        assert "teamLink(c.team_id" in _fn_body(js, "_weeklySummaryRosterCardHtml")
        assert "playerLink(p.player_id, p.name)" in _fn_body(js, "_weeklySummaryPlayerHtml")
        assert "teamLink(g.opponent_team_id" in _fn_body(js, "_weeklySummaryGameHtml")
        assert "teamLink(team.id" in _fn_body(js, "_weeklySummaryTeamHtml")

    def test_weekly_summary_js_has_no_plain_name_spans(self):
        """Failure path: app-weekly-summary.js renders no player or team name as a plain escaped
        string without `playerLink` / `teamLink` (e.g. no `_escHtml(p.player_name)` or
        `_escHtml(...team_name)` outside a link helper)."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert not re.search(r"_escHtml\([\w.]*team_name\)", js)
        assert "_escHtml(p.name)" not in js and "_escHtml(p.player_name)" not in js
        # player_name is escaped only into attributes (aria-label, data-player-name), never as text.
        for m in re.finditer(r"_escHtml\(c\.player_name\)", js):
            before = js[max(0, m.start() - 40):m.start()]
            assert re.search(r'(aria-label="[^"]*|data-player-name=")\$\{$', before), before

    def test_reveal_overlay_stacks_above_modal_overlay(self):
        """style.css: the `z-index` of `.reveal-overlay` is numerically greater than the
        `z-index` of `.modal-overlay` (300)."""
        css = _read(_STYLE_CSS_PATH)
        reveal = int(re.search(r"z-index:\s*(\d+)", _css_rule(css, ".reveal-overlay")).group(1))
        modal = int(re.search(r"z-index:\s*(\d+)", _css_rule(css, ".modal-overlay")).group(1))
        assert modal == 300 and reveal > modal
        # Popups after the card viewer in the DOM (player, team) still open above it.
        later = int(re.search(r"z-index:\s*(\d+)", _css_rule(css, ".reveal-overlay ~ .modal-overlay")).group(1))
        assert later > reveal

    def test_player_and_team_modals_after_weekly_summary_modal(self):
        """index.html: #playerModal and #teamModal are `.modal-overlay` elements placed after
        #weeklySummaryModal, so they open on top of the report."""
        html = _read(_INDEX_HTML_PATH)
        report = html.index('id="weeklySummaryModal"')
        reveal = html.index('id="revealModal"')
        for modal_id in ("playerModal", "teamModal"):
            pos = html.index(f'id="{modal_id}"')
            assert pos > report and pos > reveal
            tag_start = html.rindex("<div", 0, pos)
            assert 'class="modal-overlay' in html[tag_start:pos]


# ---------------------------------------------------------------------------
# Story 5: Reveal and Substitution States
# ---------------------------------------------------------------------------
class TestRevealAndSubstitutionStates:
    def test_unrevealed_roster_has_identities_only(self, db):
        """`_build_week_summary(db, week, revealed=False, user_id)["roster"]["cards"]` entries
        contain only card_id, card_type, player and team fields — no `week_points`, `games`,
        `counted`, `subbed_in`, `subbed_out`, `subbed_in_for`; and `roster` has no `week_total`."""
        _seed(db, substitute=True)
        roster = _summary(db, revealed=False)["roster"]
        assert set(roster) == {"cards"}
        for c in roster["cards"]:
            assert set(c) == {"card_id", "card_type", "player_id", "player_name", "avatar_url",
                              "team_id", "team_name"}

    def test_unrevealed_roster_shows_lock_time_slots(self, db):
        """Substitution scenario, unrevealed: `roster.cards` lists the five lock-time cards in slot
        order — B (subbed out) stays in its slot, C (subbed in) is absent."""
        _seed(db, substitute=True)
        cards = _summary(db, revealed=False)["roster"]["cards"]
        assert [c["card_id"] for c in cards] == [1, 2]
        assert [c["player_id"] for c in cards] == [A, B]

    def test_unrevealed_week_has_no_card_points(self, db):
        """Failure path: unrevealed week — no result player carries `card_points` (and the
        existing players / points block stays hidden)."""
        _seed(db, substitute=True)
        summary = _summary(db, revealed=False)
        assert list(_players(summary)) == []
        for s in summary["series"]:
            for m in s["matches"]:
                assert "players" not in m
                assert m["winner_team_id"] is None
        assert "card_points" not in repr(summary)
        assert "is_mvp" not in repr(summary)

    def test_roster_html_hides_points_before_reveal(self):
        """app-weekly-summary.js: `_weeklySummaryRosterHtml(roster, revealed, ...)` renders
        "Reveal results to see your points" when not revealed and skips points, game rows,
        WIN/LOSS, MVP and status tags; thumbnails still call `showCard`."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        roster = _fn_body(js, "_weeklySummaryRosterHtml")
        assert "Reveal results to see your points" in roster
        card = _fn_body(js, "_weeklySummaryRosterCardHtml")
        unrevealed = card[card.index("if (!revealed) {"):]
        unrevealed = unrevealed[:unrevealed.index("\n  }\n")]
        assert "${thumb}" in unrevealed
        for hidden in ("week_points", "games", "statusTag", "WIN", "MVP", "pts"):
            assert hidden not in unrevealed, hidden
        assert "showCard(" in _fn_body(js, "_weeklySummaryShowCard")

    def test_roster_header_shows_substitutions_pending_note(self):
        """app-weekly-summary.js: when `substitutions_pending` is true the roster header renders
        the existing note that substitutions run {N} hours after the week ends and statuses may
        change."""
        render = _fn_body(_read(_APP_WEEKLY_SUMMARY_JS_PATH), "renderWeeklySummaryContent")
        assert "data.revealed && data.substitutions_pending" in render
        assert "${data.substitution_delay_hours} hours after the week ends" in render
        note = render[render.index("data.revealed && data.substitutions_pending"):]
        assert "getElementById('weeklySummaryRosterMeta').appendChild(note)" in note


# ---------------------------------------------------------------------------
# Story 6: New Recap Popup
# ---------------------------------------------------------------------------
def _seed_reports(db, week_ids=(1,)):
    db.add(User(id=1, username="alice", email="a@test", password_hash="x", tokens=5))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=1000, is_locked=True))
    db.add(Week(id=2, label="Week 2", start_time=1001, end_time=2000, is_locked=True))
    for wid in week_ids:
        db.add(WeeklySummary(week_id=wid, generated_at=int(time.time())))
    db.commit()


class TestNewRecapPopup:
    def test_weekly_summary_seen_has_last_prompted_week_id(self):
        """models.WeeklySummarySeen has a nullable Integer column `last_prompted_week_id` with a
        ForeignKey to `weeks.id`."""
        col = WeeklySummarySeen.__table__.c.last_prompted_week_id
        assert col.nullable is True
        assert col.type.__class__.__name__ == "Integer"
        assert {fk.target_fullname for fk in col.foreign_keys} == {"weeks.id"}

    def test_migration_030_adds_last_prompted_week_id(self):
        """`migrate.run_migrations` on a legacy `weekly_summary_seen` table without the column adds
        `last_prompted_week_id` (migration id `030_weekly_summary_seen_last_prompted`), existing
        rows get NULL, and running again is a no-op."""
        ids = [m[0] for m in migrate.MIGRATIONS]
        assert ids[-1] == "030_weekly_summary_seen_last_prompted"
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE weekly_summary_seen"))
            conn.execute(text("CREATE TABLE weekly_summary_seen (user_id INTEGER PRIMARY KEY, "
                              "last_seen_week_id INTEGER)"))
            conn.execute(text("INSERT INTO weekly_summary_seen VALUES (1, 4)"))
            conn.commit()
            migrate._ensure_migrations_table(conn)
            for migration_id in ids:
                if migration_id < "030":
                    migrate._record(conn, migration_id)
        cols = lambda: [c["name"] for c in sa_inspect(engine).get_columns("weekly_summary_seen")]  # noqa: E731
        assert "last_prompted_week_id" not in cols()
        migrate.run_migrations(engine)
        assert cols().count("last_prompted_week_id") == 1
        with engine.connect() as conn:
            assert tuple(conn.execute(text("SELECT user_id, last_seen_week_id, last_prompted_week_id "
                                           "FROM weekly_summary_seen")).one()) == (1, 4, None)
            assert conn.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE id = "
                                     "'030_weekly_summary_seen_last_prompted'")).scalar() == 1
            migrate._m030_weekly_summary_seen_last_prompted(conn)  # re-run the body directly
        migrate.run_migrations(engine)
        assert cols().count("last_prompted_week_id") == 1

    def test_list_weekly_summaries_show_prompt_true_for_new_week(self, db):
        """`GET /weekly-summary` (list_weekly_summaries) returns `show_prompt: True` and
        `latest_week: {"week_id", "label"}` for the newest report week when the user has no
        WeeklySummarySeen row."""
        _seed_reports(db, (1, 2))
        data = list_weekly_summaries(db=db, current_user=_user())
        assert data["show_prompt"] is True
        assert data["latest_week"] == {"week_id": 2, "label": "Week 2"}

    def test_prompted_clears_show_prompt_but_not_has_unseen(self, db):
        """After `POST /weekly-summary/prompted`, `show_prompt` is False and `has_unseen` is still
        True; the row's `last_prompted_week_id` equals the newest report week; response is
        `{"ok": True}`."""
        _seed_reports(db, (1, 2))
        assert mark_weekly_summary_prompted(db=db, current_user=_user()) == {"ok": True}
        data = list_weekly_summaries(db=db, current_user=_user())
        assert (data["show_prompt"], data["has_unseen"]) == (False, True)
        assert db.get(WeeklySummarySeen, 1).last_prompted_week_id == 2

    def test_prompted_creates_row_and_is_idempotent(self, db):
        """`POST /weekly-summary/prompted` creates the WeeklySummarySeen row if missing (leaving
        `last_seen_week_id` NULL) and calling it twice leaves one row with the same value."""
        _seed_reports(db)
        assert db.get(WeeklySummarySeen, 1) is None
        mark_weekly_summary_prompted(db=db, current_user=_user())
        mark_weekly_summary_prompted(db=db, current_user=_user())
        rows = db.query(WeeklySummarySeen).all()
        assert len(rows) == 1
        assert (rows[0].last_seen_week_id, rows[0].last_prompted_week_id) == (None, 1)

    def test_seen_clears_both_show_prompt_and_has_unseen(self, db):
        """After `POST /weekly-summary/seen`, both `show_prompt` and `has_unseen` are False, and
        `last_prompted_week_id` is also set to the newest report week."""
        _seed_reports(db, (1, 2))
        mark_weekly_summary_seen(db=db, current_user=_user())
        data = list_weekly_summaries(db=db, current_user=_user())
        assert (data["show_prompt"], data["has_unseen"]) == (False, False)
        row = db.get(WeeklySummarySeen, 1)
        assert (row.last_seen_week_id, row.last_prompted_week_id) == (2, 2)

    def test_newer_report_week_makes_show_prompt_true_again(self, db):
        """After prompting/seeing week 1, generating a report for a newer week 2 makes
        `show_prompt` True again with `latest_week.week_id` = week 2 (newest only)."""
        _seed_reports(db, (1,))
        mark_weekly_summary_prompted(db=db, current_user=_user())
        mark_weekly_summary_seen(db=db, current_user=_user())
        assert list_weekly_summaries(db=db, current_user=_user())["show_prompt"] is False
        db.add(WeeklySummary(week_id=2, generated_at=int(time.time())))
        db.commit()
        data = list_weekly_summaries(db=db, current_user=_user())
        assert data["show_prompt"] is True
        assert data["latest_week"]["week_id"] == 2

    def test_prompted_requires_authentication(self):
        """Failure path: `POST /weekly-summary/prompted` without a session returns 401 (minimal
        FastAPI app with weekly_summary router; route is not shadowed by
        `/weekly-summary/{week_id}` routes)."""
        from database import get_db
        from routers import weekly_summary as weekly_summary_router

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        def _override_get_db():
            s = Session()
            try:
                yield s
            finally:
                s.close()

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="t" * 40)
        app.include_router(weekly_summary_router.router)
        app.dependency_overrides[get_db] = _override_get_db
        client = TestClient(app)
        res = client.post("/weekly-summary/prompted")
        assert res.status_code == 401
        paths = [(r.path, sorted(r.methods)) for r in weekly_summary_router.router.routes]
        assert ("/weekly-summary/prompted", ["POST"]) in paths

    def test_recap_prompt_dialog_markup(self):
        """index.html: `#weeklyRecapPrompt` is a `.modal-overlay` with `role="dialog"`,
        `aria-modal="true"`, `aria-labelledby` pointing at its title, the line "See what your
        cards scored and how the matches went", a mention of Weekly Report at the top right,
        an "Open recap" primary button, a "Close" button and an X close button."""
        html = _prompt_markup()
        tag = html[:html.index(">")]
        assert 'class="modal-overlay hidden"' in tag
        assert 'role="dialog"' in tag and 'aria-modal="true"' in tag
        assert 'aria-labelledby="weeklyRecapPromptTitle"' in tag
        assert 'id="weeklyRecapPromptTitle"' in html
        assert "See what your cards scored and how the matches went" in html
        assert "Weekly Report at the top right" in html
        assert re.search(r'<button id="weeklyRecapPromptOpen" onclick="openWeeklyRecapFromPrompt\(\)">Open recap</button>', html)
        assert re.search(r'<button class="secondary"[^>]*>Close</button>', html)
        assert 'aria-label="Close">&#x2715;</button>' in html
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "`${title} recap is ready`" in js and "`Week ${label}`" in js

    def test_recap_prompt_gives_nothing_away(self):
        """Failure path: the #weeklyRecapPrompt markup and the JS that fills it contain no
        points, winners or results (only the week label is interpolated)."""
        html = _prompt_markup().lower()
        for word in ("pts", "points", "winner", "won", "mvp", "win<", "loss"):
            assert word not in html, word
        fn = _fn_body(_read(_APP_WEEKLY_SUMMARY_JS_PATH), "maybeShowWeeklyRecapPrompt")
        assert re.findall(r"\$\{([^}]*)\}", fn) == ["label", "title"]
        assert "innerHTML" not in fn

    def test_maybe_show_prompt_called_after_highlight_check(self):
        """app-weekly-summary.js defines `maybeShowWeeklyRecapPrompt(` and calls it after
        `checkWeeklySummaryHighlight()` has loaded the list (call appears inside / after that
        function's fetch)."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "function maybeShowWeeklyRecapPrompt(data)" in js
        fn = _fn_body(js, "checkWeeklySummaryHighlight")
        assert fn.index("await res.json()") < fn.index("maybeShowWeeklyRecapPrompt(data)")
        assert fn.index("if (!res.ok) return;") < fn.index("maybeShowWeeklyRecapPrompt(data)")

    def test_maybe_show_prompt_guards_against_clashes(self):
        """Failure path: `maybeShowWeeklyRecapPrompt` returns without showing when
        `data.show_prompt` is false, another `.modal-overlay` or `.reveal-overlay` is open,
        `_tour` is running, or `activeMustChangePassword` is true — and marks nothing."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        fn = _fn_body(js, "maybeShowWeeklyRecapPrompt")
        show = fn.index("classList.remove('hidden')")
        for guard in ("if (!data || !data.show_prompt || !data.latest_week) return;",
                      "if (_weeklyRecapOtherOverlayOpen()) return;",
                      "if (typeof _tour !== 'undefined' && _tour) return;",
                      "if (activeMustChangePassword) return;"):
            assert guard in fn and fn.index(guard) < show, guard
        assert "fetch(" not in fn
        other = _fn_body(js, "_weeklyRecapOtherOverlayOpen")
        assert "'.modal-overlay, .reveal-overlay'" in other
        assert "el.id !== 'weeklyRecapPrompt'" in other

    def test_open_recap_opens_report_on_latest_week(self):
        """app-weekly-summary.js: the "Open recap" handler calls `openWeeklySummary(` selecting
        `latest_week`, which then marks the week seen (POST /weekly-summary/seen)."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        fn = _fn_body(js, "openWeeklyRecapFromPrompt")
        assert "_weeklyRecapPromptWeek" in fn
        assert "await openWeeklySummary(week ? week.week_id : undefined);" in fn
        assert "_weeklyRecapPromptWeek = data.latest_week;" in _fn_body(js, "maybeShowWeeklyRecapPrompt")
        opener = _fn_body(js, "openWeeklySummary")
        assert opener.index("loadWeeklySummaryList(weekId)") < opener.index("markWeeklySummarySeen()")
        loader = _fn_body(js, "loadWeeklySummaryList")
        assert "_weeklySummaryWeeks.find(w => w.week_id === weekId)" in loader
        assert "/weekly-summary/seen" in _fn_body(js, "markWeeklySummarySeen")

    def test_close_paths_call_prompted_endpoint(self):
        """app-weekly-summary.js: Close button, X, Esc and backdrop click all call
        `/weekly-summary/prompted` (POST) and hide #weeklyRecapPrompt; they do not call
        `/weekly-summary/seen`."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        fn = _fn_body(js, "dismissWeeklyRecapPrompt")
        assert "fetch(`${API}/weekly-summary/prompted`, { method: 'POST' })" in fn
        assert "_hideWeeklyRecapPrompt();" in fn
        assert "/seen" not in fn
        html = _prompt_markup()
        tag = html[:html.index(">")]
        assert 'data-close="dismissWeeklyRecapPrompt"' in tag  # Esc (app-init.js)
        assert 'onclick="if(event.target===this)dismissWeeklyRecapPrompt()"' in tag  # backdrop
        assert html.count('onclick="dismissWeeklyRecapPrompt()"') == 2  # X and Close

    def test_recap_prompt_focus_and_trap(self):
        """app-weekly-summary.js: on open, focus moves to the "Open recap" button, and a keydown
        handler keeps Tab / Shift+Tab inside #weeklyRecapPrompt."""
        js = _read(_APP_WEEKLY_SUMMARY_JS_PATH)
        assert "getElementById('weeklyRecapPromptOpen').focus()" in _fn_body(js, "maybeShowWeeklyRecapPrompt")
        trap = js[js.index("document.getElementById('weeklyRecapPrompt')?.addEventListener('keydown'"):]
        assert "e.key !== 'Tab'" in trap
        assert "e.shiftKey && document.activeElement === first" in trap
        assert "last.focus()" in trap and "first.focus()" in trap
