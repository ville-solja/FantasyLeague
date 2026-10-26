"""
Tests for plan-issue-230-accolades-and-rank-in-player-popup.md (resolves GitHub issue #230).

The card viewer (`#revealModal`) loses the rank medal (`#revealRank`,
`_renderRevealRank`) and the Accolades section (`#revealAccolades`); the Tags
section stays and the player's name under the card gains a "Stats and accolades"
hint. The rank becomes a summary tile in the player popup (`_popupTilesHtml`,
after MVPs) and the header medal goes. The popup's Accolades section
(`renderPlayerAccolades`) swaps its chip timeline for #228 detail lines and a
"Played N seasons · S4–S16" summary with a disclosure.

  Story 1: The Card Popup Shows the Card
  Story 2: Rank as a Player Statistic
  Story 3: Accolades as Player Statistics
  Step 4:  Extra checks (CSS placement, tokens, phone width)

Harnesses: the #205 draw harness (`_run` in test_issue_205_card_draw_animations.py)
for the card viewer, with the app-globals ACCOLADES block and `rankMedalHtml` loaded
by indirect eval; the #208 popup harness (`_popup_src`) plus `rankMedalHtml` and
`_ownValue` for the player popup. Markup is parsed with `html.parser`.
"""

import json
import os
import re
from html.parser import HTMLParser

import pytest

from tests.test_issue_50_season_winners_and_holo_cards import _a
from tests.test_issue_205_card_draw_animations import _run as _run_draw
from tests.test_issue_208_player_popup_visualizations import (
    _P, _css_blocks, _fe, _fn_body, _fn_source, _popup_src, _rule, _run_node,
)
from tests.test_issue_228_card_visuals_rollback import (
    _CHAMPION, _TAGS, _globals_js, _ids, _parse, _reveal_modal_html,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rank_src():
    """`_RANK_MEDALS` and `rankMedalHtml` from app-globals.js."""
    g = _fe("app-globals.js")
    return g[g.index("const _RANK_MEDALS"):g.index("function _escHtml(s)")]


def _popup(body):
    """Run `body` (sets `out`, may await) after loading the popup in the #208 fake DOM."""
    g = _fe("app-globals.js")
    script = (_popup_src() + "\n" + _fn_source(g, "_ownValue") + "\n" + _rank_src()
              + "\nlet out = null;\n(async () => {\n" + body
              + "\nconsole.log(JSON.stringify(out));\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });\n")
    return _run_node(script)


_VOID = {"br", "img", "input", "meta", "hr", "link", "source", "wbr"}


class _ByClass(HTMLParser):
    """Every element carrying `cls`: its attributes, the tags inside it, its text and
    its text nodes (aria-hidden subtrees left out with skip_hidden)."""

    def __init__(self, cls, skip_hidden=False):
        super().__init__()
        self.cls, self.skip_hidden = cls, skip_hidden
        self.items, self._stack = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for _, it, _h in self._stack:
            if it is not None:
                it["inner"].append((tag, a))
        if tag in _VOID:
            return
        item = None
        if self.cls in (a.get("class") or "").split():
            item = {"tag": tag, "attrs": a, "text": "", "parts": [], "inner": []}
            self.items.append(item)
        self._stack.append((tag, item, a.get("aria-hidden") == "true"))

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        while self._stack:
            if self._stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if self.skip_hidden and any(h for _, _, h in self._stack):
            return
        for _, it, _h in self._stack:
            if it is not None:
                it["text"] += data
                if data.strip():
                    it["parts"].append(data.strip())


def _by_class(markup, cls, skip_hidden=False):
    p = _ByClass(cls, skip_hidden)
    p.feed(markup)
    return p.items


def _text(item):
    return " ".join(item["text"].split())


def _labels(markup):
    return [_text(x) for x in _by_class(markup, "lbl")]


# Card viewer harness prelude: the app-globals ACCOLADES block and rankMedalHtml as
# globals (spied), the player's accolades and tags stubbed, and a dump of every
# element the viewer may have written to.
def _viewer_prelude(accolades=None, tags=None):
    acc = _CHAMPION if accolades is None else accolades
    tg = _TAGS if tags is None else tags
    return f"""
  (0, eval)({json.dumps(_globals_js().replace("function _escHtml", "function _escHtmlUnused"))});
  (0, eval)({json.dumps(_rank_src())});
  let rankCalls = 0;
  const _realRank = globalThis.rankMedalHtml;
  globalThis.rankMedalHtml = (...a) => {{ rankCalls++; return _realRank(...a); }};
  globalThis.playerAccolades = () => {json.dumps(acc)};
  globalThis.playerTags = () => {json.dumps(tg)};
  const _textOf = n => [n.textContent, n.innerHTML, n.className, ...n.children.map(_textOf)].join(" ");
  const dump = () => Object.values(els).map(_textOf).join(" ") + " " + _textOf(document.body);
  const visibleText = n => [n.textContent, ...n.children.map(visibleText)].join(" ").replace(/\\s+/g, " ").trim();
"""


_RANKED_CHAMPION_CARD = ('{id: 3, card_type: "legendary", player_id: 7, player_name: "Glete", '
                         'team_name: "Greens", rank_tier: 54, leaderboard_rank: null}')
_ACCOLADE_TEXT = ("Champion", "Team Name", "812.3", "Most Points", "Played", "accolade-pip")
_RANK_TEXT = ("rank-medal", "Legend")


def _assert_no_rank_or_accolades(dump):
    for leak in _ACCOLADE_TEXT + _RANK_TEXT:
        assert leak not in dump, leak


# ---------------------------------------------------------------------------
# Story 1: The Card Popup Shows the Card
# ---------------------------------------------------------------------------

class TestCardViewerRemovals:

    def test_index_html_card_viewer_has_no_rank_or_accolades_section(self):
        """index.html `#revealModal` contains no element with id `revealRank` or
        `revealAccolades`, and still contains `section#revealTags` (parsed with
        html.parser)."""
        p = _ids(_reveal_modal_html())
        assert p.ids[0] == "revealModal"
        assert "revealRank" not in p.ids and "revealAccolades" not in p.ids
        assert "revealTags" in p.ids
        assert "reveal-details" in p.attrs["revealTags"]["class"].split()
        assert "hidden" in p.attrs["revealTags"]
        assert p.ids.index("revealPlayer") < p.ids.index("revealTags") < p.ids.index("revealActionBtn")

    def test_render_reveal_rank_removed_from_app_cards(self):
        """app-cards.js defines no `_renderRevealRank` function and no frontend
        file references `revealRank` or `revealAccolades`."""
        cards = _fe("app-cards.js")
        assert "_renderRevealRank" not in cards and "rankMedalHtml" not in cards
        frontend = os.path.join(_ROOT, "frontend")
        for name in sorted(os.listdir(frontend)):
            if name.endswith((".js", ".html", ".css")):
                src = _fe(name)
                assert "revealRank" not in src and "revealAccolades" not in src, name
        assert "accoladeDetailsHtml" not in cards and "playerAccolades" not in cards

    def test_card_viewer_css_for_rank_and_accolades_removed(self):
        """style.css has no `.reveal-rank` rule and no selector referencing
        `#revealRank` or `#revealAccolades`; the `.reveal-details` rules used by
        the Tags section remain."""
        css = _fe("style.css")
        assert _css_blocks(css, r"\.reveal-rank\b") == []
        assert _css_blocks(css, r"#revealRank|#revealAccolades") == []
        assert "reveal-rank" not in css
        assert _rule(css, ".reveal-details") and _rule(css, ".reveal-details[hidden]")

    def test_show_card_for_ranked_champion_renders_no_rank_or_accolades(self):
        """Harness: `showCard` for a card whose player has `rank_tier`, a
        champion accolade and tags writes no rank medal markup and no accolade
        detail lines anywhere in the modal; only the Tags section is populated
        and visible."""
        out = _run_draw(_viewer_prelude() + f"""
  showCard({_RANKED_CHAMPION_CARD}, "");
  out.dump = dump();
  out.rankCalls = rankCalls;
  out.tags = [els.revealTags.hidden, els.revealTags.innerHTML];
  out.ids = Object.keys(els);
""")
        _assert_no_rank_or_accolades(out["dump"])
        assert out["rankCalls"] == 0
        assert "revealRank" not in out["ids"] and "revealAccolades" not in out["ids"]
        hidden, tags = out["tags"]
        assert hidden is False
        assert [ln["text"] for ln in _parse(tags).lines] == ["Kana Cards admin", "Caster"]
        assert [s["title"] for s in _parse(tags).sections] == ["Tags"]

    def test_draw_reveal_shows_tags_after_flip_without_accolades(self):
        """#205 draw harness: during a draw `#revealTags` stays hidden until the
        flip finishes, then is shown with the tag lines; no accolade lines or
        rank medal are rendered at any point of the draw."""
        steps = _viewer_prelude() + """
  const tags = document.getElementById("revealTags");
  tags.hidden = true;
  DRAW = { status: 200, body: Object.assign({}, DRAW.body, { rank_tier: 54, leaderboard_rank: null }) };
  drawCard();
  out.firstVisible = null; out.leaks = [];
  for (let i = 0; i < 400; i++) {
    await advance(10);
    const d = dump();
    for (const leak of ["Champion", "812.3", "rank-medal", "Legend", "Played"]) {
      if (d.includes(leak) && !out.leaks.includes(leak)) out.leaks.push(leak);
    }
    if (!tags.hidden && out.firstVisible === null) out.firstVisible = NOW;
  }
  const flip = ANIMS.find(a => JSON.stringify(a.keyframes).includes("rotateY"));
  out.flipEnd = flip ? flip.at + flip.opts.duration : null;
  out.final = [tags.hidden, tags.innerHTML];
  out.rankCalls = rankCalls;
"""
        out = _run_draw(steps)
        assert out["leaks"] == [] and out["rankCalls"] == 0
        assert out["flipEnd"] is not None and out["firstVisible"] is not None
        assert out["flipEnd"] <= out["firstVisible"]
        hidden, html = out["final"]
        assert hidden is False
        assert [ln["text"] for ln in _parse(html).lines] == ["Kana Cards admin", "Caster"]

    def test_card_viewer_hides_tags_when_player_has_no_tags(self):
        """Failure path: for a player with no tags (but with accolades and a
        rank) `#revealTags` stays hidden and empty, and nothing else appears
        under the card besides the name."""
        out = _run_draw(_viewer_prelude(tags=[]) + f"""
  document.getElementById("revealTags").innerHTML = "old";
  showCard({_RANKED_CHAMPION_CARD}, "");
  out.tags = [els.revealTags.hidden, els.revealTags.innerHTML];
  out.dump = dump();
  out.name = visibleText(els.revealPlayer);
  out.ids = Object.keys(els);
""")
        assert out["tags"] == [True, ""]
        _assert_no_rank_or_accolades(out["dump"])
        assert "revealRank" not in out["ids"] and "revealAccolades" not in out["ids"]
        assert out["name"] == "Glete Stats and accolades"


class TestCardViewerNameHint:

    def test_reveal_name_carries_stats_and_accolades_hint(self):
        """Harness: after `showCard`, the player name element under the card
        contains the visible text "Stats and accolades" (not only a title
        attribute) alongside the player's name."""
        out = _run_draw(_viewer_prelude() + f"""
  showCard({_RANKED_CHAMPION_CARD}, "");
  const link = els.revealPlayer.children[0];
  out.text = visibleText(els.revealPlayer);
  out.linkText = link.textContent;
  out.hint = link.children.map(c => [c.className, c.textContent]);
  out.title = link.getAttribute("title");
""")
        assert out["text"] == "Glete Stats and accolades"
        assert out["linkText"] == "Glete"
        assert out["hint"] == [["reveal-player-hint", "Stats and accolades"]]
        assert out["title"] is None
        assert _rule(_fe("style.css"), ".reveal-player-hint")

    def test_reveal_name_click_and_keyboard_open_player_popup(self):
        """Harness: clicking the name element, or pressing Enter / Space on it,
        calls `openPlayerModal(card.player_id)` with the card's player id; the
        element is focusable (tabindex 0, role button)."""
        out = _run_draw(_viewer_prelude() + f"""
  const calls = [];
  openPlayerModal = id => calls.push(id);
  showCard({_RANKED_CHAMPION_CARD}, "");
  const link = els.revealPlayer.children[0];
  let prevented = 0;
  const key = k => link.onkeydown({{ key: k, preventDefault() {{ prevented++; }} }});
  link.onclick();
  key("Enter"); key(" "); key("a");
  out.calls = calls;
  out.prevented = prevented;
  out.focus = [link.tabIndex, link.getAttribute("role"), link.className];
""")
        assert out["calls"] == [7, 7, 7]
        assert out["prevented"] == 2
        assert out["focus"][0] == 0 and out["focus"][1] == "button"
        assert "entity-link" in out["focus"][2].split()

    def test_reveal_name_without_player_id_has_no_hint_or_link(self):
        """Failure path: a card with no `player_id` renders the name without the
        "Stats and accolades" hint and without a click handler that would call
        `openPlayerModal`."""
        out = _run_draw(_viewer_prelude() + """
  const calls = [];
  openPlayerModal = id => calls.push(id);
  showCard({id: 4, card_type: "common", player_name: "Anon", team_name: "T"}, "");
  out.text = visibleText(els.revealPlayer);
  out.children = els.revealPlayer.children.length;
  out.onclick = typeof els.revealPlayer.onclick;
  out.calls = calls;
""")
        assert out["text"] == "Anon"
        assert "Stats and accolades" not in out["text"]
        assert out["children"] == 0 and out["onclick"] != "function"
        assert out["calls"] == []


# ---------------------------------------------------------------------------
# Story 2: Rank as a Player Statistic
# ---------------------------------------------------------------------------

def _tiles(**over):
    return _popup(f"out = _popupTilesHtml({json.dumps(_P(**over))});")


def _rank_tile(**p):
    return _popup(f"out = _popupRankTile({json.dumps(p)});")


class TestRankTile:

    def test_popup_tiles_end_with_rank_tile_after_mvps(self):
        """`_popupTilesHtml(p)` for a player with `rank_tier` returns tiles in
        the order Matches, Avg pts, Total pts, Best match, MVPs, Rank; the last
        tile's label is "Rank"."""
        html = _tiles(rank_tier=54)
        assert _labels(html) == ["Matches", "Avg pts", "Total pts", "Best match", "MVPs", "Rank"]
        tiles = _by_class(html, "player-modal-stat")
        assert "player-modal-stat--rank" in tiles[-1]["attrs"]["class"].split()
        grid = _by_class(html, "player-popup-tiles")[0]
        assert "player-popup-tiles--ranked" in grid["attrs"]["class"].split()

    def test_rank_tile_value_shows_medal_symbol_and_name(self):
        """For `rank_tier=54` the Rank tile's value contains the medal symbol
        markup and the text "Legend 4"."""
        html = _rank_tile(rank_tier=54)
        val = _by_class(html, "val", skip_hidden=True)[0]
        assert _text(val) == "Legend 4"
        classes = [c for _, a in val["inner"] for c in (a.get("class") or "").split()]
        assert "rank-medal" in classes and "rank-medal--legend" in classes and "rank-medal-icon" in classes
        assert "★★★★" in html

    def test_rank_tile_immortal_shows_leaderboard_place(self):
        """For `rank_tier=80, leaderboard_rank=120` the Rank tile's value text
        is "Immortal #120"; for `rank_tier=80` with no leaderboard rank it is
        "Immortal"."""
        place = _rank_tile(rank_tier=80, leaderboard_rank=120)
        plain = _rank_tile(rank_tier=80)
        assert _text(_by_class(place, "val", skip_hidden=True)[0]) == "Immortal #120"
        assert _text(_by_class(plain, "val", skip_hidden=True)[0]) == "Immortal"
        assert "★" not in place and "★" not in plain

    def test_rank_tile_shows_opendota_date_line(self):
        """With `rank_fetched_at` set, the Rank tile has a sub line
        "OpenDota, <date>" with the date formatted from `rank_fetched_at`;
        without `rank_fetched_at` the line reads "OpenDota" with no date and no
        "Invalid Date"."""
        out = _popup("""
out = {
  dated: _popupRankTile({rank_tier: 54, rank_fetched_at: 1700000000}),
  date: _popupDate(1700000000),
  none: _popupRankTile({rank_tier: 54}),
  bad: _popupRankTile({rank_tier: 54, rank_fetched_at: "soon"}),
};
""")
        assert _text(_by_class(out["dated"], "sub")[0]) == f"OpenDota, {out['date']}"
        assert re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", out["date"])
        for key in ("none", "bad"):
            assert _text(_by_class(out[key], "sub")[0]) == "OpenDota"
            assert "Invalid" not in out[key] and "NaN" not in out[key]

    def test_unranked_player_has_no_rank_tile(self):
        """Failure path: `rank_tier` null, 0 or missing yields no tile labelled
        "Rank" and no empty tile placeholder; the tile count equals the unranked
        layout (five tiles)."""
        for over in ({"rank_tier": None}, {"rank_tier": 0}, {}):
            html = _tiles(**over)
            assert _labels(html) == ["Matches", "Avg pts", "Total pts", "Best match", "MVPs"], over
            assert len(_by_class(html, "player-modal-stat")) == 5
            assert "player-modal-stat--rank" not in html and "player-popup-tiles--ranked" not in html
        assert _popup("out = [_popupRankTile({}), _popupRankTile({rank_tier: null}), _popupRankTile({rank_tier: 0})];") == ["", "", ""]

    def test_rank_tile_text_carries_rank_and_medal_is_decorative(self):
        """The Rank tile's text content (ignoring aria-hidden nodes) includes the
        rank name, and the medal symbol element is `aria-hidden="true"` (or an
        image with empty alt)."""
        html = _rank_tile(rank_tier=33, rank_fetched_at=1700000000)
        tile = _by_class(html, "player-modal-stat", skip_hidden=True)[0]
        assert "Crusader 3" in _text(tile) and "Rank" in _text(tile)
        assert "★" not in _text(tile)  # the stars are decorative too
        icons = _by_class(html, "rank-medal-icon")
        assert len(icons) == 1 and icons[0]["attrs"].get("aria-hidden") == "true"
        assert _by_class(html, "rank-medal-stars")[0]["attrs"].get("aria-hidden") == "true"
        assert 'role="img"' not in html

    def test_rank_tile_escapes_or_ignores_non_numeric_input(self):
        """Failure path: a non-numeric `rank_tier` or `leaderboard_rank` (e.g. a
        string with markup) produces no injected markup in the tile output (no
        Rank tile, or a tile with escaped text only)."""
        out = _popup("""
out = {
  tier: _popupRankTile({rank_tier: "<img src=x onerror=alert(1)>"}),
  place: _popupRankTile({rank_tier: 80, leaderboard_rank: "<b>1</b>"}),
  fetched: _popupRankTile({rank_tier: 54, rank_fetched_at: "<i>x</i>"}),
};
""")
        assert out["tier"] == ""
        assert "<b>" not in out["place"] and "&lt;b&gt;" not in out["place"]
        assert _text(_by_class(out["place"], "val", skip_hidden=True)[0]) == "Immortal"
        assert "<i>" not in out["fetched"]
        assert _text(_by_class(out["fetched"], "sub")[0]) == "OpenDota"


def _ranked_player(**over):
    p = _P(rank_tier=54, leaderboard_rank=None, rank_fetched_at=1700000000,
           accolades=[_a("champion", "Season 15", "div1", "Team Name"), _a("played", "Season 15")])
    p.update(over)
    return p


class TestHeaderMedalRemoved:

    def test_open_player_modal_header_has_no_rank_medal(self):
        """`openPlayerModal` source no longer calls `rankMedalHtml` for the
        header, and a harness run for a ranked player renders no medal next to
        the team name in the header."""
        assert "rankMedalHtml" not in _fn_body(_fe("app-player-popup.js"), "openPlayerModal")
        out = _popup(f"""
const P = {json.dumps(_ranked_player())};
fetch = url => Promise.resolve(url.endsWith("/profile")
  ? {{ ok: false, json: async () => ({{}}) }}
  : {{ ok: true, json: async () => P }});
await openPlayerModal(10);
out = {{ team: document.getElementById("playerModalTeam").innerHTML,
        stats: document.getElementById("playerModalStats").innerHTML,
        name: document.getElementById("playerModalName").textContent }};
""")
        assert out["name"] == "Alpha"
        assert "Reds" in out["team"]
        assert "rank-medal" not in out["team"] and "Legend" not in out["team"]
        assert "Legend 4" in _text(_by_class(out["stats"], "player-modal-stat--rank", skip_hidden=True)[0])

    def test_header_keeps_tag_and_accolade_pips(self):
        """Failure guard: removing the medal leaves `#playerModalPips` in place,
        still filled with the tag and accolade pips for a decorated player."""
        html = _fe("index.html")
        modal = html[html.index('id="playerModal"'):html.index('id="playerModalStats"')]
        assert 'id="playerModalPips"' in modal
        out = _popup(f"""
_tagsByPlayer = {{"10": [{{key: "caster", label: "Caster"}}]}};
renderPlayerAccolades({json.dumps(_ranked_player())});
out = document.getElementById("playerModalPips").innerHTML;
""")
        assert _by_class(out, "card-tag-pip") and _by_class(out, "accolade-pip")
        assert out.index("card-tag-pip") < out.index("accolade-pip")
        assert "rank-medal" not in out


# ---------------------------------------------------------------------------
# Story 3: Accolades as Player Statistics
# ---------------------------------------------------------------------------

def _section(accolades, **over):
    """renderPlayerAccolades for a player with these accolades: (hidden, innerHTML)."""
    p = {"id": 10, "accolades": accolades, "current_season": "Season 17",
         "current_season_matches": 0, "holo_unlocked": False}
    p.update(over)
    return _popup(f"""
renderPlayerAccolades({json.dumps(p)});
const s = document.getElementById("playerModalAccolades");
out = [s.hidden, s.innerHTML];
""")


def _entries(html):
    return [e["parts"] for e in _by_class(html, "player-accolades-season")]


def _played(*seasons):
    return [_a("played", f"Season {n}") for n in seasons]


class TestAccoladesSection:

    def test_section_keeps_holo_banner_and_three_tiles(self):
        """`renderPlayerAccolades(p)` for a decorated player still renders the
        Holo banner and the tiles labelled Champion titles, Season awards and
        Seasons played."""
        acc = [_a("champion", "Season 15", "div1", "Team Name"), _a("most_points", "Season 15", value=812.3)] + _played(14, 15)
        hidden, html = _section(acc, holo_unlocked=True)
        assert hidden is False
        assert "Holo unlocked." in _text(_by_class(html, "player-accolades-holo")[0])
        assert _labels(html) == ["Champion titles", "Season awards", "Seasons played"]
        assert [_text(v) for v in _by_class(html, "val")] == ["1", "1", "2"]

    def test_section_absent_for_player_without_accolades(self):
        """Failure path: a player with no accolades (empty list, missing field)
        gets an empty result / hidden section, as today: no banner, no tiles, no
        timeline."""
        assert _section([]) == [True, ""]
        out = _popup("""
const s = document.getElementById("playerModalAccolades");
s.innerHTML = "old"; s.hidden = false;
renderPlayerAccolades({id: 10, holo_unlocked: true});
const a = [s.hidden, s.innerHTML];
renderPlayerAccolades(null);
out = [a, [s.hidden, s.innerHTML]];
""")
        assert out == [[True, ""], [True, ""]]


class TestAccoladesTimeline:

    def test_timeline_one_entry_per_season_newest_first(self):
        """Accolades across S12, S15 and S14 render three season entries in the
        order S15, S14, S12, each entry holding only that season's lines."""
        acc = [_a("most_points", "Season 12", value=500.0), _a("best_match", "Season 14", value=60.0),
               _a("most_points", "Season 15", value=812.3), _a("champion", "Season 15", "div1", "Team Name"),
               _a("champion", "Season 12", "div2", "Old")] + _played(12, 14, 15)
        _, html = _section(acc)
        assert _entries(html) == [
            ["S15 Div 1 Champion · with Team Name", "S15 Most Points · 812.3 pts"],
            ["S14 Best Single Match · 60.0 pts"],
            ["S12 Div 2 Champion · with Old", "S12 Most Points · 500.0 pts"],
        ]
        assert _by_class(html, "player-accolades-timeline")[0]["tag"] == "ol"

    def test_timeline_uses_detail_lines_not_chips(self):
        """The timeline renders `accoladeDetailsHtml`-style detail lines (the
        #228 line classes) and no longer the old chip elements whose details
        lived only in title attributes."""
        acc = [_a("champion", "Season 15", "div1", "Team Name"), _a("most_points", "Season 15", value=812.3)] + _played(15)
        _, html = _section(acc)
        assert "accolade-chip" not in html and "title=" not in html
        lines = _parse(html).lines
        assert [ln["text"] for ln in lines if not ln["details"]] == [
            "S15 Div 1 Champion · with Team Name", "S15 Most Points · 812.3 pts"]
        keyed = sorted(lines, key=lambda ln: ln["details"])  # the Played line sits above the timeline
        for ln, key in zip(keyed, ("div1", "most_points", "played")):
            assert "card-detail-symbol" in ln["symbol"] and f"accolade-pip--{key}" in ln["symbol"]
            assert ln["aria_hidden"] == "true"
        fn = _fn_body(_fe("app-player-popup.js"), "renderPlayerAccolades")
        assert "accoladeDetailLine(a)" in fn and "accoladeChipsHtml" not in fn

    def test_champion_line_names_division_and_team(self):
        """A champion accolade for S15 Div 1 with team "Team Name" renders the
        line text "S15 Div 1 Champion · with Team Name"; team names are
        HTML-escaped."""
        _, html = _section([_a("champion", "Season 15", "div1", "Team Name")])
        assert _entries(html) == [["S15 Div 1 Champion · with Team Name"]]
        _, evil = _section([_a("champion", "Season 15", "div1", "<img src=x>&Co")])
        assert "<img" not in evil and "&lt;img src=x&gt;&amp;Co" in evil
        assert _entries(evil) == [["S15 Div 1 Champion · with <img src=x>&Co"]]

    def test_point_accolade_line_shows_value(self):
        """A Most Points accolade with value 812.3 renders the line text
        "S15 Most Points · 812.3 pts"."""
        _, html = _section([_a("most_points", "Season 15", value=812.3)])
        assert _entries(html) == [["S15 Most Points · 812.3 pts"]]

    def test_champion_without_team_name_omits_with_clause(self):
        """Failure path: a champion accolade with no team name renders
        "S15 Div 1 Champion" without a dangling " · with" and without
        "undefined" or "null"."""
        _, html = _section([_a("champion", "Season 15", "div1", None)])
        assert _entries(html) == [["S15 Div 1 Champion"]]
        for bad in (" · with", "undefined", "null"):
            assert bad not in html


class TestSeasonsPlayed:

    def _played_line(self, html):
        lines = [ln for ln in _parse(html).lines if ln["details"]]
        assert len(lines) == 1
        return lines[0]

    def test_played_summary_line_counts_from_season_4(self):
        """A player who played S4–S16 with gaps totalling seven seasons shows
        the line "Played 7 seasons · S4–S16"; seasons before Season 4 are not
        counted."""
        _, html = _section(_played(2, 3, 4, 5, 6, 10, 14, 15, 16))
        line = self._played_line(html)
        assert line["summary"] == "Played 7 seasons · S4–S16"
        assert line["icon"] == "calendar-check" and "accolade-pip--played" in line["symbol"]
        assert "S3" not in line["seasons"] and "S2" not in line["seasons"]
        assert _entries(html) == []  # Played rows are not timeline entries

    def test_played_list_behind_disclosure(self):
        """The per-season list sits inside a `<details>` element (closed by
        default) whose `<summary>` is the Played line; each season appears once
        in the list."""
        _, html = _section(_played(4, 5, 5, 6) + [_a("champion", "Season 6", "div1", "T")])
        details = _by_class(html, "card-detail-more")
        assert len(details) == 1 and details[0]["tag"] == "details"
        assert "open" not in details[0]["attrs"]
        assert ("summary", {"class": "card-detail-text"}) in details[0]["inner"]
        line = self._played_line(html)
        assert line["summary"] == "Played 3 seasons · S4–S6"
        assert line["seasons"] == ["S6", "S5", "S4"]

    def test_played_list_shows_live_season_match_count(self):
        """The live (current) season's entry in the disclosure shows its match
        count (e.g. "S16 · 5 matches")."""
        _, html = _section(_played(14, 15, 16), current_season="Season 16", current_season_matches=5)
        assert self._played_line(html)["seasons"] == ["S16 · 5 matches", "S15", "S14"]
        _, one = _section(_played(16), current_season="Season 16", current_season_matches=1)
        assert self._played_line(one)["seasons"] == ["S16 · 1 match"]
        _, unknown = _section(_played(16), current_season="Season 16", current_season_matches=None)
        assert self._played_line(unknown)["seasons"] == ["S16"]

    def test_played_single_season_uses_singular(self):
        """Failure path: a player with one played season gets
        "Played 1 season · S16" (singular, no range dash)."""
        _, html = _section(_played(16))
        assert self._played_line(html)["summary"] == "Played 1 season · S16"
        assert "–" not in self._played_line(html)["summary"]

    def test_seasons_played_tile_stays(self):
        """The Seasons played tile still shows the season count alongside the
        new summary line."""
        _, html = _section(_played(2, 3, 4, 5, 6, 10, 14, 15, 16))
        labels, vals = _labels(html), [_text(v) for v in _by_class(html, "val")]
        assert vals[labels.index("Seasons played")] == "7"
        assert self._played_line(html)["summary"].startswith("Played 7 seasons")
        assert html.index("Seasons played") < html.index("player-accolades-played")


# ---------------------------------------------------------------------------
# Step 4: CSS placement, tokens, phone width
# ---------------------------------------------------------------------------

_NEW_CSS = r"\.player-modal-stat--rank|\.player-popup-tiles--ranked|\.player-accolades-(?:played|timeline|season)|\.reveal-player-hint"


class TestPopupCss:

    def test_new_css_before_guided_tour_and_tokens_only(self):
        """The Rank tile and timeline line CSS rules sit before the
        "GUIDED TOUR (issue #144)" header in style.css and use only `var(--…)`
        colour tokens (no hex, rgb or rgba literals)."""
        css = _fe("style.css")
        tour = css.index("GUIDED TOUR (issue #144)")
        rules = _css_blocks(css, _NEW_CSS)
        selectors = " ".join(sel for sel, _ in rules)
        for wanted in (".player-modal-stat--rank .rank-medal", ".player-popup-tiles--ranked",
                       ".player-accolades-played", ".player-accolades-season", ".reveal-player-hint"):
            assert wanted in selectors, wanted
        assert _css_blocks(css[tour:], _NEW_CSS) == []
        for sel, body in rules:
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", body), sel
            for prop in ("color", "background", "border-color"):
                for m in re.finditer(rf"(?<![-\w]){prop}:\s*([^;]+);", body):
                    assert m.group(1).strip().startswith("var(--"), (sel, prop)
        assert "issue 230" in css and "#230" not in css
        assert "player-accolades-season-label" not in css + _fe("app-player-popup.js")

    def test_tiles_and_timeline_wrap_at_phone_width(self):
        """The tile grid and timeline lines wrap at phone width: no fixed widths
        above 343px, lines allow wrapping (`overflow-wrap` / `flex-wrap`), and no
        `white-space: nowrap` without an ellipsis fallback."""
        css = _fe("style.css")
        for sel, body in _css_blocks(css, _NEW_CSS):
            if "nowrap" in body:
                assert "text-overflow: ellipsis" in body, sel
            for m in re.finditer(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", body):
                assert int(m.group(1)) <= 343, sel
        medal = _rule(css, ".player-modal-stat--rank .rank-medal")[0]
        assert "white-space: normal" in medal and "flex-wrap: wrap" in medal
        assert "overflow-wrap: anywhere" in medal
        ranked = _rule(css, ".player-popup-tiles--ranked")
        assert any("repeat(3, minmax(0, 1fr))" in b for b in ranked)
        assert any("repeat(2, minmax(0, 1fr))" in b for b in ranked)  # the phone layout
        phone = css[css.index("@media (max-width: 640px) {\n  .player-popup-tiles,"):]
        assert ".player-popup-tiles--ranked" in phone[:phone.index("}")]
        assert "min-width: 0" in _rule(css, ".player-accolades-season")[0]
        assert "overflow-wrap: anywhere" in _rule(css, ".card-detail-text")[0]
        assert "flex-wrap: wrap" in _rule(css, ".card-detail-seasons")[0]
