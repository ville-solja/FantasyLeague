"""Tests for plan-card-art-polish.md.

Five follow-up refinements to the card-art-accolade-redesign (#239): the
accolade count badge is hard to read, accolade badges give no information on
hover, the card face has no click-through to a player's or team's profile,
team logos fill their slot inconsistently (contain-fit, not a stretch bug),
and the My Team roster/bench cards are small with a horizontal scrollbar.

  Story 1: Legible, Informative Accolade Badges
  Story 2: Jump to a Player or Team From Their Card
  Story 3: Consistent Team Logo Fill
  Story 4: Bigger Cards, Five to a Row

Frontend: reuse `_fe`, `_rule`, `_css_blocks`, `_run_node`, `_fn_source`, `_a` and
the Node-harness pattern of test_issue_50/228 (`_globals_helpers_js`, the
app-globals.js ACCOLADES block). Image: reuse `_image`, `_no_fetch`, `_render` from
test_issue_228.
"""

import io
import json
import re

import pytest

import models  # noqa: F401  (register tables for the db fixture)
from models import Card, Player, PlayerMatchStats, Team, User
from tests.test_issue_50_season_winners_and_holo_cards import (  # noqa: F401  (db fixture used by name)
    _a, _css_blocks, _fe, _fn_source, _globals_helpers_js, _run_node, db,
)
from tests.test_issue_228_card_visuals_rollback import _image, _render, _rule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, tokens=10, username="tester", email="t@t.com"):
    u = User(username=username, email=email, password_hash="x", tokens=tokens)
    db.add(u)
    db.flush()
    return u


def _make_player(db, player_id, name="PlayerOne"):
    p = Player(id=player_id, name=name)
    db.add(p)
    db.flush()
    return p


def _seed_team_player(db, team_id, player_id, team_name=None):
    if db.get(Team, team_id) is None:
        db.add(Team(id=team_id, name=team_name or f"Team{team_id}"))
    db.add(PlayerMatchStats(player_id=player_id, match_id=9000 + player_id, team_id=team_id,
                            fantasy_points=1.0, kills=1))
    db.flush()


def _rects_overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _base_css():
    """style.css up to the shared max-width:768px breakpoint (there is only one),
    so `.card-grid` lookups in the base stylesheet don't also match the phone rule."""
    css = _fe("style.css")
    return css[:css.index("@media (max-width: 768px)")]


def _hotspot_js():
    """`_globals_helpers_js()` (ACCOLADE_KINDS, _accoladeKind, _accoladePipText, etc.)
    plus the card-face hotspot helpers (`cardAccoladeSlotsFromList`, `cardHotspotOverlayHtml`,
    ...). The hotspot helpers live right after the `// END ACCOLADES (issue 50)` marker in
    app-globals.js, deliberately outside the block `_globals_helpers_js()` loads, so this
    test file's Node harness doesn't bloat the one shared by many other tests."""
    js = _fe("app-globals.js")
    start = js.index("// CARD FACE HOTSPOTS (plan-card-art-polish)")
    return _globals_helpers_js() + "\n" + js[start:]


def _node_overlay(card_json, extra=""):
    return _run_node(_hotspot_js() + extra + f"""
console.log(JSON.stringify(cardHotspotOverlayHtml({card_json})));
""")


# ---------------------------------------------------------------------------
# Story 1: Legible, Informative Accolade Badges
# ---------------------------------------------------------------------------

class TestLegibleInformativeAccoladeBadges:

    def test_accolade_count_badge_sizing_prevents_clipping(self):
        """AC: the accolade count badge's digits are at least 20% larger than
        before (image._ACCOLADE_COUNT_FONT_SIZE 17->20) and the badge circle
        grows (image._ACCOLADE_COUNT_BADGE_RADIUS 11->13) so a "9+" count
        never clips the circle's edge."""
        image = _image()
        assert image._ACCOLADE_COUNT_FONT_SIZE == 20
        assert image._ACCOLADE_COUNT_BADGE_RADIUS == 13
        from PIL import Image, ImageDraw
        probe = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        font = image._get_font(image._ACCOLADE_COUNT_FONT_SIZE)
        bbox = draw.textbbox((0, 0), "9+", font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        diameter = image._ACCOLADE_COUNT_BADGE_RADIUS * 2
        assert text_w < diameter, (text_w, diameter)
        assert text_h < diameter, (text_h, diameter)

    def test_accolade_badge_tooltip_shows_name_and_season_breakdown(self):
        """AC: hovering, focusing or tapping any accolade badge on a rendered
        card shows a tooltip naming that accolade and, when held more than
        once, how many times and in which seasons (frontend hotspot/tooltip
        wiring over the card image, via the existing `[data-tip]` engine)."""
        accolades_list = [
            _a("champion", "Season 15", "div1", "Reds"),
            _a("champion", "Season 12", "div1", "Blues"),
        ]
        out = _run_node(_hotspot_js() + f"""
console.log(JSON.stringify(cardAccoladeSlotsFromList({json.dumps(accolades_list)})));
""")
        assert len(out) == 1
        slot = out[0]
        assert slot["key"] == "div1"
        assert slot["count"] == 2
        assert "Div 1 Champion" in slot["tip"]
        assert "S15" in slot["tip"] and "S12" in slot["tip"]
        assert "2 times" in slot["aria"]

    def test_accolade_tooltip_order_matches_backend_selection_priority(self):
        """AC: the tooltip's accolade order and count match exactly what's
        painted on the card face — same selection, priority and dedup rule as
        `image.py` (parity test between the frontend's accolade-slot helper
        and `image._ACCOLADE_PRIORITY`/`_select_accolade_keys`, matching the
        `test_issue_230` ACCOLADE_KINDS parity pattern)."""
        image = _image()
        js = _fe("app-globals.js")
        start = js.index("const _CARD_ACCOLADE_PRIORITY = {")
        block = js[start:js.index("};", start)]
        frontend = {m.group(1): int(m.group(2)) for m in re.finditer(r"(\w+):\s*(\d+)", block)}
        assert frontend == image._ACCOLADE_PRIORITY

        # Behavioural parity too: the same accolade list, deduped/ranked/capped the
        # same way on both sides.
        accolades_list = [
            _a("played", "Season 16"), _a("best_match", "Season 14"),
            _a("champion", "Season 15", "div2", "Blues"), _a("most_points", "Season 13"),
            _a("fantasy_winner", "Season 12"), _a("champion", "Season 16", "div1", "Reds"),
            _a("best_average", "Season 11"), _a("runner_up", "Season 10", "div1", "Olds"),
        ]
        from accolades import kind_key
        backend_keys = image._select_accolade_keys([kind_key(a) for a in accolades_list])
        out = _run_node(_hotspot_js() + f"""
console.log(JSON.stringify(cardAccoladeSlotsFromList({json.dumps(accolades_list)}).map(s => s.key)));
""")
        assert out == backend_keys

    def test_accolade_tooltip_present_on_roster_bench_viewer_and_reveal(self):
        """AC: the accolade tooltip hotspots work on every place a card image
        is shown (My Team roster/bench, the card viewer, the draw reveal) —
        not just one view."""
        roster = _fe("app-roster.js")
        slot_fn = _fn_source(roster, "_cardSlotHTML")
        assert "cardHotspotOverlayHtml(c)" in slot_fn  # My Team roster and bench

        cards = _fe("app-cards.js")
        assert 'getElementById("revealCardHotspots")' in cards
        assert "cardHotspotOverlayHtml(card)" in cards  # showCard: the card viewer and the draw reveal

        html = _fe("index.html")
        assert 'id="revealCardHotspots"' in html

    def test_accolade_badge_and_tooltip_absent_when_player_has_no_accolades(self):
        """Failure path: a player with no accolades renders an empty accolade
        grid and no tooltip hotspots anywhere on the card, as today."""
        out = _run_node(_hotspot_js() + """
console.log(JSON.stringify(cardAccoladeSlotsFromList([])));
""")
        assert out == []
        html = _node_overlay('{"player_id": 7, "player_name": "Ab", "team_id": null}')
        assert "card-hotspot--accolade" not in html
        assert "data-tip" not in html


# ---------------------------------------------------------------------------
# Story 2: Jump to a Player or Team From Their Card
# ---------------------------------------------------------------------------

class TestJumpToPlayerOrTeamFromTheirCard:

    def test_card_name_region_click_opens_player_profile_popup(self):
        """AC: clicking or activating the player name area of a rendered card
        opens that player's profile popup (`openPlayerModal`)."""
        html = _node_overlay('{"player_id": 42, "player_name": "Ab", "team_id": null}')
        assert "card-hotspot--name" in html
        assert "openPlayerModal(42)" in html
        assert "event.stopPropagation()" in html

    def test_card_team_region_click_opens_team_profile_popup(self):
        """AC: clicking or activating the team name or team logo area opens
        that team's profile popup (`openTeamModal`)."""
        html = _node_overlay('{"player_id": null, "team_id": 9, "team_name": "Reds"}')
        assert html.count("card-hotspot--team") == 2  # team-name-bar + logo-box
        assert html.count("openTeamModal(9)") == 2
        assert "event.stopPropagation()" in html

    def test_card_hotspots_are_keyboard_reachable_and_labeled(self):
        """AC: the name and team hotspot regions are reachable by keyboard
        (Tab, then Enter or Space) and are announced to screen readers with a
        descriptive `aria-label`."""
        html = _node_overlay('{"player_id": 1, "player_name": "Ab", "team_id": 2, "team_name": "T1"}')
        # Native <button> elements: focusable and Enter/Space-activating by default.
        assert html.count("<button type=\"button\"") == 3  # name + 2 team regions
        assert 'aria-label="View Ab' in html
        assert 'aria-label="View T1' in html

    def test_card_click_outside_hotspots_still_opens_card_viewer(self):
        """AC: clicking anywhere else on the card (photo, stats box, accolade
        grid, empty margin) still opens the card viewer, exactly as today —
        the hotspot overlay must not swallow those clicks."""
        image = _image()
        # The name/team/logo hotspots never cover the photo or stats box.
        hotspot_rects = [image._NAME_BAR, image._TEAM_NAME_BAR, image._LOGO_BOX]
        other_rects = [image._PHOTO_SLOT, image._STATS_BOX]
        for h in hotspot_rects:
            for o in other_rects:
                assert not _rects_overlap(h, o), (h, o)
        # The frontend's hotspot geometry stays in lock-step with image.py's rects.
        js = _fe("app-globals.js")

        def _arr(name):
            m = re.search(rf"const {name} = \[([^\]]+)\]", js)
            return tuple(int(x) for x in m.group(1).split(","))

        assert _arr("_CARD_NAME_BAR") == image._NAME_BAR
        assert _arr("_CARD_TEAM_NAME_BAR") == image._TEAM_NAME_BAR
        assert _arr("_CARD_LOGO_BOX") == image._LOGO_BOX
        # The accolade hotspots (over the accolade grid) only add a tooltip: no
        # click handler, so a tap there still bubbles to the card's own "open card
        # viewer" handler, same as a click on the photo/stats/margin.
        html = _node_overlay('{"player_id": 7, "player_name": "Ab"}',
                             extra='_accoladesByPlayer["7"] = ' + json.dumps([_a("played", "Season 14")]) + ";")
        m = re.search(r'<span class="card-hotspot card-hotspot--accolade"[^>]*>', html)
        assert m, html
        assert "onclick" not in m.group(0)

    def test_draw_and_get_card_responses_include_team_id_for_reveal_hotspot(self, db):
        """AC: the click-to-profile hotspots work both on the small
        roster/bench grid cards and on the large card-viewer/draw-reveal
        image; the draw reveal needs `team_id` in the payload to target
        `openTeamModal`, so `draw_card`, `draw_booster` and `get_card` in
        `backend/routers/cards.py` must include `team_id` alongside
        `team_name`/`team_logo_url`."""
        from routers.cards import draw_booster, draw_card, get_card

        user = _make_user(db)
        player = _make_player(db, 501, "Ab")
        _seed_team_player(db, 9, player.id, "Reds")
        db.commit()

        drawn = draw_card(db, {"user_id": user.id})
        assert drawn["team_id"] == 9

        fetched = get_card(drawn["id"], db, {"user_id": user.id})
        assert fetched["team_id"] == 9

        player2 = _make_player(db, 502, "Cd")
        _seed_team_player(db, 9, player2.id, "Reds")
        db.commit()
        boosted = draw_booster(9, db, {"user_id": user.id})
        assert boosted["player_id"] == player2.id
        assert boosted["team_id"] == 9

    def test_card_hotspots_absent_when_card_has_no_player_or_team_id(self):
        """Failure path: a card slot with no `player_id`/`team_id` (e.g. no
        team on record) renders without the corresponding hotspot button and
        without a handler that would call `openPlayerModal`/`openTeamModal`."""
        html = _node_overlay('{"player_id": null, "team_id": null}')
        assert html == ""
        assert "openPlayerModal" not in html
        assert "openTeamModal" not in html
        out_null = _run_node(_hotspot_js() + """
console.log(JSON.stringify(cardHotspotOverlayHtml(null)));
""")
        assert out_null == ""


# ---------------------------------------------------------------------------
# Story 3: Consistent Team Logo Fill
# ---------------------------------------------------------------------------

class TestConsistentTeamLogoFill:

    def test_team_logo_cover_fit_fills_logo_box_with_no_margin(self, tmp_path, monkeypatch):
        """AC: every team logo fully fills the card's logo box with no
        visible empty margin on any side, regardless of the source logo's own
        aspect ratio (new `image._cover_fit` used in the team-logo path)."""
        image = _image()
        from PIL import Image
        src = Image.new("RGBA", (50, 400), (255, 0, 0, 255))  # tall, narrow logo
        logo_path = tmp_path / "logo.png"
        src.save(logo_path)
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda d, name: str(logo_path))
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        lw, lh = lx1 - lx0, ly1 - ly0
        out = image._load_team_logo_for_card("AnyTeam", None, (lw, lh))
        assert out.size == (lw, lh)
        for x, y in [(0, 0), (lw - 1, 0), (0, lh - 1), (lw - 1, lh - 1), (lw // 2, lh // 2)]:
            assert out.getpixel((x, y))[:3] == (255, 0, 0), (x, y, out.getpixel((x, y)))

    def test_team_logo_mismatched_aspect_ratio_is_center_cropped_not_letterboxed(self):
        """AC: a logo whose aspect ratio doesn't match the box is
        centre-cropped rather than letterboxed, trading a small edge crop for
        a consistent fill."""
        image = _image()
        from PIL import Image
        src = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
        blue = Image.new("RGBA", (100, 100), (0, 0, 255, 255))
        src.paste(blue, (100, 0))
        w, h = 120, 120  # a square box: the 2:1 source must be cropped, not padded
        out = image._cover_fit(src, w, h)
        assert out.size == (w, h)
        assert out.getpixel((5, h // 2))[:3] == (255, 0, 0)        # left: still red
        assert out.getpixel((w - 5, h // 2))[:3] == (0, 0, 255)    # right: still blue
        assert out.getpixel((0, 0))[3] == 255                      # no transparent margin
        assert out.getpixel((w - 1, h - 1))[3] == 255

    def test_team_logo_http_fallback_path_uses_same_cover_fit_as_local_path(self, monkeypatch):
        """AC: both the locally cached Dotabuff logo path
        (`_load_team_logo_for_card`) and the HTTP `team_logo_url` fallback
        path (`_fetch_team_logo_image`/`_fetch_pil_image`) get the same
        consistent cover-fit fill."""
        image = _image()
        from PIL import Image
        src = Image.new("RGBA", (300, 90), (10, 20, 230, 255))
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda d, name: None)
        monkeypatch.setattr(image, "safe_logo_url", lambda u: u)

        def _fake_get(url, timeout=10, headers=None):
            buf = io.BytesIO()
            src.save(buf, format="PNG")
            return type("Resp", (), {"status_code": 200, "content": buf.getvalue()})()

        monkeypatch.setattr("requests.get", _fake_get)
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        lw, lh = lx1 - lx0, ly1 - ly0
        out = image._load_team_logo_for_card("AnyTeam", "https://example.com/logo.png", (lw, lh))
        assert out.size == (lw, lh)
        expected = image._cover_fit(src.convert("RGBA"), lw, lh)
        assert out.tobytes() == expected.tobytes()

    def test_team_logo_cover_fit_change_does_not_break_missing_logo_placeholder(self, monkeypatch):
        """Failure path: with no local logo file and no `team_logo_url`, the
        logo box still renders the existing blank placeholder rather than
        raising or leaving a corrupted slot — the fit-mode change must not
        regress the missing-logo path."""
        image = _image()
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda d, name: None)
        # The real function (not bypassed): no local file and no team_logo_url (_render
        # always passes None) means no HTTP fetch is attempted either.
        assert image._load_team_logo_for_card("NoLogoTeam", None, (10, 10)) is None
        img = _render(image, team="NoLogoTeam")
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        cx, cy = (lx0 + lx1) // 2, (ly0 + ly1) // 2
        assert img.getpixel((cx, cy)) == (0, 0, 0, 255)  # _blank_logo_placeholder


# ---------------------------------------------------------------------------
# Story 4: Bigger Cards, Five to a Row
# ---------------------------------------------------------------------------

class TestBiggerCardsFiveToARow:

    def test_card_grid_css_shows_five_columns_with_no_horizontal_scroll(self):
        """AC: the active roster grid shows all 5 roster slots in a single
        row filling the My Team panel's available width, with no horizontal
        scrollbar (`.card-grid` becomes a 5-column CSS grid, dropping
        `overflow-x: auto`)."""
        base_css = _base_css()
        bodies = _rule(base_css, ".card-grid")
        assert len(bodies) == 1
        body = bodies[0]
        assert "display: grid" in body
        assert "grid-template-columns: repeat(5, 1fr)" in body
        assert "overflow-x" not in body

    def test_bench_grid_css_uses_five_column_layout_and_wraps(self):
        """AC: the bench grid uses the same 5-column layout, wrapping into
        further rows as it grows past 5 cards."""
        html = _fe("index.html")
        assert re.search(r'id="rosterActiveGrid"\s+class="[^"]*\bcard-grid\b', html)
        assert re.search(r'id="benchGrid"\s+class="[^"]*\bcard-grid\b', html)
        base_css = _base_css()
        body = _rule(base_css, ".card-grid")[0]
        assert "grid-template-columns: repeat(5, 1fr)" in body
        # No fixed row count/height that would stop extra bench cards from wrapping.
        assert "grid-template-rows" not in body
        assert "height" not in body

    def test_card_img_css_is_responsive_width_not_fixed_180px(self):
        """AC: cards are visibly larger than the previous fixed 180px width on
        typical desktop widths (`.card-img` drops the fixed `180px` for
        `width: 100%`)."""
        base_css = _base_css()
        body = _rule(base_css, ".card-img")[0]
        assert "width: 100%" in body
        assert "180px" not in body

    def test_card_grid_css_drops_columns_at_phone_width_breakpoint(self):
        """AC: on narrow/phone-width screens the grid drops to fewer columns
        so cards stay readable instead of shrinking indefinitely (new
        `@media (max-width: 768px)` rule on `.card-grid`)."""
        css = _fe("style.css")
        media_start = css.index("@media (max-width: 768px)")
        media_block = css[media_start:]
        assert ".card-grid" in media_block
        phone_body = _rule(media_block, ".card-grid")[0]
        assert re.search(r"grid-template-columns:\s*repeat\((\d+),\s*1fr\)", phone_body)
        phone_cols = int(re.search(r"repeat\((\d+),\s*1fr\)", phone_body).group(1))
        assert phone_cols < 5

    def test_card_placeholder_css_matches_responsive_card_image_sizing(self):
        """AC: the empty-roster-slot and loading placeholders
        (`.card-slot-empty`, `.card-img-loading`) resize the same way as the
        real card images, so the grid never looks mismatched mid-load."""
        base_css = _base_css()
        loading_body = _rule(base_css, ".card-img-loading")[0]
        empty_body = _rule(base_css, ".card-slot-empty")[0]
        for body in (loading_body, empty_body):
            assert "aspect-ratio: 687 / 1024" in body
            assert "width: 100%" in body
            assert "180px" not in body and "268px" not in body

    def test_card_grid_css_no_longer_has_fixed_width_or_overflow_scroll(self):
        """Failure path / regression guard: `.card-grid` no longer carries the
        old horizontally-scrolling flex-row styling (`overflow-x: auto`) and
        `.card-img` no longer carries the old fixed `180px` width."""
        base_css = _base_css()
        grid_body = _rule(base_css, ".card-grid")[0]
        assert "overflow-x: auto" not in grid_body
        img_body = _rule(base_css, ".card-img")[0]
        assert "180px" not in img_body
