"""
Tests for plan-issue-248-most-mvps-accolade.md (resolves GitHub issue #248).

A fourth player award, Most MVPs (`most_mvps`): the player with the most MVPs
(`player_match_stats.is_mvp`) in the season's scored matches. End Season records
it, and History, the player popup, cards and Admin > Accolades show it like the
other awards. No schema change: `season_accolades.kind` is a free string and
`value` holds the MVP count.

  Story 1: Most MVPs Is Recorded at the End of the Season
  Story 2: Most MVPs Shows With the Other Accolades
  Story 3: An Admin Can Add Most MVPs by Hand

Approach notes (for the developer filling these in):

- Reuse the helpers of test_issue_50_season_winners_and_holo_cards.py (copy or
  import them): its module-level `db` fixture (StaticPool,
  check_same_thread=False, needed by every TestClient test here; conftest's
  plain `:memory:` `db` is invisible to TestClient's worker threads),
  `_seed_season`, `_end` (calls `admin_season.end_season` directly),
  `_admin_client` / `_client` (signed in with a recent re-auth), `_user`,
  `_acc`, `_rows`, `_read` / `_fe`, `_fn_body`, `_fn_source`,
  `_globals_helpers_js`, `_run_node`, `_chips`, `_pips`, `_a`, `_rule`.
- `_seed_season` builds `PlayerMatchStats` rows without `is_mvp`. Use a local
  variant that takes (player, team, match, points, is_mvp) tuples; match 1004
  is the one it marks `excluded_from_scoring`.
- `accolades.compute_awards(db)` returns {kind: [{player_account_id,
  player_name, value, match_id?}]} sorted by name; ties come from `_ties`.
  `accolades.record_season` loops over `AWARD_KINDS` and inserts with
  `insert_ignore` (ON CONFLICT DO NOTHING), so an existing row is kept.
- Routes: `GET /admin/season/accolades-preview` and `POST /admin/season/end`
  (routers/admin_season.py); `POST /admin/season-accolades` and
  `DELETE /admin/season-accolades/{id}` (routers/admin_accolades.py, whose
  `AccoladeIn.kind` is a `Literal` that has to gain `most_mvps`); `GET
  /history/seasons` builds each season's `awards` from `AWARD_KINDS`
  (`accolades.history`).
- Frontend source-reading: `_HISTORY_AWARDS` and `_historyValue` in
  app-history.js, `_END_SEASON_AWARDS` in app-admin-season.js, the `#accKind`
  select in index.html, `ACCOLADE_KINDS`, `_accoladeChipLabel`,
  `accoladeDetailLine` and `_CARD_ACCOLADE_PRIORITY` in app-globals.js. Node
  harness stubs skip when Node is missing (`_run_node`). Parse index.html with
  `html.parser`, not regexes (CodeQL `py/bad-tag-filter`).
- Older tests pin the registry and have to be extended in the same change:
  `test_accolade_kinds_backend_order_names_icons_tokens` (test_issue_50, exact
  list), `test_each_accolade_kind_uses_its_matching_badge_icon_not_lucide`
  (test_card_art_accolade_redesign.py, one badge file per key) and the
  priority parity test in test_card_art_polish.py.
- Colour tokens live in frontend/colors_and_type.css and
  design/colors_and_type.css, which must stay identical; new pip/chip CSS goes
  before the "GUIDED TOUR (issue #144)" section of style.css.

Run with: cd backend && python -m pytest tests/test_issue_248_most_mvps_accolade.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import re
from html.parser import HTMLParser

import pytest

import models  # noqa: F401  (registers every table for the db fixture)

import accolades
from models import Match, Player, PlayerMatchStats, Team
from tests.test_issue_50_season_winners_and_holo_cards import (  # noqa: F401  (`db` is a fixture)
    _a, _acc, _admin_client, _audits, _chips, _client, _end, _fe, _fn_source,
    _globals_helpers_js, _pips, _read, _rows, _rule, _run_node, _user, db,
)

_PLAYERS = {1: "Alpha", 2: "Bravo", 3: "Charlie", 4: "Delta"}
# (player, team, match, points, is_mvp); match 1004 is excluded from scoring.
_ONE_WINNER = [
    (1, 100, 1001, 30.0, True), (1, 100, 1002, 10.0, True), (1, 100, 1003, 20.0, False),
    (2, 100, 1001, 50.0, False), (2, 100, 1002, 5.0, True),
    (3, 200, 1001, 25.0, False), (3, 200, 1002, 25.0, False),
    (4, 200, 1004, 999.0, True),
]
_TIE = _ONE_WINNER[:5] + [(3, 200, 1001, 25.0, True), (3, 200, 1003, 25.0, True),
                          (4, 200, 1004, 999.0, True)]
_NO_MVPS = [(p, t, m, pts, False) for p, t, m, pts, _ in _ONE_WINNER]
_EXCLUDED = [
    (1, 100, 1001, 30.0, True), (1, 100, 1002, 10.0, False),
    (2, 100, 1001, 50.0, False),
    (4, 200, 1004, 999.0, True), (4, 200, 1004, 1.0, True), (4, 200, 1004, 2.0, True),
]


def _seed(db, stats=_ONE_WINNER):
    """test_issue_50's _seed_season with an is_mvp flag per stats row."""
    for pid, name in _PLAYERS.items():
        db.add(Player(id=pid, name=name, is_active=True))
    db.add(Team(id=100, name="Reds"))
    db.add(Team(id=200, name="Blues"))
    for mid in sorted({s[2] for s in stats}):
        db.add(Match(match_id=mid, radiant_team_id=100, dire_team_id=200, start_time=1_000_000 + mid,
                     excluded_from_scoring=(mid == 1004)))
    for pid, team, mid, pts, mvp in stats:
        db.add(PlayerMatchStats(player_id=pid, team_id=team, match_id=mid, fantasy_points=pts,
                                is_mvp=mvp))
    db.commit()


def _js_list(js, const):
    """The source of a `const NAME = [ … ];` list, without comments."""
    start = js.index(f"const {const} = [")
    return js[start:js.index("];", start)]


def _history_js():
    js = _fe("app-history.js")
    return (_globals_helpers_js() + "\n" + _js_list(js, "_HISTORY_AWARDS") + "];\n"
            + _fn_source(js, "_historyValue") + _fn_source(js, "_historyAwardsHtml"))


def _history_awards_html(season):
    return _run_node(_history_js() + f"""
console.log(JSON.stringify(_historyAwardsHtml({json.dumps(season)})));
""")


def _detail_line(accolade):
    return _run_node(_globals_helpers_js() + f"""
console.log(JSON.stringify(accoladeDetailLine({json.dumps(accolade)})));
""")


class _Options(HTMLParser):
    """[(value, label)] of the <option>s of one <select>, by id."""

    def __init__(self, select_id):
        super().__init__()
        self.select_id, self.inside, self.current, self.options = select_id, False, None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.inside = attrs.get("id") == self.select_id
        elif tag == "option" and self.inside:
            self.current = [attrs.get("value"), ""]

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == "option" and self.current is not None:
            self.options.append((self.current[0], self.current[1].strip()))
            self.current = None
        elif tag == "select":
            self.inside = False


def _mvp_body(**over):
    body = {"season_label": "Season 15", "kind": "most_mvps", "player_account_id": 7,
            "player_name": "Glete", "value": 5}
    body.update(over)
    return {k: v for k, v in body.items() if v is not None}




# ---------------------------------------------------------------------------
# Story 1: Most MVPs Is Recorded at the End of the Season
# ---------------------------------------------------------------------------

class TestMostMvpsRecordedAtSeasonEnd:

    def test_compute_awards_most_mvps_single_winner_with_count(self, db):
        """Rule: with Alpha on 2 MVPs and Bravo on 1 in scored matches, compute_awards(db)["most_mvps"] is exactly one entry for Alpha (player_account_id, player_name "Alpha") whose value is the whole number 2, with no match_id."""
        _seed(db)
        mvps = accolades.compute_awards(db)["most_mvps"]
        assert mvps == [{"player_account_id": 1, "player_name": "Alpha", "value": 2}]
        assert isinstance(mvps[0]["value"], int) and not isinstance(mvps[0]["value"], bool)
        assert "match_id" not in mvps[0]

    def test_compute_awards_most_mvps_tie_lists_every_tied_player(self, db):
        """Ties: with Alpha and Charlie both on 2 MVPs and Bravo on 1, compute_awards(db)["most_mvps"] lists Alpha and Charlie (sorted by name, value 2 each) and not Bravo."""
        _seed(db, _TIE)
        mvps = accolades.compute_awards(db)["most_mvps"]
        assert [(a["player_account_id"], a["player_name"], a["value"]) for a in mvps] == [
            (1, "Alpha", 2), (3, "Charlie", 2)]

    def test_compute_awards_most_mvps_empty_when_nobody_has_an_mvp(self, db):
        """None: with scored matches but no is_mvp row, compute_awards(db)["most_mvps"] is [] (no zero-count winners) while most_points, best_average and best_match are still filled."""
        _seed(db, _NO_MVPS)
        awards = accolades.compute_awards(db)
        assert awards["most_mvps"] == []
        for kind in ("most_points", "best_average", "best_match"):
            assert awards[kind], kind
        assert awards["most_points"][0]["player_account_id"] == 1

    def test_compute_awards_most_mvps_ignores_mvps_on_excluded_matches(self, db):
        """Scored matches only: Delta's MVPs are all on the match excluded from scoring (more of them than anyone else has), Alpha has 1 on a scored match; compute_awards(db)["most_mvps"] names only Alpha with value 1."""
        _seed(db, _EXCLUDED)
        assert accolades.compute_awards(db)["most_mvps"] == [
            {"player_account_id": 1, "player_name": "Alpha", "value": 1}]

    def test_accolades_preview_lists_most_mvps_with_winner_and_count(self, db):
        """Preview: GET /admin/season/accolades-preview as an admin answers 200 with awards["most_mvps"] holding the winner's player_account_id, player_name and MVP count as value, next to most_points, best_average and best_match."""
        _seed(db)
        client, _ = _admin_client(db)
        resp = client.get("/admin/season/accolades-preview")
        assert resp.status_code == 200, resp.text
        awards = resp.json()["awards"]
        assert awards["most_mvps"] == [{"player_account_id": 1, "player_name": "Alpha", "value": 2}]
        for kind in ("most_points", "best_average", "best_match"):
            assert awards[kind], kind

    def test_most_mvps_is_an_award_kind_after_best_match(self):
        """Kind: "most_mvps" is in accolades.KINDS and is the last entry of accolades.AWARD_KINDS (and PLAYER_AWARD_KINDS), directly after "best_match"."""
        assert "most_mvps" in accolades.KINDS
        assert accolades.AWARD_KINDS == ("most_points", "best_average", "best_match", "most_mvps")
        assert accolades.PLAYER_AWARD_KINDS == accolades.AWARD_KINDS

    def test_season_end_inserts_one_most_mvps_row_per_winner(self, db):
        """Recorded: End Season ("Season 16") with Alpha and Charlie tied on 2 MVPs inserts two season_accolades rows of kind most_mvps (player ids and names of both, value 2.0, source "season_end", match_id None, division None), and the result's "awards" count includes them."""
        _seed(db, _TIE)
        result = _end(db)
        rows = sorted(_rows(db, kind="most_mvps"), key=lambda r: r.player_account_id)
        assert [(r.season_label, r.player_account_id, r.player_name, r.value, r.source, r.match_id,
                 r.division) for r in rows] == [
            ("Season 16", 1, "Alpha", 2.0, "season_end", None, None),
            ("Season 16", 3, "Charlie", 2.0, "season_end", None, None)]
        award_rows = [r for r in _rows(db) if r.kind in accolades.AWARD_KINDS]
        assert result["awards"] == len(award_rows)
        assert result["awards"] >= 5  # most_points, best_average, best_match and two most_mvps

    def test_season_end_keeps_an_existing_most_mvps_row(self, db):
        """Recorded: a most_mvps row for the season's winner entered by hand first (source "admin", value 7) is still the only most_mvps row for that player after End Season, with source "admin" and value 7 unchanged."""
        _seed(db)
        _acc(db, "Season 16", "most_mvps", 1, "Alpha", value=7)
        _end(db)
        rows = _rows(db, kind="most_mvps", player_account_id=1)
        assert [(r.source, r.value) for r in rows] == [("admin", 7.0)]
        assert len(_rows(db, kind="most_mvps")) == 1

    def test_season_end_with_no_mvps_records_no_most_mvps_row_and_still_works(self, db):
        """None (failure path): End Season on a season with scored matches and no MVPs succeeds, records the most_points / best_average / best_match and played rows as before, and leaves no row of kind most_mvps."""
        _seed(db, _NO_MVPS)
        result = _end(db)
        assert result["awards"] == 3 and result["played"] == 3
        assert _rows(db, kind="most_mvps") == []
        for kind in ("most_points", "best_average", "best_match"):
            assert len(_rows(db, kind=kind)) == 1, kind
        assert len(_rows(db, kind="played")) == 3


# ---------------------------------------------------------------------------
# Story 2: Most MVPs Shows With the Other Accolades
# ---------------------------------------------------------------------------

class TestMostMvpsShowsWithOtherAccolades:

    def test_accolade_kinds_backend_has_most_mvps_after_best_match(self):
        """Registry: accolades.ACCOLADE_KINDS has the entry key "most_mvps", kind "most_mvps", division None, name "Most MVPs", icon "star", plate "outlined", token "--accolade-mvp", placed directly after best_match and before fantasy_winner."""
        keys = [k["key"] for k in accolades.ACCOLADE_KINDS]
        i = keys.index("most_mvps")
        assert accolades.ACCOLADE_KINDS[i] == {
            "key": "most_mvps", "kind": "most_mvps", "division": None, "name": "Most MVPs",
            "icon": "star", "plate": "outlined", "token": "--accolade-mvp"}
        assert keys[i - 1] == "best_match" and keys[i + 1] == "fantasy_winner"
        assert accolades.kind_key({"kind": "most_mvps", "division": None}) == "most_mvps"

    def test_accolade_kinds_frontend_lists_most_mvps_identically(self):
        """Registry (source-reading): ACCOLADE_KINDS in frontend/app-globals.js equals backend accolades.ACCOLADE_KINDS field by field (key, kind, division, name, icon, plate, token) and contains most_mvps at the same index."""
        block = _js_list(_fe("app-globals.js"), "ACCOLADE_KINDS")
        fields = ("key", "kind", "division", "name", "icon", "plate", "token")
        frontend = []
        for line in block.splitlines()[1:]:
            if not line.strip():
                continue
            entry = {}
            for f in fields:
                m = re.search(rf'\b{f}: (?:"([^"]*)"|null)', line)
                assert m, (f, line)
                entry[f] = m.group(1)
            frontend.append(entry)
        assert frontend == accolades.ACCOLADE_KINDS
        backend_keys = [k["key"] for k in accolades.ACCOLADE_KINDS]
        assert [k["key"] for k in frontend].index("most_mvps") == backend_keys.index("most_mvps")

    def test_history_returns_most_mvps_award_for_the_season(self, db):
        """History: with a most_mvps row for "Season 16" (Alpha, value 3), GET /history/seasons lists that season with awards["most_mvps"] == [{player_account_id, player_name "Alpha", value 3, match_id None}]; a season without such a row has awards["most_mvps"] == []."""
        _acc(db, "Season 16", "most_mvps", 1, "Alpha", value=3, source="season_end")
        _acc(db, "Season 15", "most_points", 2, "Bravo", value=40)
        seasons = {s["season_label"]: s for s in _client(db).get("/history/seasons").json()["seasons"]}
        assert seasons["Season 16"]["awards"]["most_mvps"] == [
            {"player_account_id": 1, "player_name": "Alpha", "value": 3, "match_id": None}]
        assert seasons["Season 15"]["awards"]["most_mvps"] == []

    def test_history_awards_list_shows_most_mvps_as_n_mvps_not_points(self):
        """History (Node harness over app-history.js): _HISTORY_AWARDS has {kind: "most_mvps", unit: "MVPs"} after best_match, and _historyAwardsHtml for a season whose awards.most_mvps is [{player_name: "Alpha", value: 3}] renders a row with the Most MVPs chip, "Alpha" and the value text "3 MVPs" (no decimals, no "pts")."""
        awards = _run_node(_history_js() + "\nconsole.log(JSON.stringify(_HISTORY_AWARDS));")
        kinds = [a["kind"] for a in awards]
        i = kinds.index("most_mvps")
        assert awards[i] == {"kind": "most_mvps", "unit": "MVPs"} and kinds[i - 1] == "best_match"
        season = {"season_label": "Season 16", "season_short": "S16",
                  "awards": {"most_mvps": [{"player_name": "Alpha", "value": 3}]}}
        html = _history_awards_html(season)
        assert html.count('class="history-award-row"') == 1
        assert "accolade-chip--most_mvps" in html and "S16 Most MVPs" in html
        assert '<span class="history-award-name">Alpha</span>' in html
        assert '<span class="history-award-value">3 MVPs</span>' in html
        assert "3.0" not in html and "pts" not in html
        # A single MVP reads "1 MVP"; a stored float count stays whole.
        season["awards"]["most_mvps"][0]["value"] = 1.0
        assert '<span class="history-award-value">1 MVP</span>' in _history_awards_html(season)

    def test_history_awards_list_omits_most_mvps_row_when_no_winner(self):
        """History (failure path, Node harness): _historyAwardsHtml for a season with awards.most_mvps == [] (or the key missing, as for seasons ended before this change) renders no Most MVPs row and does not throw."""
        points = [{"player_name": "Bravo", "value": 60}]
        for awards in ({"most_points": points, "most_mvps": []}, {"most_points": points}):
            html = _history_awards_html({"season_label": "Season 15", "season_short": "S15",
                                         "awards": awards})
            assert html.count('class="history-award-row"') == 1, awards
            assert "Most MVPs" not in html and "MVP" not in html, awards
            assert "60.0 pts" in html, awards
        assert "No awards recorded" in _history_awards_html({"season_label": "Season 15", "awards": {}})

    def test_end_season_preview_list_includes_most_mvps(self):
        """Preview (source-reading): _END_SEASON_AWARDS in frontend/app-admin-season.js has {kind: "most_mvps", name: "Most MVPs"} after best_match, and the preview row shows its value as a whole MVP count ("3 MVPs"), not with one decimal as for points."""
        js = _fe("app-admin-season.js")
        entries = re.findall(r'\{ kind: "(\w+)", name: "([^"]*)" \}', _js_list(js, "_END_SEASON_AWARDS"))
        i = entries.index(("most_mvps", "Most MVPs"))
        assert entries[i - 1][0] == "best_match"
        body = _fn_source(js, "endSeason")
        assert 'kind === "most_mvps" ? accoladeValueText(kind, winners[0].value)' in body
        # The shared formatter the preview row calls gives a whole count.
        out = _run_node(_globals_helpers_js() + """
console.log(JSON.stringify([accoladeValueText("most_mvps", 3), accoladeValueText("most_mvps", 1),
                            accoladeValueText("most_points", 3), accoladeValueText("most_mvps", null)]));
""")
        assert out == ["3 MVPs", "1 MVP", "3.0 pts", ""]

    def test_accolade_timeline_line_and_chip_show_icon_and_mvp_count(self):
        """Player popup (Node harness over the ACCOLADES block of app-globals.js): for {kind: "most_mvps", season "Season 16", value 3}, accoladeDetailLine returns "S16 Most MVPs · 3 MVPs" (not "3.0 pts"), and accoladeChipsHtml / accoladePipsHtml render the accolade-chip--most_mvps / accolade-pip--most_mvps element with data-lucide="star" and a tooltip naming Most MVPs."""
        acc = _a("most_mvps", "Season 16", value=3)
        line = _detail_line(acc)
        assert '<span class="card-detail-text">S16 Most MVPs · 3 MVPs</span>' in line
        assert "accolade-pip--most_mvps" in line and 'data-lucide="star"' in line
        assert "pts" not in line and "3.0" not in line
        chip = _chips([acc])
        assert "accolade-chip accolade-chip--outlined accolade-chip--most_mvps" in chip
        assert 'data-lucide="star"' in chip and "S16 Most MVPs" in chip
        assert 'title="3 MVPs"' in chip
        pip = _pips([acc])
        assert "accolade-pip accolade-pip--outlined accolade-pip--most_mvps" in pip
        assert 'data-lucide="star"' in pip
        assert 'data-tip="Most MVPs · S16"' in pip and 'aria-label="Most MVPs: S16"' in pip

    def test_accolade_detail_line_without_value_has_no_mvp_count(self):
        """Player popup (failure path, Node harness): a most_mvps accolade with value null (added by hand without a value) renders "S16 Most MVPs" with no " · " suffix, no "NaN" and no "MVPs" count."""
        line = _detail_line(_a("most_mvps", "Season 16"))
        assert '<span class="card-detail-text">S16 Most MVPs</span>' in line
        assert " · " not in line and "NaN" not in line
        chip = _chips([_a("most_mvps", "Season 16")])
        assert "title=" not in chip and "NaN" not in chip

    def test_most_mvps_colour_token_and_pip_rule_exist(self):
        """Symbols (source-reading): --accolade-mvp is defined in frontend/colors_and_type.css, design/colors_and_type.css is identical to it, and style.css sets --pip-color: var(--accolade-mvp) for .accolade-pip--most_mvps and .accolade-chip--most_mvps, before the "GUIDED TOUR (issue #144)" section."""
        tokens = _fe("colors_and_type.css")
        assert re.search(r"^\s*--accolade-mvp:\s*[^;]+;", tokens, flags=re.M)
        assert _read("design", "colors_and_type.css") == tokens
        css = _fe("style.css")
        before_tour = css[:css.index("GUIDED TOUR (issue #144)")]
        for selector in (".accolade-pip--most_mvps", ".accolade-chip--most_mvps"):
            bodies = _rule(before_tour, selector)
            assert len(bodies) == 1, selector
            assert "--pip-color: var(--accolade-mvp)" in bodies[0], selector

    def test_most_mvps_has_a_card_badge_file(self):
        """Cards: image._ACCOLADE_ICON_FILES["most_mvps"] == "Accolade_Most_MVPs.png", the file exists in assets/accolades/ and opens with Pillow as an image, and the keys of _ACCOLADE_ICON_FILES equal the keys of accolades.ACCOLADE_KINDS."""
        image = pytest.importorskip("image")
        from PIL import Image
        assert image._ACCOLADE_ICON_FILES["most_mvps"] == "Accolade_Most_MVPs.png"
        assert set(image._ACCOLADE_ICON_FILES) == {k["key"] for k in accolades.ACCOLADE_KINDS}
        folder = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "accolades")
        path = os.path.join(folder, "Accolade_Most_MVPs.png")
        assert os.path.isfile(path)
        with Image.open(path) as badge, Image.open(
                os.path.join(folder, "Accolade_Best_Single_Match.png")) as other:
            badge.load()
            assert badge.size == other.size and badge.mode == other.mode

    def test_most_mvps_card_priority_matches_the_other_awards(self):
        """Cards: image._ACCOLADE_PRIORITY["most_mvps"] equals the priority of most_points, best_average and best_match; _CARD_ACCOLADE_PRIORITY in app-globals.js has the same value for most_mvps; and image._select_accolade_keys(["played", "most_mvps", "div1"]) returns ["div1", "most_mvps", "played"]."""
        image = pytest.importorskip("image")
        prio = image._ACCOLADE_PRIORITY
        assert prio["most_mvps"] == prio["most_points"] == prio["best_average"] == prio["best_match"]
        js = _fe("app-globals.js")
        start = js.index("const _CARD_ACCOLADE_PRIORITY = {")
        frontend = {m.group(1): int(m.group(2))
                    for m in re.finditer(r"(\w+):\s*(\d+)", js[start:js.index("};", start)])}
        assert frontend["most_mvps"] == prio["most_mvps"]
        assert image._select_accolade_keys(["played", "most_mvps", "div1"]) == ["div1", "most_mvps", "played"]

    def test_card_accolade_slot_for_most_mvps_has_a_tooltip(self):
        """Cards (Node harness): cardAccoladeSlotsFromList([{kind: "most_mvps", season: "Season 16", value 3}]) returns one slot with key "most_mvps" whose tooltip/label text names "Most MVPs" and the season, like the slots of the other awards."""
        js = _fe("app-globals.js")
        hotspots = js[js.index("// CARD FACE HOTSPOTS (plan-card-art-polish)"):]
        slots = _run_node(_globals_helpers_js() + "\n" + hotspots + f"""
console.log(JSON.stringify(cardAccoladeSlotsFromList({json.dumps([_a("most_mvps", "Season 16", value=3)])})));
""")
        assert len(slots) == 1
        slot = slots[0]
        assert slot["key"] == "most_mvps" and slot["index"] == 0 and slot["count"] == 1
        assert slot["tip"] == "Most MVPs · S16"
        assert slot["aria"] == "Most MVPs: S16"


# ---------------------------------------------------------------------------
# Story 3: An Admin Can Add Most MVPs by Hand
# ---------------------------------------------------------------------------

class TestAdminAddsMostMvpsByHand:

    def test_post_season_accolades_accepts_most_mvps_with_player_and_value(self, db):
        """Add: POST /admin/season-accolades as a re-authed admin with {season_label "Season 15", kind "most_mvps", player_account_id, player_name, value 5} answers 200 and stores one row with kind most_mvps, that player, value 5.0, source "admin", and team_name, division and match_id None; an admin audit entry is written as for the other kinds."""
        client, _ = _admin_client(db)
        # A match id is only kept for best_match.
        resp = client.post("/admin/season-accolades", json=_mvp_body(match_id=99))
        assert resp.status_code == 200, resp.text
        rows = _rows(db)
        assert len(rows) == 1
        r = rows[0]
        assert (r.season_label, r.kind, r.player_account_id, r.player_name, r.value, r.source) == (
            "Season 15", "most_mvps", 7, "Glete", 5.0, "admin")
        assert r.team_name is None and r.division is None and r.match_id is None
        audit = _audits(db, "admin_accolade_added")
        assert len(audit) == 1 and "kind=most_mvps" in audit[0].detail

    def test_add_accolade_dialog_offers_most_mvps_kind(self):
        """Add (source-reading, html.parser): the #accKind select in frontend/index.html has an option value "most_mvps" labelled "Most MVPs", placed after "best_match" with the other player awards."""
        parser = _Options("accKind")
        parser.feed(_fe("index.html"))
        values = [v for v, _ in parser.options]
        assert ("most_mvps", "Most MVPs") in parser.options
        assert values[:4] == ["most_points", "best_average", "best_match", "most_mvps"]
        # The value field stays visible for it: only Played and the placements hide it.
        changed = _fn_source(_fe("app-admin-players.js"), "accKindChanged")
        assert 'getElementById("accValueWrap").hidden = isPlayed || isPlacement' in changed

    def test_post_season_accolades_most_mvps_without_player_returns_422(self, db):
        """Add (failure path): POST /admin/season-accolades with kind "most_mvps" and no player_account_id answers 422 ("needs a player"), as does one carrying a division or a user_id; no row is stored. A misspelt kind ("most_mvp") also answers 422."""
        client, _ = _admin_client(db)
        resp = client.post("/admin/season-accolades", json=_mvp_body(player_account_id=None))
        assert resp.status_code == 422
        assert "needs a player" in resp.text
        for body in (_mvp_body(division="div1"), _mvp_body(user_id=3), _mvp_body(kind="most_mvp")):
            assert client.post("/admin/season-accolades", json=body).status_code == 422, body
        assert _rows(db) == []

    def test_post_season_accolades_duplicate_most_mvps_returns_409(self, db):
        """Add (failure path): posting the same season, kind most_mvps and player a second time answers 409 and leaves exactly one row."""
        client, _ = _admin_client(db)
        assert client.post("/admin/season-accolades", json=_mvp_body()).status_code == 200
        assert client.post("/admin/season-accolades", json=_mvp_body(value=6)).status_code == 409
        rows = _rows(db)
        assert len(rows) == 1 and rows[0].value == 5.0

    def test_delete_season_accolade_removes_most_mvps_row(self, db):
        """Remove: DELETE /admin/season-accolades/{id} for a most_mvps row as a re-authed admin answers 200, the row is gone, other rows of the season stay, and an audit entry is written."""
        row = _acc(db, "Season 15", "most_mvps", 7, "Glete", value=5)
        _acc(db, "Season 15", "most_points", 7, "Glete", value=60)
        _acc(db, "Season 15", "played", 7, "Glete")
        client, _ = _admin_client(db)
        resp = client.delete(f"/admin/season-accolades/{row.id}")
        assert resp.status_code == 200, resp.text
        assert sorted(r.kind for r in _rows(db)) == ["most_points", "played"]
        audit = _audits(db, "admin_accolade_removed")
        assert len(audit) == 1 and "kind=most_mvps" in audit[0].detail

    def test_delete_most_mvps_accolade_requires_admin(self, db):
        """Remove (failure path): DELETE /admin/season-accolades/{id} for a most_mvps row from a signed-in non-admin answers 403 (401 when signed out) and the row stays."""
        row = _acc(db, "Season 15", "most_mvps", 7, "Glete", value=5)
        bob = _user(db, "bob")
        assert _client(db, login=bob).delete(f"/admin/season-accolades/{row.id}").status_code == 403
        assert _client(db).delete(f"/admin/season-accolades/{row.id}").status_code == 401
        assert len(_rows(db, kind="most_mvps")) == 1
        assert _audits(db, "admin_accolade_removed") == []


def test_most_mvps_value_must_be_a_whole_count():
    """Security review (Low): a hand-entered Most MVPs value is a whole number >= 1."""
    import pytest
    from pydantic import ValidationError
    from routers.admin_accolades import AccoladeIn, _whole_count

    base = {"season_label": "Season 16", "kind": "most_mvps", "player_account_id": 123}
    assert AccoladeIn(**base, value=3).value == 3
    assert AccoladeIn(**base).value is None
    for bad in (2.5, 0, -1):
        with pytest.raises(ValidationError):
            AccoladeIn(**base, value=bad)
    assert AccoladeIn(**{**base, "kind": "most_points"}, value=812.3).value == 812.3
    assert _whole_count(None) and _whole_count(4.0) and not _whole_count(0.5)
