"""Tests for plan-card-art-accolade-redesign.md.

New illustrated card templates (Common->Grey, Rare->Blue, Epic->Purple,
Legendary->Gold, plus a dedicated Holo template) replace the #228 originals.
`backend/image.py` is rewritten: card size becomes 687x1024, the player photo
becomes a square-crop portrait, the team logo becomes an aspect-fit box (no
circles), player/team name and stats move into template bars/boxes, and up to
6 accolade badge icons are composited into a 3x2 grid, selected and capped by
priority (champion > runner-up > third place > fantasy winner > performance
awards > seasons played, newest first within a tier). The procedurally
generated Holo sheen (`_holo_sheen`, `warn_if_holo_template_missing`) is
removed; a real Holo template file always ships.

  Story 1: New Card Template With Accolade Slots
  Story 2: Accolades Printed on the Card Face
  Story 3: Dedicated Holo Template Art
"""

import io
import os
import shutil
import time

import pytest

import models  # noqa: F401  (register tables for the db fixture)
from models import Card, Player, SeasonAccolade, User
from tests.test_issue_50_season_winners_and_holo_cards import _client, _fe, _read, _rule, _user, db  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _image():
    image = pytest.importorskip("image")
    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    return image


def _no_fetch(image, monkeypatch, avatar=None, logo=None):
    """No network: the avatar and the team logo come from the given images (or none).
    `avatar`/`logo` may be a PIL Image or a callable taking the fetch `size`."""
    monkeypatch.setattr(image, "_fetch_pil_image",
                        lambda url, size: avatar(size) if callable(avatar) else avatar)
    monkeypatch.setattr(image, "_load_team_logo_for_card",
                        lambda name, url, size: logo(size) if callable(logo) else logo)


def _seed_card(db, card_type="common", is_holo=False, player_id=4300):
    player = db.get(Player, player_id)
    if player is None:
        player = Player(id=player_id, name="Redesigned", is_active=True)
        db.add(player)
    owner = db.query(User).filter_by(username="redesignowner").first() or _user(db, "redesignowner")
    card = Card(owner_id=owner.id, player_id=player_id, card_type=card_type,
                is_active=False, generation=1, is_holo=is_holo)
    db.add(card)
    db.commit()
    return card


def _image_client(db, monkeypatch):
    from routers import cards as cards_router
    monkeypatch.setattr(cards_router.limiter, "enabled", False)
    return _client(db)


def _cell_has_icon(image, img, index):
    """True if the accolade cell at `index` carries a badge icon rather than the
    template's own (near-uniform, textured) empty fill."""
    box = image._accolade_cell_rect(index)
    colors = img.crop(box).convert("RGB").getcolors(maxcolors=100000)
    return bool(colors) and len(colors) > 500


# ---------------------------------------------------------------------------
# Story 1: New Card Template With Accolade Slots
# ---------------------------------------------------------------------------

class TestNewCardTemplateWithAccoladeSlots:

    def test_get_card_image_renders_on_new_rarity_templates(self, db, monkeypatch):
        """AC: GET /cards/{id}/image renders on the new rarity templates (Common ->
        Grey, Rare -> Blue, Epic -> Purple, Legendary -> Gold) instead of the
        pre-redesign Card_Template_* originals."""
        image = _image()
        from PIL import Image
        _no_fetch(image, monkeypatch)
        client = _image_client(db, monkeypatch)
        assert sorted(os.path.basename(v) for v in image._CARD_TEMPLATES.values()) == \
            ["Card_Blue.png", "Card_Gold.png", "Card_Grey.png", "Card_Purple.png"]
        for i, ct in enumerate(("common", "rare", "epic", "legendary")):
            card = _seed_card(db, card_type=ct, player_id=4300 + i)
            res = client.get(f"/cards/{card.id}/image")
            assert res.status_code == 200
            got = Image.open(io.BytesIO(res.content)).convert("RGBA")
            assert got.size == image._CARD_SIZE
            expected = image._load_template(ct, False)
            # A frame-only corner, untouched by any slot: it matches the new
            # rarity template directly, proving that template is the base.
            assert got.getpixel((10, 10)) == expected.getpixel((10, 10)), ct

    def test_generate_card_image_square_crops_player_photo(self, monkeypatch):
        """AC: the player photo is composited as a square portrait filling the
        template's photo slot, with no circular crop applied."""
        image = _image()
        from PIL import Image
        quad = Image.new("RGBA", (300, 300), (200, 0, 0, 255))
        half = 150
        quad.paste((0, 200, 0, 255), (half, 0, 300, half))
        quad.paste((0, 0, 200, 255), (0, half, half, 300))
        quad.paste((200, 200, 0, 255), (half, half, 300, 300))
        _no_fetch(image, monkeypatch, avatar=lambda size: quad)
        img = image.generate_card_image("common", "Ab", "https://a.example/a.png", None, None)
        x0, y0, x1, y1 = image._PHOTO_SLOT
        inset = 6
        # A circular mask would cut these corners to the dark base/template; a plain
        # square crop shows the avatar's own corner colour right up to the slot edge.
        assert img.getpixel((x0 + inset, y0 + inset)) == (200, 0, 0, 255)
        assert img.getpixel((x1 - inset, y0 + inset)) == (0, 200, 0, 255)
        assert img.getpixel((x0 + inset, y1 - inset)) == (0, 0, 200, 255)
        assert img.getpixel((x1 - inset, y1 - inset)) == (200, 200, 0, 255)

    def test_generate_card_image_aspect_fits_team_logo_no_circle_crop(self, monkeypatch):
        """AC: the team logo is composited inside the template's dedicated logo box,
        scaled to fit without distortion, with no circular crop applied."""
        image = _image()
        from PIL import Image
        src = Image.new("RGBA", (400, 100), (10, 20, 230, 255))  # 4:1, not the box's own ratio
        monkeypatch.setattr(image, "_load_team_logo_for_card",
                            lambda name, url, size: image._aspect_fit(src, *size))
        img = image.generate_card_image("common", "Ab", None, "Team", "https://logo.example/x.png")
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        lw, lh = lx1 - lx0, ly1 - ly0
        fitted = image._aspect_fit(src, lw, lh)
        # Aspect preserved (not stretched to the box's own, different, ratio).
        assert abs((fitted.width / fitted.height) - (400 / 100)) < 0.1
        assert fitted.width == lw or fitted.height == lh  # fits snugly on one axis
        cx, cy = (lx0 + lx1) // 2, (ly0 + ly1) // 2
        assert img.getpixel((cx, cy)) == (10, 20, 230, 255)
        if fitted.height < lh:  # letterboxed top/bottom: no logo colour in the margin
            margin_y = ly0 + (lh - fitted.height) // 4
            assert img.getpixel((cx, margin_y)) != (10, 20, 230, 255)

    def test_generate_card_image_draws_name_and_team_in_their_own_bars(self, monkeypatch):
        """AC: the player name and team name are drawn in their own template bars,
        each sized and positioned for that bar (not the old shared centred rows)."""
        image = _image()
        _no_fetch(image, monkeypatch)
        calls = []
        real = image._draw_text_in_box

        def spy(draw, text, box, font, fill, shadow, pad=16):
            calls.append((text, box))
            return real(draw, text, box, font, fill, shadow, pad=pad)

        monkeypatch.setattr(image, "_draw_text_in_box", spy)
        image.generate_card_image("common", "Ab", None, "Reds", None)
        assert calls[0] == ("AB", image._NAME_BAR)
        assert calls[1] == ("REDS", image._TEAM_NAME_BAR)
        team_cx = (image._TEAM_NAME_BAR[0] + image._TEAM_NAME_BAR[2]) // 2
        card_cx = image._CARD_SIZE[0] // 2
        # Centred within its own bar's text area, not the full card width.
        assert team_cx != card_cx

    def test_name_and_team_text_is_light_on_the_dark_bars(self, monkeypatch):
        """The new templates' name/team bars are near-black fills (unlike the old
        templates' light plates), so the text must be light with a dark shadow for
        contrast — not the old dark-on-light combination, which renders unreadable
        on the new bars."""
        image = _image()
        _no_fetch(image, monkeypatch)
        calls = []
        real = image._draw_text_in_box

        def spy(draw, text, box, font, fill, shadow, pad=16):
            calls.append((text, fill, shadow))
            return real(draw, text, box, font, fill, shadow, pad=pad)

        monkeypatch.setattr(image, "_draw_text_in_box", spy)
        image.generate_card_image("common", "Ab", None, "Reds", None)
        assert len(calls) == 2
        for _, fill, shadow in calls:
            assert fill == image._NAME_TEAM_FILL
            assert shadow == image._NAME_TEAM_SHADOW
            # Light fill (readable on a near-black bar), dark shadow for edge contrast.
            assert sum(fill[:3]) > 600
            assert sum(shadow[:3]) < 150

    def test_generate_card_image_draws_stat_modifiers_inside_stats_box(self, monkeypatch):
        """AC: stat modifier lines are drawn inside the template's stats box."""
        image = _image()
        _no_fetch(image, monkeypatch)
        calls = []
        real = image._draw_centered_text

        def spy(draw, text, cx, cy, font, fill, shadow=(0, 0, 0, 160)):
            calls.append((text, cx, cy))
            return real(draw, text, cx, cy, font, fill, shadow=shadow)

        monkeypatch.setattr(image, "_draw_centered_text", spy)
        mods = {"kills": 5, "assists": 10, "gpm": 15}
        image.generate_card_image("common", "Ab", None, "Reds", None, card_modifiers=mods)
        x0, y0, x1, y1 = image._STATS_BOX
        in_box = [(t, cx, cy) for t, cx, cy in calls if y0 <= cy <= y1]
        assert len(in_box) == 3
        for _, cx, cy in in_box:
            assert x0 <= cx <= x1
        # The name/team bars sit outside the stats box.
        assert {t for t, cx, cy in calls if not (y0 <= cy <= y1)} == {"AB", "REDS"}

    def test_card_size_is_687x1024_everywhere_a_card_image_is_shown(self, monkeypatch):
        """AC: card size changes to 687 x 1024 (image._CARD_SIZE), and every view
        that shows a card image (My Team, collection, draw reveal, card viewer,
        Weekly Report) displays correctly at the new size (no hardcoded 597/845
        sizing or aspect-ratio assumptions left in frontend/app-cards.js or
        frontend/style.css)."""
        image = _image()
        assert image._CARD_SIZE == (687, 1024)
        _no_fetch(image, monkeypatch)
        for ct in ("common", "rare", "epic", "legendary"):
            assert image.generate_card_image(ct, "Ab", None, "T", None).size == (687, 1024)
        assert image.generate_card_image("legendary", "Ab", None, "T", None,
                                         is_holo=True).size == (687, 1024)

        css = _fe("style.css")
        cards_js = _fe("app-cards.js")
        assert "597" not in css and "845" not in css
        assert "597" not in cards_js and "845" not in cards_js
        # The loading/placeholder boxes that stand in before the real <img> loads were
        # sized to the old 597x845 ratio; they must follow the new one instead.
        for sel in (".card-img-loading", ".card-slot-empty"):
            body = _rule(css, sel)[0]
            assert "width: 180px" in body and "height: 268px" in body, sel
        for sel in (".reveal-img-wrap", ".reveal-img-wrap .reveal-img-placeholder",
                    ".reveal-img-wrap .reveal-card-img"):
            body = _rule(css, sel)[0]
            assert "width: 200px" in body and "height: 298px" in body, sel

    def test_generate_card_image_missing_photo_or_logo_leaves_slot_blank(self, monkeypatch):
        """AC: a missing player photo or team logo leaves that slot visibly blank
        (same placeholder intent as today, resized to the new slot shape) rather
        than broken."""
        image = _image()
        _no_fetch(image, monkeypatch)  # no avatar, no logo
        img = image.generate_card_image("common", "Ab", None, None, None)
        template = image._load_template("common", False)
        px0, py0, _, _ = image._PHOTO_SLOT
        # No photo: the slot shows the bare template (no avatar placeholder today).
        assert img.getpixel((px0 + 10, py0 + 10)) == template.getpixel((px0 + 10, py0 + 10))
        # No logo: the blank placeholder fills the box solid black.
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        assert img.getpixel(((lx0 + lx1) // 2, (ly0 + ly1) // 2)) == (0, 0, 0, 255)

    def test_get_card_image_missing_card_returns_404(self, db, monkeypatch):
        """Failure path: GET /cards/{id}/image for an id with no Card row still
        answers 404 (the redesign must not change the route's error handling)."""
        _image()
        res = _image_client(db, monkeypatch).get("/cards/987654/image")
        assert res.status_code == 404
        assert res.json()["detail"] == "Card not found"


# ---------------------------------------------------------------------------
# Story 2: Accolades Printed on the Card Face
# ---------------------------------------------------------------------------

class TestAccoladesPrintedOnCardFace:

    def test_get_card_image_composites_up_to_six_accolade_icons_into_grid(self, db, monkeypatch):
        """AC: GET /cards/{id}/image composites up to 6 accolade icons into the
        template's accolade grid, one icon per accolade the player holds."""
        image = _image()
        from PIL import Image
        _no_fetch(image, monkeypatch)
        from routers import cards as cards_router
        card = _seed_card(db, player_id=4310)
        fixed = [{"kind": "champion", "division": "div1", "season": "Season 15"},
                 {"kind": "most_points", "division": None, "season": "Season 15"},
                 {"kind": "played", "division": None, "season": "Season 15"}]
        monkeypatch.setattr(cards_router.accolades, "accolades_for",
                            lambda db, ids, **kw: {card.player_id: fixed})
        client = _image_client(db, monkeypatch)
        res = client.get(f"/cards/{card.id}/image")
        assert res.status_code == 200
        got = Image.open(io.BytesIO(res.content)).convert("RGBA")
        filled = [i for i in range(6) if _cell_has_icon(image, got, i)]
        assert filled == [0, 1, 2]

    def test_each_accolade_kind_uses_its_matching_badge_icon_not_lucide(self):
        """AC: each accolade kind (ACCOLADE_KINDS key) uses its matching badge icon
        asset (e.g. Division 1 Champion -> crown badge) via image._ACCOLADE_ICON_FILES,
        not the Lucide icon used elsewhere on the site."""
        image = _image()
        import accolades
        kind_keys = {k["key"] for k in accolades.ACCOLADE_KINDS}
        assert set(image._ACCOLADE_ICON_FILES) == kind_keys
        for key, filename in image._ACCOLADE_ICON_FILES.items():
            assert filename.startswith("Accolade_") and filename.endswith(".png"), key
            path = os.path.join(image._ASSETS_DIR, "accolades", filename)
            assert os.path.isfile(path), key
        assert image._ACCOLADE_ICON_FILES["div1"] == "Accolade_Div1_Champion.png"
        lucide_icons = {k["icon"] for k in accolades.ACCOLADE_KINDS}
        assert not (set(image._ACCOLADE_ICON_FILES.values()) & lucide_icons)

    def test_generate_card_image_no_accolades_shows_empty_grid(self, monkeypatch):
        """AC: a player with no accolades (empty accolade_keys) shows an empty grid
        with no placeholder icons."""
        image = _image()
        _no_fetch(image, monkeypatch)
        img = image.generate_card_image("common", "Ab", None, "T", None, accolade_keys=[])
        assert not any(_cell_has_icon(image, img, i) for i in range(6))
        img_none = image.generate_card_image("common", "Ab", None, "T", None, accolade_keys=None)
        assert not any(_cell_has_icon(image, img_none, i) for i in range(6))

    def test_generate_card_image_more_than_six_accolades_keeps_top_six_by_priority(self):
        """AC: a player with more than 6 accolades shows the 6 highest-priority ones:
        champion > runner-up > third place > fantasy winner > performance awards
        (Most Points, Best Average, Best Single Match) > seasons played, newest
        season first within a tier."""
        image = _image()
        keys = [
            "div1", "div2",                   # champion, two seasons (newest first)
            "div1_runner_up",                 # runner-up
            "div1_third",                     # third place
            "fantasy_winner",
            "most_points", "best_average", "best_match",   # performance awards
            "played", "played", "played",     # three seasons played
        ]
        selected = image._select_accolade_keys(keys)
        assert selected == ["div1", "div2", "div1_runner_up", "div1_third",
                            "fantasy_winner", "most_points"]
        assert len(selected) == 6
        assert "played" not in selected
        assert "best_average" not in selected and "best_match" not in selected
        # A stable sort preserves "newest season first" within a tier: the caller
        # (accolades.accolades_for) already lists newest season first.
        assert image._select_accolade_keys(["div2", "div1", "played"])[:2] == ["div2", "div1"]

    def test_generate_card_image_accolade_count_badge_for_repeated_kind(self, monkeypatch):
        """AC: an accolade kind held 2+ times (e.g. division champion across multiple
        seasons) shows a small count badge in the icon's corner; a kind held once
        shows none, and a kind held 9+ times shows "9+" rather than overflowing."""
        image = _image()
        _no_fetch(image, monkeypatch)
        keys = ["div1", "div1", "div1", "most_points"]  # 3x champion, 1x most points
        counts = image._accolade_counts(keys)
        assert counts == {"div1": 3, "most_points": 1}
        assert image._select_accolade_keys(keys) == ["div1", "most_points"]

        img = image.generate_card_image("legendary", "Ab", None, "T", None, accolade_keys=keys)
        r = image._ACCOLADE_COUNT_BADGE_RADIUS
        box_champion = image._accolade_cell_rect(0)   # div1, count 3 -> badge
        box_single = image._accolade_cell_rect(1)      # most_points, count 1 -> no badge
        badge_fill = (20, 18, 14)
        # Sample near the bottom of the badge circle, clear of the count digit's own
        # ink (which sits centred in the circle, not at its bottom edge).
        cx0, cy0 = box_champion[2] - r - 1, box_champion[3] - r - 1
        assert img.getpixel((cx0, cy0 + r - 2))[:3] == badge_fill
        cx1, cy1 = box_single[2] - r - 1, box_single[3] - r - 1
        assert img.getpixel((cx1, cy1 + r - 2))[:3] != badge_fill

        img_overflow = image.generate_card_image("legendary", "Ab", None, "T", None,
                                                  accolade_keys=["played"] * 11)
        assert img_overflow.getpixel((cx0, cy0 + r - 2))[:3] == badge_fill  # "played" lands in cell 0 alone

    def test_accolades_still_shown_as_html_pips_and_timeline_elsewhere(self):
        """AC: accolades still show as detailed HTML pips/timeline elsewhere (Players
        list, Teams tab, team popup, Hall of Fame, player popup) — the card face icons
        are additive, not a replacement for accolades.accolades_for or the pip
        renderers."""
        _image()
        g = _fe("app-globals.js")
        assert "function accoladePipsHtml(" in g
        players = _fe("app-players.js")
        assert '<td class="players-titles">${accoladePipsHtml(' in players
        teams_cell = players[players.index('class="teams-titles"'):]
        assert "accoladePipsHtml(" in teams_cell[:teams_cell.index("</td>")]
        assert "accoladePipsHtml(" in _fe("app-team-popup.js")
        assert "accoladePipsHtml(f.accolades" in _fe("app-history.js")
        assert "accoladeDetailLine" in _fe("app-player-popup.js")

    def test_card_image_accolade_icons_update_on_next_request_no_cache(self, db, monkeypatch):
        """AC: accolade icons update on the very next GET /cards/{id}/image request
        after an accolade is granted or changed, since the image has no server-side
        cache (same as the rest of the card)."""
        image = _image()
        from PIL import Image
        _no_fetch(image, monkeypatch)
        from routers import cards as cards_router
        card = _seed_card(db, player_id=4320)
        state = {"list": []}
        monkeypatch.setattr(cards_router.accolades, "accolades_for",
                            lambda db, ids, **kw: {card.player_id: state["list"]})
        client = _image_client(db, monkeypatch)

        before = Image.open(io.BytesIO(client.get(f"/cards/{card.id}/image").content)).convert("RGBA")
        assert not any(_cell_has_icon(image, before, i) for i in range(6))

        state["list"] = [{"kind": "champion", "division": "div1", "season": "Season 15"}]
        after = Image.open(io.BytesIO(client.get(f"/cards/{card.id}/image").content)).convert("RGBA")
        assert _cell_has_icon(image, after, 0)

    def test_generate_card_image_unknown_accolade_key_does_not_break_render(self, monkeypatch):
        """Failure path: an accolade key with no entry in
        image._ACCOLADE_ICON_FILES (e.g. a stale or unmapped key) does not raise and
        does not break the rest of the card render; the card still renders at the
        new size with its other slots filled."""
        image = _image()
        _no_fetch(image, monkeypatch)
        img = image.generate_card_image("common", "Ab", None, "Reds", None,
                                        accolade_keys=["not_a_real_key", "div1"])
        assert img.size == image._CARD_SIZE
        # The valid key still sorts first (priority 0 vs the unknown key's fallback
        # priority 99) and renders; the unknown key's cell is simply left blank.
        assert _cell_has_icon(image, img, 0)
        assert not _cell_has_icon(image, img, 1)


# ---------------------------------------------------------------------------
# Story 3: Dedicated Holo Template Art
# ---------------------------------------------------------------------------

class TestDedicatedHoloTemplateArt:

    def test_holo_legendary_uses_dedicated_holo_template_file(self):
        """AC: a Holo Legendary (cards.is_holo) uses the dedicated Holo template file
        for its base art (image._HOLO_TEMPLATE / _load_template('legendary', True))."""
        image = _image()
        from PIL import Image
        holo = image._load_template("legendary", True)
        expected = Image.open(os.path.join(image._ASSETS_DIR, image._HOLO_TEMPLATE)).convert("RGBA")
        assert holo.size == expected.size == image._CARD_SIZE
        assert holo.tobytes() == expected.tobytes()
        legendary_plain = image._load_template("legendary", False)
        assert legendary_plain.tobytes() != holo.tobytes()
        assert os.path.basename(image._HOLO_TEMPLATE) == "Card_Holo.png"

    def test_procedural_holo_sheen_is_removed_entirely(self):
        """AC: the procedurally generated rainbow sheen effect is removed; no code
        path falls back to a generated shine (image._holo_sheen and
        warn_if_holo_template_missing no longer exist)."""
        image = _image()
        for name in ("_holo_sheen", "warn_if_holo_template_missing", "_holo_warned",
                     "_HOLO_SHEEN_ALPHA", "_holo_template_path"):
            assert not hasattr(image, name), name
        src = _read("backend", "image.py")
        assert "_holo_sheen" not in src and "colorsys" not in src
        assert "warn_if_holo_template_missing" not in src

    def test_holo_template_composites_all_dynamic_content_same_way(self, monkeypatch):
        """AC: all dynamic content (photo, logo, name, team, stats, accolades)
        composites onto the Holo template the same way as the rarity templates
        (same slot rects, same compositing order)."""
        image = _image()
        from PIL import Image
        quad = Image.new("RGBA", (300, 300), (10, 20, 30, 255))
        _no_fetch(image, monkeypatch, avatar=lambda size: quad,
                 logo=lambda size: Image.new("RGBA", size, (40, 50, 60, 255)))
        mods = {"kills": 5}
        kwargs = dict(player_name="Champ", avatar_url="https://a.example/a.png", team_name="Team",
                     team_logo_url="https://logo.example/x.png", card_modifiers=mods,
                     accolade_keys=["div1"])
        holo = image.generate_card_image("legendary", is_holo=True, **kwargs)
        legendary = image.generate_card_image("legendary", is_holo=False, **kwargs)
        assert holo.size == legendary.size == image._CARD_SIZE
        px0, py0, _, _ = image._PHOTO_SLOT
        assert holo.getpixel((px0 + 10, py0 + 10)) == legendary.getpixel((px0 + 10, py0 + 10))
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        cxy = ((lx0 + lx1) // 2, (ly0 + ly1) // 2)
        assert holo.getpixel(cxy) == legendary.getpixel(cxy)
        assert _cell_has_icon(image, holo, 0) and _cell_has_icon(image, legendary, 0)
        # The frame art itself differs (Holo vs Gold template) even though every
        # dynamic slot composited the same way.
        assert holo.tobytes() != legendary.tobytes()

    def test_generate_card_image_holo_with_no_template_file_does_not_fall_back_to_sheen(self, tmp_path, monkeypatch):
        """Failure path: with no Holo template file present on disk, generating a
        Holo Legendary card does not silently fall back to a generated sheen (no
        _holo_sheen call exists to fall back to); the redesign assumes a real Holo
        template always ships, so a missing file must surface as a clear error, not
        a quietly wrong image."""
        image = _image()
        template_dir = tmp_path / "card_templates"
        template_dir.mkdir()
        for rarity_file in image._CARD_TEMPLATES.values():
            shutil.copy(os.path.join(image._ASSETS_DIR, rarity_file), tmp_path / rarity_file)
        monkeypatch.setattr(image, "_ASSETS_DIR", str(tmp_path))
        assert not os.path.exists(os.path.join(str(tmp_path), image._HOLO_TEMPLATE))
        with pytest.raises(FileNotFoundError):
            image._load_template("legendary", True)
        with pytest.raises(FileNotFoundError):
            image.generate_card_image("legendary", "Ab", None, "T", None, is_holo=True)
        assert not hasattr(image, "_holo_sheen")
