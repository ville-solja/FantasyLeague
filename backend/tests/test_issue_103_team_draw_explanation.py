"""
Tests for plan-issue-103-team-draw-explanation (resolves GitHub issue #103).

Covers the three user stories from
markdown/plans/plan-issue-103-team-draw-explanation.md. Most criteria are
frontend copy, so they are static checks against `frontend/index.html`,
`frontend/app-cards.js` and `frontend/app-globals.js` (paths resolved from the
repo root, same pattern as test_draw_panel_redesign.py and
test_how_to_play_role_subtabs.py). The admin label criteria are backend tests
of `seed.DEFAULT_WEIGHTS` / `seed.seed_weights()` with `seed.SessionLocal`
patched to an in-memory SQLite session (same pattern as test_seed.py).

  Story: Team Draw Explained on How to Play
    - Users subtab Cards & Drawing section has a team draw bullet, right after
      the standard draw bullet
    - Bullet says the team draw gives one card from a team you choose, at the
      current team draw cost in tokens
    - Cost is read from GET /config (team_booster_cost) at page load, 3 fallback
    - Bullet says rarity uses the same odds as the standard draw, and you get an
      unowned player from that team until you own them all
    - Bullet says fully collected teams are greyed out in the team picker

  Story: Clear Team Draw Naming in the Draw Panel
    - Button reads "Draw from a team (N Tokens)" with live cost + token name
    - Hint under the button: "One card from a team you pick, favouring players
      you don't own yet."
    - Picker confirm reads "Draw 1 card from this team"; cost line reads
      "Costs N Tokens for 1 card"
    - No user-visible "Booster" in index.html or app-cards.js; internal
      identifiers (boosterBtn, /deck/booster, /draw/booster/{id},
      _drawBoosterForTeam, ...) unchanged
    - Reveal modal "Draw another card" still repeats a team draw from the same
      team (static check of revealAction() logic)

  Story: Team Draw Cost Label for Admins
    - DEFAULT_WEIGHTS labels team_booster_cost "Team draw cost (Tokens)"; the
      Scoring Weights panel renders the DB label (w.label), not a hard-coded one
    - seed_weights() refreshes the label of every existing weight row to the
      DEFAULT_WEIGHTS label on startup
    - Refreshing labels never changes a weight's value

"No user-visible Booster" guidance for the implementer: only user-visible text
counts — HTML text nodes (outside <script>/<style> and comments), button labels,
visible attributes (title, placeholder, aria-label, alt), and JS string/template
literals that are assigned to .textContent / .innerHTML / .title or passed to
setStatus()/showToast(). Ignore identifiers, element IDs, function names, CSS
class names (booster-team-tile), HTML/JS comments, and API paths such as
/deck/booster and /draw/booster/. The failure-path stub must prove the checker
flags a planted visible "Booster" while ignoring those internal names.

Manual verification (not automated):
  - With team_booster_cost set to 4 in the admin panel, reload: the Draw panel
    button, picker cost line and How to Play bullet all show 4.
  - On an existing database, restart the app: Scoring Weights shows
    "Team draw cost (Tokens)" and the value is unchanged.
  - Do a team draw, then click "Draw another card": it draws from the same
    team again (the static stub below only checks the JS wiring).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pathlib
import re
from html.parser import HTMLParser
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "frontend" / "index.html"
APP_CARDS_JS = REPO_ROOT / "frontend" / "app-cards.js"
APP_GLOBALS_JS = REPO_ROOT / "frontend" / "app-globals.js"
APP_ADMIN_INGEST_JS = REPO_ROOT / "frontend" / "app-admin-ingest.js"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path):
    return path.read_text(encoding="utf-8")


def _users_cards_drawing_items(html):
    """<li> inner HTML of the Cards & Drawing list in #howtoplay-panel-users."""
    start = html.index('id="howtoplay-panel-users"')
    heading = html.index("Cards &amp; Drawing", start)
    ul_start = html.index("<ul", heading)
    ul_end = html.index("</ul>", ul_start)
    return re.findall(r"<li>(.*?)</li>", html[ul_start:ul_end], re.S)


def _team_draw_bullet(html):
    items = _users_cards_drawing_items(html)
    matches = [i for i, li in enumerate(items) if "team draw" in _plain(li).lower()]
    assert len(matches) == 1, f"expected exactly one team draw bullet, got {matches}"
    return matches[0], items


def _plain(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def _element_text(html, element_id):
    m = re.search(r'<(\w+)[^>]*\bid="' + re.escape(element_id) + r'"[^>]*>(.*?)</\1>', html, re.S)
    assert m, f"#{element_id} not found"
    return _plain(m.group(2))


def _js_function_body(js, name):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", js)
    assert m, f"function {name} not found"
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
    return js[m.end():i - 1]


# A "booster" occurrence is user-visible only as a standalone word. Identifiers
# (boosterBtn, _drawBoosterForTeam), CSS classes (booster-team-tile) and API
# paths (/deck/booster) always glue it to other identifier/path characters.
_BOOSTER_WORD = re.compile(r"(?<![\w$./#-])booster(?![\w$/-])", re.I)
_VISIBLE_ATTRS = {"title", "placeholder", "aria-label", "alt"}


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for k, v in attrs:
            if k in _VISIBLE_ATTRS and v:
                self.chunks.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def _visible_booster_in_html(html):
    parser = _VisibleTextParser()
    parser.feed(html)
    return [c.strip() for c in parser.chunks if _BOOSTER_WORD.search(c)]


def _strip_js_comments(js):
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|[^:\\])//.*$", r"\1", js, flags=re.M)


def _visible_booster_in_js(js):
    return [line.strip() for line in _strip_js_comments(js).splitlines() if _BOOSTER_WORD.search(line)]


@pytest.fixture
def seed_env(monkeypatch):
    """In-memory DB with seed.SessionLocal patched to use it."""
    monkeypatch.delenv("WEIGHTS_JSON", raising=False)
    from database import Base
    import models  # noqa: F401  (register tables on Base.metadata)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with patch("seed.SessionLocal", side_effect=Session):
        yield Session


# ---------------------------------------------------------------------------
# Story: Team Draw Explained on How to Play
# ---------------------------------------------------------------------------

def test_howtoplay_team_draw_bullet_follows_standard_draw_bullet():
    """#howtoplay-panel-users Cards & Drawing list has a team draw <li> immediately after the 1-token standard draw <li>."""
    idx, items = _team_draw_bullet(_read(INDEX_HTML))
    assert idx > 0
    prev = _plain(items[idx - 1]).lower()
    assert "draw a card" in prev and "1 token" in prev


def test_howtoplay_team_draw_bullet_says_one_card_from_chosen_team_at_cost():
    """Team draw bullet says it gives one card from a team you choose, costing the team draw cost (#htpTeamDrawCost span) in tokens."""
    idx, items = _team_draw_bullet(_read(INDEX_HTML))
    li = items[idx]
    assert re.search(r'<span id="htpTeamDrawCost">\d+</span>\s*tokens', li)
    text = _plain(li).lower()
    assert "one card" in text
    assert "team you pick" in text or "team you choose" in text


def test_howtoplay_team_draw_cost_span_filled_from_config():
    """app-globals.js (or wherever _teamBoosterCost is set from /config) writes team_booster_cost into #htpTeamDrawCost at page load."""
    js = _read(APP_GLOBALS_JS)
    body = _js_function_body(js, "loadConfig")
    set_idx = body.index("_teamBoosterCost = cfg.team_booster_cost")
    fill = re.search(r'getElementById\("htpTeamDrawCost"\)', body)
    assert fill and fill.start() > set_idx
    assert re.search(r"\.textContent\s*=\s*_teamBoosterCost", body[fill.start():])


def test_howtoplay_team_draw_cost_fallback_is_3_when_config_unavailable():
    """Failure path: with /config unavailable the #htpTeamDrawCost span's static text is 3 and the JS default _teamBoosterCost stays 3."""
    assert _element_text(_read(INDEX_HTML), "htpTeamDrawCost") == "3"
    js = _read(APP_GLOBALS_JS)
    assert re.search(r"let _teamBoosterCost\s*=\s*3;", js)
    # The span is only written inside the res.ok branch, after the cost is set.
    body = _js_function_body(js, "loadConfig")
    assert body.index("if (res.ok)") < body.index("htpTeamDrawCost")


def test_howtoplay_team_draw_bullet_explains_rarity_and_unowned_player_preference():
    """Bullet says rarity uses the same odds as the standard draw and you get an unowned player from that team until you own them all."""
    idx, items = _team_draw_bullet(_read(INDEX_HTML))
    text = _plain(items[idx]).lower()
    assert "rarity uses the same odds as a normal draw" in text
    assert "you don't own yet" in text
    assert "until you own them all" in text


def test_howtoplay_team_draw_bullet_mentions_greyed_out_collected_teams():
    """Bullet says fully collected teams are greyed out in the team picker."""
    idx, items = _team_draw_bullet(_read(INDEX_HTML))
    text = _plain(items[idx]).lower()
    assert "fully collected teams are greyed out" in text
    assert "team picker" in text


def test_howtoplay_team_draw_bullet_does_not_describe_a_multi_card_pack():
    """Failure path: the bullet must not call it a booster/pack or imply several cards are given."""
    idx, items = _team_draw_bullet(_read(INDEX_HTML))
    text = _plain(items[idx]).lower()
    assert "booster" not in text
    assert "pack" not in text
    assert not re.search(r"\b(several|multiple|\d+|two|three|five) cards\b", text)


# ---------------------------------------------------------------------------
# Story: Clear Team Draw Naming in the Draw Panel
# ---------------------------------------------------------------------------

def test_update_booster_btn_text_is_draw_from_a_team_with_live_cost():
    """_updateBoosterBtn() sets `Draw from a team (${cost} ${_tokenName})` and the static #boosterBtn fallback in index.html matches."""
    body = _js_function_body(_read(APP_CARDS_JS), "_updateBoosterBtn")
    assert "btn.textContent = `Draw from a team (${cost} ${_tokenName})`;" in body
    assert "const cost = _teamBoosterCost ?? 3;" in body
    assert _element_text(_read(INDEX_HTML), "boosterBtn") == "Draw from a team (3 Tokens)"


def test_booster_btn_hint_line_under_button():
    """A hint line under #boosterBtn gives both draw costs (team cost in #boosterHintCost) and the
    unowned-players-first rule, which applies to both draws."""
    html = _read(INDEX_HTML)
    assert _element_text(html, "boosterHint") == (
        "1 token for a random player, or 3 for a player from a team you pick. "
        "You get players you don't own yet first."
    )
    assert '<span id="boosterHintCost">3</span> for a player from a team you pick.' in html
    body = _js_function_body(_read(APP_GLOBALS_JS), "loadConfig")
    assert re.search(r'getElementById\("boosterHintCost"\)', body)
    btn_pos = html.index('id="boosterBtn"')
    hint_pos = html.index('id="boosterHint"')
    assert btn_pos < hint_pos < html.index('id="redeemCodeInput"')


def test_booster_modal_confirm_button_reads_draw_1_card_from_this_team():
    """#boosterDrawBtn label reads "Draw 1 card from this team" (in index.html and any JS that resets its text)."""
    assert _element_text(_read(INDEX_HTML), "boosterDrawBtn") == "Draw 1 card from this team"
    js = _read(APP_CARDS_JS)
    # Any JS that rewrites the confirm button's label must keep the same text.
    for m in re.finditer(r"drawBtn\.textContent\s*=\s*(.+?);", js):
        assert "Draw 1 card from this team" in m.group(1)


def test_booster_cost_label_reads_costs_n_tokens_for_1_card():
    """loadBoosterTeams() sets boosterCostLabel to `Costs ${cost} ${_tokenName} for 1 card` (not "per draw")."""
    body = _js_function_body(_read(APP_CARDS_JS), "loadBoosterTeams")
    assert "costLabel.textContent = `Costs ${cost} ${_tokenName} for 1 card`" in body
    assert "per draw" not in body


def test_no_user_visible_booster_text_in_index_html_or_app_cards_js():
    """No user-visible text (HTML text nodes, visible attributes, JS literals assigned to textContent/innerHTML/setStatus) contains "Booster"."""
    assert _visible_booster_in_html(_read(INDEX_HTML)) == []
    assert _visible_booster_in_js(_read(APP_CARDS_JS)) == []


def test_user_visible_booster_checker_flags_planted_text_but_ignores_identifiers():
    """Failure path: the visible-text checker flags a planted "Draw Booster" label but ignores boosterBtn, booster-team-tile, _drawBoosterForTeam, /deck/booster and comments."""
    clean_html = (
        '<!-- Team Booster Modal -->'
        '<button id="boosterBtn" class="booster-team-tile" onclick="openBoosterModal()">Draw from a team</button>'
        '<script>const x = "Booster";</script>'
    )
    assert _visible_booster_in_html(clean_html) == []
    assert _visible_booster_in_html('<button id="boosterBtn">Draw Booster</button>') == ["Draw Booster"]
    assert _visible_booster_in_html('<button title="Team booster draw">x</button>') == ["Team booster draw"]

    clean_js = (
        "// Team Booster Draw\n"
        "/* booster */\n"
        'const btn = document.getElementById("boosterBtn");\n'
        "await fetch(`${API}/deck/booster`);\n"
        "await fetch(`${API}/draw/booster/${teamId}`, { method: \"POST\" });\n"
        "_drawBoosterForTeam(teamId);\n"
        'document.querySelectorAll(".booster-team-tile");\n'
    )
    assert _visible_booster_in_js(clean_js) == []
    planted = clean_js + 'btn.textContent = "Draw Booster";\n'
    assert _visible_booster_in_js(planted) == ['btn.textContent = "Draw Booster";']
    assert _visible_booster_in_js('setStatus("deckStatus", `Booster failed`, false);')


def test_internal_booster_identifiers_unchanged():
    """Internal names stay: #boosterBtn, #boosterModal, #boosterDrawBtn, /deck/booster, /draw/booster/, _drawBoosterForTeam, openBoosterModal."""
    html = _read(INDEX_HTML)
    for el_id in ("boosterBtn", "boosterModal", "boosterDrawBtn", "boosterCostLabel",
                  "boosterTeamGrid", "boosterStatus"):
        assert f'id="{el_id}"' in html, el_id
    assert 'onclick="openBoosterModal()"' in html
    assert 'onclick="drawBooster()"' in html
    js = _read(APP_CARDS_JS)
    for token in ("`${API}/deck/booster`", "`${API}/draw/booster/${teamId}`",
                  "async function _drawBoosterForTeam(", "function openBoosterModal(",
                  "function _updateBoosterBtn(", "function loadBoosterTeams(",
                  "booster-team-tile"):
        assert token in js, token


def test_reveal_action_repeats_team_draw_for_same_team():
    """revealAction() still calls _drawBoosterForTeam(_revealBoosterTeamId) when the reveal came from a team draw, and showReveal() stores the team id."""
    js = _read(APP_CARDS_JS)
    action = _js_function_body(js, "revealAction")
    assert re.search(r"if \(_revealBoosterTeamId\)\s*\{\s*const teamId = _revealBoosterTeamId;"
                     r"\s*closeReveal\(\);\s*_drawBoosterForTeam\(teamId\);", action)
    reveal = _js_function_body(js, "showReveal")
    assert "_revealBoosterTeamId = boosterTeamId ?? null;" in reveal
    draw = _js_function_body(js, "_drawBoosterForTeam")
    assert "showReveal(data, teamId);" in draw


# ---------------------------------------------------------------------------
# Story: Team Draw Cost Label for Admins
# ---------------------------------------------------------------------------

def test_default_weights_team_booster_cost_label_is_team_draw_cost():
    """DEFAULT_WEIGHTS labels team_booster_cost "Team draw cost (Tokens)" and the Scoring Weights panel renders w.label from the DB."""
    import seed
    labels = {w["key"]: w["label"] for w in seed.DEFAULT_WEIGHTS}
    assert labels["team_booster_cost"] == "Team draw cost (Tokens)"
    assert "${w.label}" in _read(APP_ADMIN_INGEST_JS)


def test_seed_weights_refreshes_stale_labels_on_existing_rows(seed_env):
    """seed_weights() on a DB whose weight rows have stale labels (e.g. "Team booster draw cost (Tokens)") rewrites every label to DEFAULT_WEIGHTS."""
    import seed
    from models import Weight

    seed.seed_weights()
    db = seed_env()
    for row in db.query(Weight).all():
        row.label = "Team booster draw cost (Tokens)" if row.key == "team_booster_cost" else "stale"
    db.commit()
    db.close()

    seed.seed_weights()

    db = seed_env()
    labels = {w.key: w.label for w in db.query(Weight).all()}
    db.close()
    assert labels == {w["key"]: w["label"] for w in seed.DEFAULT_WEIGHTS}
    assert labels["team_booster_cost"] == "Team draw cost (Tokens)"


def test_seed_weights_label_refresh_does_not_change_values(seed_env):
    """Failure path: rows with stale labels and admin-edited values keep their values after seed_weights() refreshes the labels."""
    import seed
    from models import Weight

    seed.seed_weights()
    db = seed_env()
    edited = {}
    for row in db.query(Weight).all():
        row.label = "stale"
        row.value = row.value + 7.5
        edited[row.key] = row.value
    db.commit()
    db.close()

    seed.seed_weights()

    db = seed_env()
    rows = db.query(Weight).all()
    db.close()
    assert {w.key: w.value for w in rows} == edited
    assert all(w.label != "stale" for w in rows)
