"""Tests for Card Formatting (plan-issue-218-card-formatting.md).

Layout A · Classic TCG on the 597 x 845 card: a rarity-coloured frame (the edge
colour is the rarity), a name bar with the player name only, a 368 x 368
portrait slot (the 184 px avatar at exactly 2x) between two plain pillars, a
type line with a 100 x 60 logo slot (the 250 x 150 cached logo at exactly 0.4x)
and the team name, and a cream rules box with up to 3 modifier lines. Ordinary
legendaries get a light shine; Holo legendaries a much stronger rainbow.
Tag pips (#217) and accolade pips (#50) are HTML overlays sized in container
units over the left and right pillars; the PNG draws no tags or accolades.

Covers the stories:
  - Card Frame With Exact Portrait and Logo Slots
  - Pips Sit in the Pillars

Not covered:
  - Choose a New Card Layout (design decision, already done)
  - Rank Medal on the Card (deferred; one stub asserts the PNG draws no medal)
  - Counted Accolades (not yet implemented)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib.util
import inspect
import re
import shutil
from html.parser import HTMLParser

import pytest

image = pytest.importorskip("image")
if not image.PIL_AVAILABLE:
    pytest.skip("Pillow not installed", allow_module_level=True)

from PIL import Image, ImageChops, ImageStat  # noqa: E402

from tests.test_issue_50_season_winners_and_holo_cards import (  # noqa: E402
    _a, _fe, _fn_body, _pips, _read, _rule,
)
from tests.test_issue_217_tag_symbols_on_cards import _tag_pips  # noqa: E402

_RARITIES = ("common", "rare", "epic", "legendary")
_MODS = [{}, {"kills": 5}, {"kills": 5, "assists": 10}, {"kills": 5, "assists": 10, "gpm": 15}]
_CARD_W = image._CARD_SIZE[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generator():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "make_card_templates.py")
    spec = importlib.util.spec_from_file_location("make_card_templates_218", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _quadrants(size=184):
    """A square avatar with four solid quadrants, so a crop or offset shows."""
    img = Image.new("RGBA", (size, size), (200, 0, 0, 255))
    h = size // 2
    img.paste((0, 200, 0, 255), (h, 0, size, h))
    img.paste((0, 0, 200, 255), (0, h, h, size))
    img.paste((200, 200, 0, 255), (h, h, size, size))
    return img


def _render(monkeypatch=None, ct="common", name="Ab", team="T1", mods=None, avatar=None,
            is_holo=False, foil=True):
    if monkeypatch is not None:
        monkeypatch.setattr(image, "_fetch_pil_image", lambda url, size=None: avatar)
        if not foil:
            monkeypatch.setattr(image, "_apply_foil_sheen", lambda img: img)
    return image.generate_card_image(ct, name, "https://avatars.example/a.png" if avatar else None,
                                     team, None, mods or {}, is_holo=is_holo)


def _template(ct):
    return Image.open(os.path.join(image._ASSETS_DIR, image._CARD_TEMPLATES[ct])).convert("RGBA")


def _same(a, b):
    """Pixel-identical, all channels (an RGBA difference's getbbox() checks alpha only)."""
    return a.size == b.size and a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()


def _mean_diff(a, b, box=None):
    if box:
        a, b = a.crop(box), b.crop(box)
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    return sum(ImageStat.Stat(diff).mean) / 3


# The frame and pillars, where the Holo shine is strong.
_SHINE_BOXES = (image._LEFT_PILLAR, image._RIGHT_PILLAR, (6, 6, 591, 22), (6, 826, 591, 839))


def _shine(img, baseline):
    return sum(_mean_diff(img, baseline, box) for box in _SHINE_BOXES) / len(_SHINE_BOXES)


def _nearest_rarity(rgb):
    return min(image._RARITY_COLORS, key=lambda r: sum((a - b) ** 2 for a, b in
                                                      zip(image._RARITY_COLORS[r], rgb[:3])))


def _drawn_texts(monkeypatch):
    texts = []
    real = image._draw_text

    def spy(draw, xy, text, font, fill, anchor="lm"):
        texts.append(text)
        return real(draw, xy, text, font, fill, anchor)

    monkeypatch.setattr(image, "_draw_text", spy)
    return texts


def _supports_block(css):
    m = re.search(r"@supports \(container-type: inline-size\)\s*\{(.*?)\n\}", css, re.S)
    assert m, "no @supports (container-type: inline-size) block"
    return m.group(1)


def _units(body, prop):
    """The --card-u multiplier of `prop` in a rule body, e.g. calc(var(--card-u) * 18.4)."""
    m = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*calc\(var\(--card-u\) \* ([\d.]+)\)", body)
    assert m, f"{prop} is not in --card-u units: {body}"
    return float(m.group(1))


def _px_to_u(px):
    return px * 100 / _CARD_W


class _Attrs(HTMLParser):
    def __init__(self, cls):
        super().__init__()
        self.cls, self.found = cls, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.cls in (a.get("class") or "").split():
            self.found.append(a)


def _pip_attrs(markup, cls):
    p = _Attrs(cls)
    p.feed(markup)
    return p.found




# ===========================================================================
# Story: Card Frame With Exact Portrait and Logo Slots
# ===========================================================================

def test_generate_card_image_every_rarity_and_modifier_count_renders_597x845():
    """AC: the card PNG is 597 x 845 and uses layout A for every rarity, with 0 to 3 modifiers."""
    for ct in _RARITIES:
        for mods in _MODS:
            img = image.generate_card_image(ct, "Player", None, "Team", None, mods)
            assert img.size == (597, 845) and img.mode == "RGBA", (ct, mods)
            # Layout A: the frame edge is the rarity colour and the corners are rounded.
            assert _nearest_rarity(img.getpixel((2, 422))) == ct
            assert img.getpixel((0, 0))[3] == 0
    # Up to 3 modifier lines: a fourth modifier is not drawn.
    rows = image._modifier_rows_from_map({"kills": 1, "assists": 2, "gpm": 3, "deaths": 4})
    assert len(rows) == 4 and image._MAX_MODIFIER_LINES == 3


def test_generate_card_image_unknown_card_type_falls_back_to_common():
    """Failure path: an unknown or missing rarity renders the common layout-A card at 597 x 845 instead of raising."""
    common = image.generate_card_image("common", "Player", None, "Team", None, {})
    for ct in ("mythic", "", None, "LEGENDARY-ish"):
        img = image.generate_card_image(ct, "Player", None, "Team", None, {})
        assert img.size == (597, 845)
        assert _same(img, common), ct
    # Upper case is the same rarity, not a fallback.
    assert _nearest_rarity(image.generate_card_image("RARE", "P", None, None, None).getpixel((2, 422))) == "rare"


def test_generate_card_image_avatar_184_fills_portrait_slot_exactly_2x(monkeypatch):
    """AC: the 184 x 184 avatar fills a 368 x 368 slot exactly (2x), with no crop, stretch or filler."""
    src = _quadrants(184)
    slot = image._PORTRAIT_SLOT
    assert image._slot_size(slot) == (368, 368)
    scaled = image._avatar_for_slot(src)
    assert scaled.size == (368, 368)
    # Exactly 2x: equal to the source scaled by 2, no crop or offset.
    assert _same(scaled, src.resize((368, 368), Image.LANCZOS))

    img = _render(monkeypatch, "common", avatar=src)
    x0, y0, x1, y1 = slot
    # Each corner of the slot shows its quadrant (no crop), and the slot is filled to
    # its edges (no filler); just outside it is the rarity-coloured portrait border.
    assert img.getpixel((x0 + 2, y0 + 2))[:3] == (200, 0, 0)
    assert img.getpixel((x1 - 3, y0 + 2))[:3] == (0, 200, 0)
    assert img.getpixel((x0 + 2, y1 - 3))[:3] == (0, 0, 200)
    assert img.getpixel((x1 - 3, y1 - 3))[:3] == (200, 200, 0)
    assert img.getpixel((x0 + 176, y0 + 2))[:3] == (200, 0, 0)
    assert img.getpixel((x0 + 192, y0 + 2))[:3] == (0, 200, 0)
    border = image._RARITY_COLORS["common"]
    for xy in ((x0 - 3, (y0 + y1) // 2), (x1 + 2, (y0 + y1) // 2), ((x0 + x1) // 2, y0 - 3)):
        assert img.getpixel(xy)[:3] == border, xy


def test_load_team_logo_for_card_250x150_fills_logo_slot_exactly(tmp_path, monkeypatch):
    """AC: a 250 x 150 cached logo fills a 100 x 60 slot exactly (0.4x), with no circle crop."""
    logo_dir = tmp_path / "dotabuff_league_logos"
    logo_dir.mkdir()
    src = Image.new("RGBA", (250, 150), (10, 120, 220, 255))
    src.paste((240, 30, 30, 255), (0, 0, 125, 75))
    src.save(logo_dir / "Logo_Team.png")
    assets = image._ASSETS_DIR
    monkeypatch.setattr(image, "_ASSETS_DIR", str(tmp_path))
    monkeypatch.setattr(image, "resolve_local_team_logo_path",
                        lambda d, name: str(logo_dir / "Logo_Team.png") if name == "Logo Team" else None)
    assert image._slot_size(image._LOGO_SLOT) == (100, 60)
    logo = image._load_team_logo_for_card("Logo Team", None, (100, 60))
    assert logo.size == (100, 60)
    # Exactly 0.4x: the whole logo, scaled, with no circle crop (corners kept).
    assert _same(logo, src.resize((100, 60), Image.LANCZOS))
    assert logo.getpixel((0, 0))[:3] == (240, 30, 30) and logo.getpixel((99, 59))[:3] == (10, 120, 220)
    # On the card it fills the logo slot to its corners.
    monkeypatch.setattr(image, "_ASSETS_DIR", assets)
    monkeypatch.setattr(image, "_load_team_logo_for_card", lambda n, u, s: logo)
    img = image.generate_card_image("rare", "P", None, "Logo Team", None, {})
    x0, y0, x1, y1 = image._LOGO_SLOT
    assert img.getpixel((x0, y0))[:3] == (240, 30, 30)
    assert img.getpixel((x1 - 1, y1 - 1))[:3] == (10, 120, 220)


def test_load_team_logo_for_card_square_or_tall_fallback_fits_without_stretch(monkeypatch):
    """Failure path: a fallback logo of another shape (square or tall) is fitted inside the 100 x 60 slot, centred, not stretched."""
    for size in ((120, 120), (80, 200)):
        src = Image.new("RGBA", size, (250, 250, 250, 255))
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda d, n: None)
        monkeypatch.setattr(image, "_fetch_team_logo_image", lambda url, s=None, _src=src: _src)
        logo = image._load_team_logo_for_card("Any", "https://example.com/logo.png", (100, 60))
        assert logo.size == (100, 60)
        bbox = Image.eval(logo.convert("L"), lambda v: 255 if v > 200 else 0).getbbox()
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # Fitted to the slot height, aspect ratio kept (no stretch), centred.
        assert h == 60
        assert abs(w / h - size[0] / size[1]) < 0.05, (size, w, h)
        assert abs((bbox[0] + bbox[2]) / 2 - 50) <= 1
        # The sides are the dark plate, not the logo.
        assert logo.getpixel((0, 30))[:3] == image._LOGO_PLATE[:3]


def test_generate_card_image_frame_edge_colour_by_rarity():
    """AC: rarity is shown by the frame edge colour: common grey, rare blue, epic purple, legendary gold."""
    expected = {"common": "grey", "rare": "blue", "epic": "purple", "legendary": "gold"}
    r, g, b = image._RARITY_COLORS["common"]
    assert max(r, g, b) - min(r, g, b) < 20                      # grey
    assert image._RARITY_COLORS["rare"][2] > image._RARITY_COLORS["rare"][0]      # blue
    assert image._RARITY_COLORS["epic"][0] > image._RARITY_COLORS["epic"][1] < image._RARITY_COLORS["epic"][2]  # purple
    assert image._RARITY_COLORS["legendary"][0] > image._RARITY_COLORS["legendary"][2]  # gold
    for ct in expected:
        img = image.generate_card_image(ct, "P", None, "T", None, {})
        for xy in ((2, 422), (594, 422), (298, 842), (298, 2)):
            assert _nearest_rarity(img.getpixel(xy)) == ct, (ct, xy)
    holo = image.generate_card_image("legendary", "P", None, "T", None, {}, is_holo=True)
    assert _nearest_rarity(holo.getpixel((2, 422))) == "legendary"


def test_generate_card_image_draws_no_gems_rarity_word_or_card_number(monkeypatch):
    """AC: no rarity gems, rarity word or card number are drawn on the image."""
    src = _read("backend", "image.py")
    for gone in ("_draw_rarity_gems", "_RARITY_GEMS", "_GEM_AREA", "card_id", "_CARD_NO_",
                 "rarity_text", "capitalize("):
        assert gone not in src, gone
    assert "card_id" not in inspect.signature(image.generate_card_image).parameters
    for ct in _RARITIES:
        texts = _drawn_texts(monkeypatch)
        img = _render(monkeypatch, ct, name="Ab", team="T1", mods={"kills": 5}, foil=False)
        assert set(texts) == {"Ab", "T1", "KILLS", "+5%"}, texts
        assert not [t for t in texts if t.lower() in _RARITIES or t.startswith("#")]
        tpl = _template(ct)
        # The pillars, and the right ends of the name bar and type line, are the bare template.
        for box in (image._LEFT_PILLAR, image._RIGHT_PILLAR, (300, 24, 573, 92), (300, 496, 573, 560)):
            assert _same(img.crop(box), tpl.crop(box)), (ct, box)
        monkeypatch.undo()


def test_generate_card_image_ordinary_legendary_has_light_shine(monkeypatch):
    """AC: an ordinary legendary has a light shine; common, rare and epic have none."""
    calls = []
    real = image._apply_foil_sheen
    monkeypatch.setattr(image, "_apply_foil_sheen", lambda img: calls.append(1) or real(img))
    for ct in ("common", "rare", "epic"):
        image.generate_card_image(ct, "P", None, "T", None, {})
    assert calls == []
    shiny = image.generate_card_image("legendary", "P", None, "T", None, {})
    assert calls == [1]
    monkeypatch.setattr(image, "_apply_foil_sheen", lambda img: img)
    plain = image.generate_card_image("legendary", "P", None, "T", None, {})
    whole = _mean_diff(shiny, plain)
    # A light shine: visible, but a small change to the card.
    assert 0.5 < whole < 12, whole
    # It is a light band: lighter, never darker.
    a, b = shiny.convert("L"), plain.convert("L")
    assert ImageStat.Stat(a).mean[0] > ImageStat.Stat(b).mean[0]


def test_generate_card_image_holo_with_template_much_shinier_than_legendary(monkeypatch):
    """AC: with Card_Template_Holo.png present, a Holo legendary has a much stronger rainbow shine on the frame and pillars than an ordinary legendary."""
    assert os.path.exists(os.path.join(image._ASSETS_DIR, "Card_Template_Holo.png"))
    shiny = image.generate_card_image("legendary", "P", None, "T", None, {})
    holo = image.generate_card_image("legendary", "P", None, "T", None, {}, is_holo=True)
    monkeypatch.setattr(image, "_apply_foil_sheen", lambda img: img)
    plain = image.generate_card_image("legendary", "P", None, "T", None, {})
    legendary_shine, holo_shine = _shine(shiny, plain), _shine(holo, plain)
    assert holo_shine > 30, holo_shine
    assert holo_shine > 4 * legendary_shine, (holo_shine, legendary_shine)
    # A Holo flag on another rarity is ignored.
    epic = image.generate_card_image("epic", "P", None, "T", None, {})
    assert _same(epic, image.generate_card_image("epic", "P", None, "T", None, {},
                                                                 is_holo=True))


def test_generate_card_image_holo_without_template_uses_generated_sheen(tmp_path, monkeypatch):
    """Failure path: without Card_Template_Holo.png, a Holo legendary still renders (Legendary template plus generated sheen) and is shinier than an ordinary legendary."""
    for name in ("Common", "Rare", "Epic", "Legendary"):
        shutil.copy(os.path.join(image._ASSETS_DIR, f"Card_Template_{name}.png"), tmp_path)
    shiny = image.generate_card_image("legendary", "P", None, "T", None, {})
    monkeypatch.setattr(image, "_ASSETS_DIR", str(tmp_path))
    monkeypatch.setattr(image, "_holo_warned", True)
    holo = image.generate_card_image("legendary", "P", None, "T", None, {}, is_holo=True)
    assert holo.size == (597, 845)
    monkeypatch.setattr(image, "_apply_foil_sheen", lambda img: img)
    plain = image.generate_card_image("legendary", "P", None, "T", None, {})
    assert _shine(holo, plain) > 2 * _shine(shiny, plain), (_shine(holo, plain), _shine(shiny, plain))
    # The generated sheen stays off the cutouts: the empty portrait slot is the base colour.
    cx, cy = (image._PORTRAIT_SLOT[0] + image._PORTRAIT_SLOT[2]) // 2, (image._PORTRAIT_SLOT[1] + image._PORTRAIT_SLOT[3]) // 2
    assert holo.getpixel((cx, cy)) == image._BASE_COLOR


def test_make_card_templates_holo_text_panels_stay_readable():
    """AC: the Holo template's rainbow is strong on the frame and pillars and only a faint tint on the name bar, type line and rules box."""
    gen = _generator()
    holo, legendary = gen.draw_holo_template(), gen.draw_template("legendary")
    inner = lambda box: (box[0] + 12, box[1] + 8, box[2] - 12, box[3] - 8)
    strong = min(_mean_diff(holo, legendary, inner(b)) for b in (image._LEFT_PILLAR, image._RIGHT_PILLAR))
    faint = max(_mean_diff(holo, legendary, inner(b))
                for b in (image._NAME_BAR, image._TYPE_LINE, image._RULES_BOX))
    assert strong > 40, strong
    assert faint < strong / 4, (faint, strong)
    # The cream rules box stays light, so its dark text keeps its contrast.
    assert ImageStat.Stat(holo.crop(inner(image._RULES_BOX)).convert("L")).mean[0] > 170


def test_card_templates_have_transparent_cutouts_at_slots():
    """AC: each committed Card_Template_<Rarity>.png is 597 x 845 RGBA with transparent cutouts at the portrait and logo slots."""
    names = list(image._CARD_TEMPLATES.values()) + ["Card_Template_Holo.png"]
    for name in names:
        tpl = Image.open(os.path.join(image._ASSETS_DIR, name))
        assert tpl.size == (597, 845) and tpl.mode == "RGBA", name
        for slot in (image._PORTRAIT_SLOT, image._LOGO_SLOT):
            assert tpl.crop(slot).getchannel("A").getextrema() == (0, 0), (name, slot)
            # Opaque right around the cutout.
            assert tpl.getpixel((slot[0] - 1, (slot[1] + slot[3]) // 2))[3] == 255, (name, slot)
        assert tpl.crop(image._LEFT_PILLAR).getchannel("A").getextrema() == (255, 255)


def test_make_card_templates_output_matches_committed_pngs(tmp_path):
    """AC: the templates are drawn by backend/scripts/make_card_templates.py, and the committed PNGs match its output."""
    gen = _generator()
    drawn = {name: gen.draw_template(rarity) for rarity, name in image._CARD_TEMPLATES.items()}
    drawn["Card_Template_Holo.png"] = gen.draw_holo_template()
    for name, img in drawn.items():
        committed = Image.open(os.path.join(image._ASSETS_DIR, name)).convert("RGBA")
        diff = ImageChops.difference(img, committed)
        # Exact, give or take a step of antialiasing between Pillow versions.
        assert max(hi for lo, hi in diff.getextrema()) <= 3, name
    # main() writes all five files.
    out = tmp_path / "assets"
    out.mkdir()
    written = gen.main(str(out))
    assert sorted(os.path.basename(p) for p in written) == sorted(drawn)


def test_generate_card_image_draws_no_league_name(monkeypatch):
    """AC: no league name (and no image from a Dota CDN) on the card; image.py and the generator name no league."""
    banned = ("kanaliiga", "dota2.com", "steamstatic", "cloudflare", "akamai", "valve")
    for src in (_read("backend", "image.py"), _read("backend", "scripts", "make_card_templates.py")):
        for word in banned:
            assert word not in src.lower(), word
    fetched = []
    monkeypatch.setattr(image, "_fetch_pil_image", lambda url, size=None: fetched.append(url) or _quadrants())
    texts = _drawn_texts(monkeypatch)
    image.generate_card_image("legendary", "Player", "https://avatars.example/a.png", "Team", None,
                              {"kills": 5}, is_holo=True)
    assert fetched == ["https://avatars.example/a.png"]
    assert not [t for t in texts if "league" in t.lower() or "kanaliiga" in t.lower()]


# ---------------------------------------------------------------------------
# Deferred: Rank Medal on the Card (product-owner decision, 25 Oct)
# ---------------------------------------------------------------------------

def test_generate_card_image_takes_no_rank_arguments_and_draws_no_medal(monkeypatch):
    """Deferred medal: generate_card_image takes no rank_tier or leaderboard_rank, and the PNG draws no rank medal in the left pillar."""
    params = inspect.signature(image.generate_card_image).parameters
    assert "rank_tier" not in params and "leaderboard_rank" not in params
    assert not [p for p in params if "rank" in p or "medal" in p]
    with pytest.raises(TypeError):
        image.generate_card_image("common", "P", None, None, None, rank_tier=54)
    src = _read("backend", "image.py")
    assert "_draw_rank_medal" not in src and "player_rank" not in src and "MEDAL" not in src
    # The left pillar is the bare template (no medal) on every rarity.
    for ct in _RARITIES:
        img = _render(monkeypatch, ct, foil=False)
        box = image._LEFT_PILLAR
        assert _same(img.crop(box), _template(ct).crop(box)), ct


# ===========================================================================
# Story: Pips Sit in the Pillars
# ===========================================================================

def test_card_pips_css_positioned_and_sized_in_container_units():
    """AC: .card-tag-pips (left pillar) and .card-pips (right pillar) are positioned and sized in container units, so they scale with the card."""
    css = _fe("style.css")
    block = _supports_block(css)
    assert "--card-u: 1cqw" in block
    # px fallback where container queries don't work: the 180 px roster card, the 200 px viewer.
    assert "--card-u: 1.8px" in _rule(css, ".card-slot")[-1] or any("--card-u: 1.8px" in b for b in _rule(css, ".card-slot"))
    assert any("--card-u: 2px" in b for b in _rule(css, ".reveal-img-wrap"))
    left_c, right_c = _px_to_u((24 + 104) / 2), _px_to_u(597 - (492 + 572) / 2)
    for sel, side, centre in ((".card-slot .card-tag-pips", "left", left_c),
                              (".reveal-pips .card-tag-pips", "left", left_c),
                              (".card-slot .card-pips", "right", right_c),
                              (".reveal-pips .card-pips", "right", right_c)):
        body = _rule(css, sel)[0]
        font = _units(body, "font-size")
        pip = 1.7 * font          # .accolade-pip / .card-tag-pip are 1.7em square
        assert 9.5 <= pip <= 10.5, (sel, pip)
        pad = _units(body, "padding")
        # The column is centred on the pillar.
        assert abs(_units(body, side) + pad + pip / 2 - centre) < 0.3, sel
        # It starts at the portrait row.
        assert _px_to_u(104) <= _units(body, "top") <= _px_to_u(130), sel
    for sel in (".card-pips .accolade-pips", ".card-tag-pips .tag-pips"):
        assert "calc(var(--card-u)" in _rule(css, sel)[0]
    for sel in (".accolade-pip", ".card-tag-pip"):
        body = [b for b in _rule(css, sel) if "width:" in b][0]
        assert "width: 1.7em" in body and "height: 1.7em" in body


def test_card_wrappers_declare_container_type():
    """AC: the card wrappers (.card-slot, the reveal image wrap, Weekly Report cards) declare container-type: inline-size."""
    css = _fe("style.css")
    block = _supports_block(css)
    rules = [(sel, body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block)]
    declared = {s.strip() for sel, body in rules if "container-type: inline-size" in body
                for s in sel.split(",")}
    # The roster card slot, the card viewer / draw reveal image wrap, the #205 landing clone.
    assert {".card-slot", ".reveal-img-wrap", ".draw-landing"} <= declared, declared
    # Inline-size containment ignores content width, so each wrapper has its own width.
    assert any("width: 180px" in b for b in _rule(css, ".card-slot"))
    assert "width: 200px" in _rule(css, ".reveal-img-wrap")[0]
    html = _fe("index.html")
    wrap = html[html.index('id="revealImgWrap"'):]
    assert wrap.index('id="revealPips"') < wrap.index("</div>\n    <div")
    # The Weekly Report shows its roster as avatar thumbnails and opens a card in the
    # card viewer, so its pips are the reveal wrap's.
    assert "showCard(" in _fn_body(_fe("app-weekly-summary.js"), "_weeklySummaryShowCard")


def test_card_tag_pips_css_column_stops_at_pillar_bottom():
    """Failure path: with more tag pips than fit, the column's max-height stops it at the pillar's bottom (no overlap with the type line)."""
    css = _fe("style.css")
    bottom = _px_to_u(484)
    for sel in (".card-slot .card-tag-pips", ".reveal-pips .card-tag-pips",
                ".card-slot .card-pips", ".reveal-pips .card-pips"):
        body = _rule(css, sel)[0]
        assert "overflow: hidden" in body and "box-sizing: border-box" in body, sel
        end = _units(body, "top") + _units(body, "max-height")
        assert end <= bottom + 0.1, (sel, end, bottom)
        assert end < _px_to_u(image._TYPE_LINE[1]), sel
        # At least four pips fit before the column stops.
        pip, gap = 1.7 * _units(body, "font-size"), 2.0
        inner = _units(body, "max-height") - 2 * _units(body, "padding")
        assert 4 * pip + 3 * gap <= inner, sel


def test_pip_helpers_keep_tooltips_focus_and_aria_labels():
    """AC: tagPipsHtml and accoladePipsHtml pips keep their data-tip tooltips, tabindex="0" focus and aria-labels."""
    tag_markup = _tag_pips('[{"key": "admin", "label": "Admin"}, {"key": "veteran", "label": "Veteran"}]')
    tags = _pip_attrs(tag_markup, "card-tag-pip")
    acc_markup = _pips([_a("most_points", "Season 15"), _a("champion", "Season 14", "div1", "Reds")])
    accs = _pip_attrs(acc_markup, "accolade-pip")
    assert len(tags) == 2 and len(accs) == 2
    for a in tags + accs:
        assert a.get("tabindex") == "0" and a.get("role") == "listitem"
        assert a.get("aria-label") and a.get("data-tip")
    assert [a["data-tip"] for a in tags] == [a["aria-label"] for a in tags]
    # The overlays stay hoverable over the image.
    css = _fe("style.css")
    assert "pointer-events: auto" in _rule(css, ".card-tag-pips .card-tag-pip")[0]
    assert "pointer-events: auto" in _rule(css, ".card-pips .accolade-pip")[0]


def test_generate_card_image_takes_no_accolades_or_tags(monkeypatch):
    """Failure path: generate_card_image takes no accolades or tags argument, so the PNG itself draws no tags or accolades (#217 stays true)."""
    params = inspect.signature(image.generate_card_image).parameters
    assert list(params) == ["card_type", "player_name", "avatar_url", "team_name",
                            "team_logo_url", "card_modifiers", "is_holo"]
    for kw in ({"accolades": [{"key": "caster"}]}, {"tag_keys": ["caster"]}):
        with pytest.raises(TypeError):
            image.generate_card_image("common", "P", None, None, None, **kw)
    src = _read("backend", "image.py")
    assert "_draw_accolades" not in src and "_load_sticker" not in src and "stickers" not in src.lower()
    # The right pillar is the bare template.
    img = _render(monkeypatch, "epic")
    box = image._RIGHT_PILLAR
    assert _same(img.crop(box), _template("epic").crop(box))
