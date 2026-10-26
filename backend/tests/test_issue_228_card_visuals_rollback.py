"""
Tests for plan-issue-228-card-visuals-rollback.md (resolves GitHub issue #228).

#218 ("layout A", commit da89798) is rolled back: the original illustrated card
templates and the pre-#218 renderer (`backend/image.py` as of `da89798^`) return,
the generated Holo template and its generator are removed, and accolade and tag
pips leave every card face. The card viewer (`#revealModal`) gains a Tags section
and an Accolades section with details, built by `tagDetailsHtml` and
`accoladeDetailsHtml` in frontend/app-globals.js. Issue 230 moved the accolade
details to the player popup's timeline (`accoladeDetailLine`, `accoladePlayedLine`)
and left the card viewer with the Tags section; the tests below follow that.

  Story 1: Cards Return to the Original Art
  Story 2: Accolades and Tags Leave the Card Face
  Story 3: Accolade and Tag Details in the Card Popup
  Step 4:  Extra checks (geometry, CSS placement, harness checks)

Notes for the developer:

- Restored files are pinned by SHA-256 of the `da89798^` blobs (below), so CI needs
  no git history. Computed with `git show da89798^:<path> | sha256sum`.
  `git log da89798..HEAD -- backend/image.py` is empty, so image.py should match its
  pre-#218 blob exactly; if something must be kept on top of it, replace the image.py
  hash test with checks of the pre-#218 constants (_BIG_CIRCLE, _SMALL_CIRCLE, ...).
- Pre-#218 renderer constants: `_BIG_CIRCLE = (298, 375, 175)` (350 px portrait
  circle), `_SMALL_CIRCLE = (444, 258, 52)` (104 px logo circle), `_PLAYER_NAME_Y = 90`,
  `_TEAM_NAME_Y = 155`, `_CARD_SIZE = (597, 845)`, `_MODIFIERS_START_Y = 620`,
  `_HOLO_TEMPLATE = "Card_Template_Holo.png"`, `_holo_sheen`, `_load_template`.
- Compare images with `a.tobytes() == b.tobytes()` (lessons-learned: RGBA getbbox
  checks alpha only); see `_same` in the old test_issue_218_card_formatting.py.
- Never touch the real app database: use the `db` fixture, and for routes the
  `_client` helper from test_issue_50 (shared-connection override of get_db).
- Frontend: reuse `_fe`, `_fn_body`, `_fn_source`, `_read`, `_rule`, `_run_node`
  from test_issue_50 and the Node-harness pattern of test_issue_217 (app-globals.js
  ACCOLADES / TAG SYMBOLS blocks, markup parsed with `html.parser`, never regexes over
  HTML tags). For the draw reveal, reuse `_HARNESS` / `_run` in
  test_issue_205_card_draw_animations.py.
- test_issue_218_card_formatting.py is deleted by this plan (its layout A tests are
  replaced by these).
"""

import hashlib
import io
import json
import os
import re
import shutil
from html.parser import HTMLParser

import pytest

import models  # noqa: F401  (register tables for the db fixture)
from models import Card, Player, User
from tests.test_issue_50_season_winners_and_holo_cards import (  # noqa: F401  (db fixture used by name)
    _a, _client, _css_blocks, _fe, _fn_body, _fn_source, _read, _rule, _run_node, _user, db,
)
from tests.test_issue_205_card_draw_animations import _run as _run_draw

# SHA-256 of the da89798^ blobs (the pre-#218 originals).
TEMPLATE_SHA256 = {
    "Card_Template_Common.png": "057747d09772646b1caa4fe0486070f9c1a716c1883a011754bcdce13b76e227",
    "Card_Template_Rare.png": "5cdd80538cbe57295b795ff2ab25986bad1ba06d0e03ac46cece84ccfb5dbab5",
    "Card_Template_Epic.png": "fa06c9b16575b47b32ef77b53f78fe143473fb8594f89c14c5e4c647c98a0fc7",
    "Card_Template_Legendary.png": "d2181a108f56271ab5c8c10bc1affa14fbc3f577045e5fd3a4b9e61c208c277e",
}
# The da89798^ blob with one docstring correction in generate_card_image (issue 228);
# the geometry tests below pin the rendering itself.
IMAGE_PY_SHA256 = "24b8819d5ff3cdf48c12ef15237a7693c61cddb2488ae0ad594f361ac5219db6"



_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _image():
    image = pytest.importorskip("image")
    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    return image


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _same(a, b):
    """Pixel-identical, all channels (an RGBA difference's getbbox() checks alpha only)."""
    return a.size == b.size and a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()


def _template(image, ct):
    from PIL import Image
    return Image.open(os.path.join(image._ASSETS_DIR, image._CARD_TEMPLATES[ct])).convert("RGBA")


def _no_fetch(image, monkeypatch, avatar=None, logo=None):
    """No network: the avatar and the team logo come from the given images (or none)."""
    monkeypatch.setattr(image, "_fetch_pil_image",
                        lambda url, d: avatar(d) if callable(avatar) else avatar)
    monkeypatch.setattr(image, "_load_team_logo_for_card",
                        lambda name, url, d: logo(d) if callable(logo) else logo)


def _render(image, ct="common", name="Ab", team="T1", mods=None, is_holo=False, avatar=False):
    return image.generate_card_image(ct, name, "https://avatars.example/a.png" if avatar else None,
                                     team, None, mods or {}, is_holo=is_holo)


def _quadrants(size):
    """A square avatar with four solid quadrants, so a crop or offset shows."""
    from PIL import Image
    img = Image.new("RGBA", (size, size), (200, 0, 0, 255))
    h = size // 2
    img.paste((0, 200, 0, 255), (h, 0, size, h))
    img.paste((0, 0, 200, 255), (0, h, h, size))
    img.paste((200, 200, 0, 255), (h, h, size, size))
    return img


def _transparent_template(image, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(image, "_load_template",
                        lambda ct, is_holo: Image.new("RGBA", image._CARD_SIZE, (0, 0, 0, 0)))


def _seed_card(db, card_type="common"):
    player = Player(id=4242, name="Restored", is_active=True)
    db.add(player)
    owner = _user(db, "artowner")
    card = Card(owner_id=owner.id, player_id=player.id, card_type=card_type,
                is_active=False, generation=1)
    db.add(card)
    db.commit()
    return card


def _image_client(db, monkeypatch):
    from routers import cards as cards_router
    monkeypatch.setattr(cards_router.limiter, "enabled", False)
    return _client(db)


def _globals_js():
    js = _fe("app-globals.js")
    start = js.index("// ACCOLADES (issue 50)")
    end = js.index("// END ACCOLADES (issue 50)")
    return (_fn_source(js, "_escHtml") + "\n" + _fn_source(js, "_ownValue") + "\n"
            + js[start:end])


def _node_out(expr, prelude=""):
    return _run_node(_globals_js() + "\n" + prelude + f"\nconsole.log(JSON.stringify({expr}));\n")


class _Lines(HTMLParser):
    """Each section (div.card-details) with its title and its lines: the symbol's
    classes, icon, aria-hidden and the line's text (disclosure seasons separately)."""

    def __init__(self):
        super().__init__()
        self.sections, self.lines = [], []
        self._in, self._stack = None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        self._stack.append((tag, cls))
        if tag == "div" and "card-details" in cls:
            self.sections.append({"classes": cls, "title": ""})
        elif tag == "h3":
            self._in = "title"
        elif tag == "li" and "card-detail" in cls:
            self.lines.append({"symbol": None, "icon": None, "aria_hidden": None, "text": "",
                               "seasons": [], "details": False, "summary": ""})
            self._in = "line"
        elif tag == "span" and "card-detail-symbol" in cls and self.lines:
            self.lines[-1]["symbol"] = cls
            self.lines[-1]["aria_hidden"] = a.get("aria-hidden")
        elif tag == "i" and self.lines and a.get("data-lucide"):
            self.lines[-1]["icon"] = a["data-lucide"]
        elif tag == "details" and self.lines:
            self.lines[-1]["details"] = True
        elif tag == "summary":
            self._in = "summary"
        elif tag == "li" and self.lines and any("card-detail-seasons" in c for _, c in self._stack[:-1]):
            self._in = "season"
            self.lines[-1]["seasons"].append("")

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()
        if tag in ("h3", "summary") or (tag == "li" and self._in == "season"):
            self._in = "line" if self.lines else None

    def handle_data(self, data):
        if self._in == "title" and self.sections:
            self.sections[-1]["title"] += data
        elif self._in == "season":
            self.lines[-1]["seasons"][-1] += data
        elif self._in == "summary":
            self.lines[-1]["summary"] += data
            self.lines[-1]["text"] += data
        elif self._in == "line" and self.lines:
            self.lines[-1]["text"] += data


def _parse(markup):
    p = _Lines()
    p.feed(markup)
    return p


class _Classes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.classes = []

    def handle_starttag(self, tag, attrs):
        self.classes += (dict(attrs).get("class") or "").split()


def _classes(markup):
    p = _Classes()
    p.feed(markup)
    return p.classes


def _reveal_modal_html():
    html = _fe("index.html")
    start = html.index("<!-- CARD REVEAL MODAL -->")
    return html[start:html.index("<!--", start + 10)]


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.attrs = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
            self.attrs[a["id"]] = a


def _ids(markup):
    p = _Ids()
    p.feed(markup)
    return p


_CHAMPION = [_a("champion", "Season 15", "div1", "Team Name"), _a("most_points", "Season 15", value=812.3),
             _a("champion", "Season 14", "div2", "Old Team"), _a("played", "Season 15"), _a("played", "Season 14")]
_TAGS = [{"key": "caster", "label": "Caster"}, {"key": "admin", "label": "Admin"}]
_DETAILS_CSS = r"\.reveal-details|\.card-details|\.card-detail"


def _details_rules(css):
    return _css_blocks(css, _DETAILS_CSS)



# ---------------------------------------------------------------------------
# Story 1: Cards Return to the Original Art
# ---------------------------------------------------------------------------

class TestOriginalArt:

    def test_card_templates_byte_identical_to_pre_218(self):
        """Each of assets/Card_Template_{Common,Rare,Epic,Legendary}.png (resolved via
        image._ASSETS_DIR and image._CARD_TEMPLATES) exists and its SHA-256 equals
        TEMPLATE_SHA256[name]."""
        image = pytest.importorskip("image")
        assert sorted(image._CARD_TEMPLATES.values()) == sorted(TEMPLATE_SHA256)
        for name, digest in TEMPLATE_SHA256.items():
            path = os.path.join(image._ASSETS_DIR, name)
            assert os.path.isfile(path), name
            assert _sha256(path) == digest, name

    def test_image_py_restored_from_pre_218(self):
        """backend/image.py's SHA-256 equals IMAGE_PY_SHA256 (the da89798^ blob plus one docstring fix); see the
        module notes if additions on top of it become necessary."""
        assert _sha256(os.path.join(_ROOT, "backend", "image.py")) == IMAGE_PY_SHA256

    def test_image_module_has_no_layout_a_symbols(self):
        """The image module defines none of #218's layout A names (_LEFT_PILLAR,
        _RIGHT_PILLAR, _RARITY_COLORS, _apply_foil_sheen and the portrait/logo slot
        constants), and does define _BIG_CIRCLE == (298, 375, 175) and
        _SMALL_CIRCLE == (444, 258, 52)."""
        image = pytest.importorskip("image")
        for name in ("_LEFT_PILLAR", "_RIGHT_PILLAR", "_RARITY_COLORS", "_RARITY_DEEP",
                     "_apply_foil_sheen", "_PORTRAIT_SLOT", "_PORTRAIT_FRAME", "_LOGO_SLOT",
                     "_NAME_BAR", "_TYPE_LINE", "_RULES_BOX"):
            assert not hasattr(image, name), name
        assert image._BIG_CIRCLE == (298, 375, 175)
        assert image._SMALL_CIRCLE == (444, 258, 52)
        assert image._PLAYER_NAME_Y == 90 and image._TEAM_NAME_Y == 155
        assert image._MODIFIERS_START_Y == 620 and image._CARD_SIZE == (597, 845)
        assert image._HOLO_TEMPLATE == "Card_Template_Holo.png"
        assert callable(image._holo_sheen) and callable(image._load_template)

    def test_get_card_image_route_renders_on_restored_template(self, db, monkeypatch):
        """GET /cards/{id}/image for a seeded common card (db fixture, `_client` from
        test_issue_50, image fetches monkeypatched to None) answers 200 image/png whose
        pixels outside the portrait circle, logo circle and text rows equal the restored
        Common template at those pixels (tobytes comparison of crops)."""
        image = _image()
        from PIL import Image
        _no_fetch(image, monkeypatch)
        card = _seed_card(db)
        res = _image_client(db, monkeypatch).get(f"/cards/{card.id}/image")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        got = Image.open(io.BytesIO(res.content)).convert("RGBA")
        assert got.size == image._CARD_SIZE
        expected = Image.new("RGBA", image._CARD_SIZE, (35, 37, 40, 255))
        expected.alpha_composite(_template(image, "common"))
        # Above the name row, and below the portrait circle (no modifiers on a fresh common).
        for box in ((0, 0, 597, 60), (0, 560, 597, 845)):
            assert _same(got.crop(box), expected.crop(box)), box

    def test_get_card_image_route_missing_card_returns_404(self, db, monkeypatch):
        """GET /cards/{id}/image for an id with no Card row answers 404 (failure path;
        the rollback must not change the route's error handling)."""
        _image()
        res = _image_client(db, monkeypatch).get("/cards/987654/image")
        assert res.status_code == 404
        assert res.json()["detail"] == "Card not found"

    def test_generate_card_image_every_rarity_renders_597x845(self, monkeypatch):
        """image.generate_card_image for common, rare, epic, legendary and a Holo
        legendary, with 0 to 3 modifiers, returns a 597 x 845 image (image._CARD_SIZE)."""
        image = _image()
        _no_fetch(image, monkeypatch)
        monkeypatch.setattr(image, "_holo_warned", True)
        mods = [{}, {"kills": 5}, {"kills": 5, "assists": 10}, {"kills": 5, "assists": 10, "gpm": 15}]
        for ct, holo in (("common", False), ("rare", False), ("epic", False),
                         ("legendary", False), ("legendary", True)):
            for m in mods:
                img = _render(image, ct, mods=m, is_holo=holo)
                assert img.size == image._CARD_SIZE == (597, 845), (ct, holo, m)

    def test_generate_card_image_unknown_card_type_falls_back_to_common(self, monkeypatch):
        """An unknown card_type renders without error, 597 x 845, on the Common template
        (same pixels as a 'common' render with identical inputs)."""
        image = _image()
        _no_fetch(image, monkeypatch)
        odd = _render(image, "mythic")
        assert odd.size == (597, 845)
        assert _same(odd, _render(image, "common"))
        assert not _same(odd, _render(image, "rare"))

    def test_holo_without_template_uses_legendary_with_generated_sheen(self, tmp_path, monkeypatch):
        """With no Card_Template_Holo.png in the assets dir, image._load_template('legendary',
        True) equals the Legendary template with image._holo_sheen alpha-composited on it,
        and differs from _load_template('legendary', False) (tobytes comparison)."""
        image = _image()
        shutil.copy(os.path.join(image._ASSETS_DIR, "Card_Template_Legendary.png"), tmp_path)
        monkeypatch.setattr(image, "_ASSETS_DIR", str(tmp_path))
        monkeypatch.setattr(image, "_holo_warned", True)
        assert not os.path.exists(tmp_path / "Card_Template_Holo.png")
        plain = image._load_template("legendary", False)
        expected = plain.copy()
        expected.alpha_composite(image._holo_sheen(plain))
        holo = image._load_template("legendary", True)
        assert _same(holo, expected)
        assert not _same(holo, plain)

    def test_holo_template_file_removed(self):
        """assets/Card_Template_Holo.png does not exist in the repo (failure path for the
        Holo story: a leftover #218 Holo template would bypass the #105 sheen)."""
        assert not os.path.exists(os.path.join(_ROOT, "assets", "Card_Template_Holo.png"))
        assert not os.path.exists(os.path.join(_ROOT, "assets", "card_template_holo.png"))
        image = pytest.importorskip("image")
        assert image._holo_template_path() is None

    def test_make_card_templates_script_removed(self):
        """backend/scripts/make_card_templates.py does not exist, and no file under
        backend/ (excluding tests) or scripts/ references `make_card_templates`."""
        assert not os.path.exists(os.path.join(_ROOT, "backend", "scripts", "make_card_templates.py"))
        offenders = []
        for top in ("backend", "scripts"):
            for dirpath, dirnames, filenames in os.walk(os.path.join(_ROOT, top)):
                dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__", ".pytest_cache")
                               and not d.startswith(".")]
                for fn in filenames:
                    if not fn.endswith((".py", ".sh", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".md")):
                        continue
                    path = os.path.join(dirpath, fn)
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        if "make_card_templates" in f.read():
                            offenders.append(os.path.relpath(path, _ROOT))
        assert offenders == []

    def test_blank_team_logo_placeholder_drawn_in_logo_circle(self, monkeypatch):
        """With no team logo (team_logo_url None and no fetch result), the logo circle
        (_SMALL_CIRCLE) shows the #107 blank placeholder from image._blank_logo_placeholder
        rather than the bare template."""
        image = _image()
        _no_fetch(image, monkeypatch)
        scx, scy, sr = image._SMALL_CIRCLE
        placeholder = image._blank_logo_placeholder(sr * 2)
        assert placeholder.size == (sr * 2, sr * 2)
        assert placeholder.getcolors() == [(sr * 2 * sr * 2, (0, 0, 0, 255))]
        img = _render(image, "common", team=None)
        assert img.getpixel((scx, scy)) == (0, 0, 0, 255)
        # The bare template is transparent there: without the placeholder the dark base shows.
        assert _template(image, "common").getpixel((scx, scy))[3] == 0

    def test_card_views_use_same_card_image_url(self):
        """My Team (app-roster.js), the collection and card viewer (app-cards.js) and the
        Weekly Report (through the card viewer) load card art from `/cards/{id}/image`
        (source inspection), so they all show the restored art. The Twitch panel draws
        its own card art and loads no card PNG. No frontend or panel file references a
        card template or a layout A-specific asset."""
        assert "return `${API}/cards/${cardId}/image" in _fn_body(_fe("app-globals.js"), "cardImageUrl")
        assert "cardImageUrl(c.id)" in _fn_body(_fe("app-roster.js"), "_cardSlotHTML")
        assert "cardImageUrl(card.id)" in _fn_body(_fe("app-cards.js"), "showCard")
        # The Weekly Report opens its roster cards in the card viewer (showCard).
        assert "showCard(" in _fn_body(_fe("app-weekly-summary.js"), "_weeklySummaryShowCard")
        sources = {}
        for folder in ("frontend", "twitch-extension"):
            for fn in os.listdir(os.path.join(_ROOT, folder)):
                if fn.endswith((".js", ".html", ".css")):
                    sources[f"{folder}/{fn}"] = _read(folder, fn)
        for path, src in sources.items():
            assert "Card_Template" not in src, path
            assert "make_card_templates" not in src, path
            assert not re.search(r"\bpillars?\b|\blayout A\b", src), path


# ---------------------------------------------------------------------------
# Step 4: Pre-#218 geometry
# ---------------------------------------------------------------------------

class TestPre218Geometry:

    def test_avatar_cropped_into_350px_portrait_circle(self, monkeypatch):
        """A quadrant-coloured avatar renders inside the circle centred (298, 375 + layout
        offset) with radius 175: pixels just inside the radius on each axis carry the
        avatar's colours and pixels just outside equal the template."""
        image = _image()
        sizes = []
        _no_fetch(image, monkeypatch, avatar=lambda d: (sizes.append(d), _quadrants(d))[1])
        _transparent_template(image, monkeypatch)
        base = (35, 37, 40, 255)
        for ct, off in (("common", 0), ("epic", image._CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY)):
            img = _render(image, ct, name="", team=None, avatar=True)
            cx, cy, r = image._BIG_CIRCLE
            cy += off
            inside = {(cx, cy - r + 3): (0, 200, 0, 255),       # top: top-right quadrant
                      (cx, cy + r - 3): (200, 200, 0, 255),     # bottom: bottom-right
                      (cx - r + 3, cy): (0, 0, 200, 255),       # left: bottom-left
                      (cx + r - 3, cy): (200, 200, 0, 255),     # right: bottom-right
                      (cx - 60, cy - 60): (200, 0, 0, 255)}     # top-left quadrant
            for xy, colour in inside.items():
                assert img.getpixel(xy) == colour, (ct, xy)
            for xy in ((cx, cy - r - 3), (cx, cy + r + 3), (cx - r - 3, cy), (cx + r + 3, cy)):
                assert img.getpixel(xy) == base, (ct, xy)
        assert set(sizes) == {350}

    def test_team_logo_cropped_into_104px_logo_circle(self, monkeypatch):
        """A solid-colour team logo renders inside the circle centred (444, 258 + layout
        offset) with radius 52; a pixel at the centre has the logo colour and a pixel
        10 px outside the radius equals the template."""
        image = _image()
        from PIL import Image
        sizes = []
        colour = (10, 20, 230, 255)
        for ct, off in (("common", 0), ("epic", image._CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY)):
            _no_fetch(image, monkeypatch, logo=lambda d: (sizes.append(d), Image.new("RGBA", (d, d), colour))[1])
            img = _render(image, ct, name="", team=None)
            _no_fetch(image, monkeypatch, logo=lambda d: Image.new("RGBA", (d, d), (240, 0, 0, 255)))
            other = _render(image, ct, name="", team=None)
            scx, scy, sr = image._SMALL_CIRCLE
            scy += off
            assert img.getpixel((scx, scy)) == colour, ct
            for xy in ((scx, scy - sr - 10), (scx, scy + sr + 10), (scx - sr - 10, scy), (scx + sr + 10, scy)):
                # Outside the circle the logo leaves no trace: the same pixel whatever the logo.
                assert img.getpixel(xy) == other.getpixel(xy), (ct, xy)
                assert img.getpixel(xy) != colour
        assert set(sizes) == {104}

    def test_name_team_and_modifiers_drawn_at_pre_218_rows(self, monkeypatch):
        """Recording _draw_centered_text calls: the player name is drawn at y=90, the team
        name at y=155 and modifier lines from y=620 in 50 px steps (plus
        _CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY for epic and legendary)."""
        image = _image()
        _no_fetch(image, monkeypatch)
        calls = []
        real = image._draw_centered_text

        def spy(draw, text, cx, cy, font, fill, shadow=(0, 0, 0, 160)):
            calls.append((text, cx, cy))
            return real(draw, text, cx, cy, font, fill, shadow=shadow)

        monkeypatch.setattr(image, "_draw_centered_text", spy)
        mods = {"kills": 5, "assists": 10, "gpm": 15}
        for ct in ("common", "rare", "epic", "legendary"):
            calls.clear()
            off = image._CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY if ct in ("epic", "legendary") else 0
            _render(image, ct, name="Ab", team="Reds", mods=mods)
            rows = [(t, cx, cy) for t, cx, cy in calls]
            assert rows[0] == ("AB", 298, 90 + off), ct
            assert rows[1] == ("REDS", 298, 155 + off), ct
            assert [cy for _, _, cy in rows[2:]] == [620 + off, 670 + off, 720 + off], ct
            assert len(rows) == 5


# ---------------------------------------------------------------------------
# Story 2: Accolades and Tags Leave the Card Face
# ---------------------------------------------------------------------------

class TestPipsOffCardFaces:

    def test_card_slot_html_has_no_accolade_or_tag_pips(self):
        """`_cardSlotHTML` in app-roster.js (source and Node harness with a player that has
        accolades and tags) produces markup with no element of class card-pips or
        card-tag-pips and calls neither accoladePipsHtml nor tagPipsHtml."""
        roster = _fe("app-roster.js")
        slot = _fn_body(roster, "_cardSlotHTML")
        assert "accoladePipsHtml" not in slot and "tagPipsHtml" not in slot
        out = _node_out("{html, calls}", prelude=f"""
let calls = 0;
const _realPips = accoladePipsHtml, _realTags = tagPipsHtml;
accoladePipsHtml = (...a) => {{ calls++; return _realPips(...a); }};
tagPipsHtml = (...a) => {{ calls++; return _realTags(...a); }};
const API = "";
function cardImageUrl(id) {{ return `/cards/${{id}}/image`; }}
function _subLabelHTML() {{ return ""; }}
function playerAccolades() {{ return {json.dumps(_CHAMPION)}; }}
function playerTags() {{ return {json.dumps(_TAGS)}; }}
{_fn_source(roster, "_cardSlotHTML")}
const html = _cardSlotHTML({{id: 5, player_id: 7, player_name: "Glete", total_points: 12.5}});
""")
        classes = _classes(out["html"])
        assert "card-img" in classes and "card-slot-pts" in classes
        assert not {"card-pips", "card-tag-pips", "accolade-pip", "card-tag-pip"} & set(classes)
        assert out["calls"] == 0

    def test_render_reveal_tags_puts_no_pips_on_card(self):
        """`_renderRevealTags` in app-cards.js (issue 230; `_renderCardAccolades` before),
        run in a Node harness for a champion with tags, writes no card-pips /
        card-tag-pips markup anywhere; #revealPips is gone from index.html or left empty."""
        cards = _fe("app-cards.js")
        out = _node_out("{written, calls}", prelude=f"""
let calls = 0;
const _realPips = accoladePipsHtml, _realTags = tagPipsHtml;
accoladePipsHtml = (...a) => {{ calls++; return _realPips(...a); }};
tagPipsHtml = (...a) => {{ calls++; return _realTags(...a); }};
const els = {{}};
const document = {{ getElementById(id) {{ return els[id] || (els[id] = {{ id, innerHTML: "", hidden: true }}); }},
                   addEventListener() {{}} }};
function playerAccolades() {{ return {json.dumps(_CHAMPION)}; }}
function playerTags() {{ return {json.dumps(_TAGS)}; }}
{_fn_source(cards, "_renderRevealTags")}
{_fn_source(cards, "_showRevealTags")}
_renderRevealTags({{player_id: 7}}, false);
const written = Object.fromEntries(Object.entries(els).map(([k, v]) => [k, v.innerHTML]));
""")
        assert set(out["written"]) == {"revealTags"}
        for html in out["written"].values():
            assert html
            assert not {"card-pips", "card-tag-pips", "accolade-pips", "tag-pips"} & set(_classes(html))
        assert out["calls"] == 0
        assert "revealPips" not in _fe("index.html") and "revealPips" not in cards

    def test_no_frontend_file_renders_card_pips_classes(self):
        """No frontend/*.js or index.html contains the class names `card-pips` or
        `card-tag-pips` (failure path: a leftover overlay on any card face, collection
        or Weekly Report markup)."""
        pat = re.compile(r"\bcard-(?:tag-)?pips\b")
        frontend = os.path.join(_ROOT, "frontend")
        names = [n for n in os.listdir(frontend) if n.endswith(".js")] + ["index.html"]
        offenders = [n for n in sorted(names) if pat.search(_fe(n))]
        assert offenders == []

    def test_card_pips_html_removed(self):
        """`cardPipsHtml` is not defined in app-globals.js and not referenced in any
        frontend file."""
        frontend = os.path.join(_ROOT, "frontend")
        for n in os.listdir(frontend):
            if n.endswith((".js", ".html")):
                assert "cardPipsHtml" not in _fe(n), n

    def test_card_face_pip_css_removed(self):
        """style.css has no rule whose selector mentions .card-pips or .card-tag-pips,
        and no #218 container-unit pip sizing (no `cqw`/`cqi` units in pip rules, no
        container-type on card wrappers added for pips)."""
        css = _fe("style.css")
        assert _css_blocks(css, r"\.card-(?:tag-)?pips\b") == []
        assert not re.search(r"\bcard-(?:tag-)?pips\b", css)
        assert not re.search(r"\d(?:cqw|cqi)\b", css)
        assert "container-type" not in css and "--card-u" not in css
        for sel in (".card-slot", ".reveal-img-wrap", ".draw-landing"):
            for body in _rule(css, sel):
                assert "container" not in body, sel

    def test_player_popup_header_keeps_tag_and_accolade_pips(self):
        """app-player-popup.js still fills its header pips with tagPipsHtml(tags) followed
        by accoladePipsHtml(list)."""
        fn = _fn_body(_fe("app-player-popup.js"), "renderPlayerAccolades")
        assert "tagPipsHtml(tags)" in fn
        assert "pipsEl.innerHTML = tagPips + accoladePipsHtml(list)" in fn

    def test_other_views_keep_accolade_pips(self):
        """accoladePipsHtml stays defined in app-globals.js and is still called in the
        Players list (app-players.js players-titles), the Teams tab (teams-titles), the
        team popup (app-team-popup.js) and the Hall of fame (app-history.js); tagPipsHtml
        stays defined and used in the player popup header."""
        g = _fe("app-globals.js")
        assert "function accoladePipsHtml(" in g and "function tagPipsHtml(" in g
        players = _fe("app-players.js")
        assert '<td class="players-titles">${accoladePipsHtml(' in players
        teams_cell = players[players.index('class="teams-titles"'):]
        assert "accoladePipsHtml(" in teams_cell[:teams_cell.index("</td>")]
        assert "accoladePipsHtml(" in _fe("app-team-popup.js")
        assert "accoladePipsHtml(f.accolades" in _fe("app-history.js")
        assert "tagPipsHtml(tags)" in _fe("app-player-popup.js")


# ---------------------------------------------------------------------------
# Story 3: Accolade and Tag Details in the Card Popup
# ---------------------------------------------------------------------------

class TestTagDetailsHtml:

    def test_tag_details_html_orders_admin_caster_then_label(self):
        """Node harness: tagDetailsHtml([generic 'Veteran', caster, admin, generic 'Analyst'])
        yields one line per tag in TAG_SYMBOLS order: 'Kana Cards admin', 'Caster', then
        'Analyst', 'Veteran' by label; each line has its symbol (aria-hidden) and text."""
        tags = [{"key": "veteran", "label": "Veteran"}, {"key": "caster", "label": "Caster"},
                {"key": "admin", "label": "Admin"}, {"key": "analyst", "label": "Analyst"}]
        html = _node_out(f"tagDetailsHtml({json.dumps(tags)})")
        parsed = _parse(html)
        assert [s["title"] for s in parsed.sections] == ["Tags"]
        assert [ln["text"] for ln in parsed.lines] == ["Kana Cards admin", "Caster", "Analyst", "Veteran"]
        assert [ln["icon"] for ln in parsed.lines] == ["shield", "mic", "tag", "tag"]
        for ln, variant in zip(parsed.lines, ("admin", "caster", "generic", "generic")):
            assert ln["aria_hidden"] == "true"
            assert "card-tag-pip" in ln["symbol"] and f"card-tag-pip--{variant}" in ln["symbol"]

    def test_tag_details_html_escapes_labels(self):
        """A generic tag label containing `<b>&` is rendered escaped (text, not markup)."""
        html = _node_out('tagDetailsHtml([{key: "x", label: "<b>&"}])')
        assert "<b>" not in html and "&lt;b&gt;&amp;" in html
        assert [ln["text"] for ln in _parse(html).lines] == ["<b>&"]

    def test_tag_details_html_never_renders_season_winner(self):
        """A season_winner tag in the input produces no line."""
        html = _node_out('tagDetailsHtml([{key: "season_winner", label: "Season Winner"}, {key: "caster", label: "Caster"}])')
        assert [ln["text"] for ln in _parse(html).lines] == ["Caster"]
        assert "Season Winner" not in html and "season_winner" not in html

    def test_tag_details_html_empty_input_returns_empty_string(self):
        """tagDetailsHtml([]), tagDetailsHtml(undefined) and a list holding only
        season_winner return '' (no heading, no empty container)."""
        out = _node_out('[tagDetailsHtml([]), tagDetailsHtml(undefined), tagDetailsHtml(null), '
                        'tagDetailsHtml([{key: "season_winner", label: "Season Winner"}])]')
        assert out == ["", "", "", ""]

    def test_tag_details_html_shows_no_user_identity(self):
        """The output contains no user id, username or email even when the tag objects
        carry extra fields; only key-derived symbols and labels are used."""
        tags = [{"key": "caster", "label": "Caster", "user_id": 31337, "username": "secretname",
                 "email": "who@example.com"},
                {"key": "vip", "label": "VIP", "user_id": 31337, "username": "secretname"}]
        html = _node_out(f"tagDetailsHtml({json.dumps(tags)})")
        for leak in ("31337", "secretname", "who@example.com"):
            assert leak not in html
        assert [ln["text"] for ln in _parse(html).lines] == ["Caster", "VIP"]


def _details(acc):
    """Issue 230: the accolade detail lines as the player popup builds them, newest first,
    then the Played summary (accoladeDetailsHtml's lines before issue 230)."""
    return _node_out(f"(l => l.slice().sort(_accoladeNewestFirst).map(accoladeDetailLine).join('') "
                     f"+ accoladePlayedLine(l))({json.dumps(acc)})")


class TestAccoladeDetailLines:

    def test_accolade_detail_lines_newest_season_first_champions_first(self):
        """Node harness: accolades across S14 and S15, mixing champion and point-based
        kinds, render newest season first and, within a season, champion lines before
        the others."""
        acc = [_a("best_match", "Season 14", value=99.0), _a("most_points", "Season 15", value=812.3),
               _a("champion", "Season 14", "div2", "Old Team"), _a("champion", "Season 15", "div1", "Team Name"),
               _a("best_average", "Season 15", value=40.25)]
        parsed = _parse(_details(acc))
        assert [ln["text"] for ln in parsed.lines] == [
            "S15 Div 1 Champion · with Team Name",
            "S15 Most Points · 812.3 pts",
            "S15 Best Average · 40.3 pts",
            "S14 Div 2 Champion · with Old Team",
            "S14 Best Single Match · 99.0 pts",
        ]

    def test_accolade_detail_line_champion_names_division_and_team(self):
        """A season-15 Div 1 champion accolade with team_name 'Team Name' renders the text
        'S15 Div 1 Champion · with Team Name' (team name escaped)."""
        acc = [_a("champion", "Season 15", "div1", "Team Name")]
        assert [ln["text"] for ln in _parse(_details(acc)).lines] == ["S15 Div 1 Champion · with Team Name"]
        evil = [_a("champion", "Season 15", "div1", "<img src=x>&Co")]
        html = _details(evil)
        assert "<img" not in html and "&lt;img src=x&gt;&amp;Co" in html
        assert [ln["text"] for ln in _parse(html).lines] == ["S15 Div 1 Champion · with <img src=x>&Co"]

    def test_accolade_detail_line_point_accolade_shows_value(self):
        """A season-15 Most Points accolade with value 812.3 renders
        'S15 Most Points · 812.3 pts'; Best Average, Best Single Match and a valued
        Fantasy Winner follow the same pattern; a Fantasy Winner without value shows no
        ' · … pts' suffix."""
        cases = [
            (_a("most_points", "Season 15", value=812.3), "S15 Most Points · 812.3 pts"),
            (_a("best_average", "Season 15", value=41.0), "S15 Best Average · 41.0 pts"),
            (_a("best_match", "Season 15", value=77.75), "S15 Best Single Match · 77.8 pts"),
            (_a("fantasy_winner", "Season 15", value=1500.0), "S15 Fantasy Winner · 1500.0 pts"),
            (_a("fantasy_winner", "Season 14"), "S14 Fantasy Winner"),
        ]
        for acc, text in cases:
            lines = _parse(_details([acc])).lines
            assert [ln["text"] for ln in lines] == [text]

    def test_accolade_played_line_summary_with_disclosure(self):
        """Played rows for seven seasons S4..S16 render one summary line
        'Played 7 seasons · S4–S16' (counted from Season 4, as #212) and a
        <details> disclosure listing each season; played rows before S4 are not counted."""
        seasons = [2, 3, 4, 5, 6, 10, 14, 15, 16]
        acc = [_a("played", f"Season {n}") for n in seasons]
        parsed = _parse(_details(acc))
        assert len(parsed.lines) == 1
        line = parsed.lines[0]
        assert line["details"] is True
        assert line["summary"] == "Played 7 seasons · S4–S16"
        assert line["seasons"] == ["S16", "S15", "S14", "S10", "S6", "S5", "S4"]
        assert line["icon"] == "calendar-check" and "accolade-pip--played" in line["symbol"]
        one = _parse(_details([_a("played", "Season 15")])).lines
        assert one[0]["summary"] == "Played 1 season · S15"
        assert _details([_a("played", "Season 3")]) == ""
        mixed = _parse(_details(acc + [_a("champion", "Season 15", "div1", "T")])).lines
        assert [ln["details"] for ln in mixed] == [False, True]  # Played comes last

    def test_accolade_detail_lines_use_kind_symbol_and_plate_colour(self):
        """Each line carries the symbol and plate colour of its kind from ACCOLADE_KINDS
        (same class/token as accoladePipsHtml); the symbol is aria-hidden and the text
        carries the meaning."""
        kinds = _node_out("ACCOLADE_KINDS")
        acc = [_a("champion", "Season 15", "div1", "A"), _a("champion", "Season 15", "div2", "B"),
               _a("most_points", "Season 15", value=1), _a("best_average", "Season 15", value=1),
               _a("best_match", "Season 15", value=1), _a("fantasy_winner", "Season 15", value=1),
               _a("played", "Season 15")]
        # Issue 233: runner-up and third place per division sit after the champions.
        acc[2:2] = [_a("runner_up", "Season 15", "div1", "C"), _a("runner_up", "Season 15", "div2", "D"),
                    _a("third_place", "Season 15", "div1", "E"), _a("third_place", "Season 15", "div2", "F")]
        lines = _parse(_details(acc)).lines
        assert len(lines) == len(kinds) == 11
        for ln, kind in zip(lines, kinds):
            assert ln["icon"] == kind["icon"]
            assert "accolade-pip" in ln["symbol"]
            assert f"accolade-pip--{kind['plate']}" in ln["symbol"]
            assert f"accolade-pip--{kind['key']}" in ln["symbol"]
            assert ln["aria_hidden"] == "true"
            assert kind["name"] in ln["text"]
        # The plate colour comes from the same CSS rule as the pips.
        css = _fe("style.css")
        assert "var(--accolade-div1)" in _rule(css, ".accolade-pip--div1")[0]

    def test_accolade_detail_lines_empty_input_return_empty_string(self):
        """accoladeDetailLine and accoladePlayedLine return '' for missing, played-only
        (the line helper) or unknown input."""
        out = _node_out('[accoladeDetailLine(undefined), accoladeDetailLine(null), '
                        'accoladeDetailLine({kind: "unknown", season: "Season 15"}), '
                        'accoladeDetailLine({kind: "played", season: "Season 15"}), '
                        'accoladePlayedLine([]), accoladePlayedLine(undefined), accoladePlayedLine(null)]')
        assert out == ["", "", "", "", "", "", ""]
        assert "accoladeDetailsHtml" not in _fe("app-globals.js")


class TestCardViewerSections:

    def test_index_html_card_viewer_has_tags_section(self):
        """#revealModal in index.html (parsed with html.parser) holds a Tags section
        container below the card; since issue 230 there is no Accolades section."""
        p = _ids(_reveal_modal_html())
        ids = p.ids
        assert ids[0] == "revealModal"
        assert "revealPips" not in ids and "revealAccolades" not in ids
        assert ids.index("revealImgWrap") < ids.index("revealTags") < ids.index("revealActionBtn")
        attrs = p.attrs["revealTags"]
        assert "reveal-details" in attrs.get("class", "").split()
        assert "hidden" in attrs  # empty until a card fills it

    def test_card_viewer_shows_tags_for_tagged_champion(self):
        """Node harness: opening a card (showCard, not a draw) for a champion with tags
        fills the Tags section from tagDetailsHtml and shows it; the accolades are not
        listed (issue 230 moved them to the player popup)."""
        out = _run_draw(f"""
  (0, eval)({json.dumps(_globals_js().replace("function _escHtml", "function _escHtmlUnused"))});
  globalThis.playerAccolades = () => {json.dumps(_CHAMPION)};
  globalThis.playerTags = () => {json.dumps(_TAGS)};
  showCard({{id: 3, card_type: "legendary", player_id: 7, player_name: "Glete", team_name: "Greens"}}, "");
  const tags = document.getElementById("revealTags");
  out.tagsHidden = tags.hidden;
  out.tags = tags.innerHTML;
  out.expectedTags = tagDetailsHtml(playerTags(7));
  out.ids = Object.keys(els);
""")
        assert out["tagsHidden"] is False
        assert out["tags"] == out["expectedTags"]
        assert [ln["text"] for ln in _parse(out["tags"]).lines] == ["Kana Cards admin", "Caster"]
        assert "revealAccolades" not in out["ids"]

    def test_card_viewer_hides_tags_when_player_has_none(self):
        """Node harness: a player with no tags leaves the Tags section hidden (hidden
        attribute) and empty, so no empty space shows."""
        out = _run_draw(f"""
  (0, eval)({json.dumps(_globals_js().replace("function _escHtml", "function _escHtmlUnused"))});
  globalThis.playerAccolades = () => [];
  globalThis.playerTags = () => [];
  // A previous card left content behind; the next card must clear it.
  document.getElementById("revealTags").innerHTML = "old";
  showCard({{id: 3, card_type: "common", player_id: 8, player_name: "Nobody", team_name: "T"}}, "");
  const tags = document.getElementById("revealTags");
  out.state = [tags.hidden, tags.innerHTML];
  showCard({{id: 4, card_type: "common", player_name: "No player id"}}, "");
  out.noPlayer = [tags.hidden, tags.innerHTML];
""")
        assert out["state"] == [True, ""]
        assert out["noPlayer"] == [True, ""]

    def test_draw_reveal_hides_tags_until_flip_finishes(self):
        """Using test_issue_205's _HARNESS/_run: during a draw of a tagged player's card
        the Tags section stays hidden while the flip animation runs and becomes visible
        only after the flip has finished (and immediately under reduced motion)."""
        steps = f"""
  (0, eval)({json.dumps(_globals_js().replace("function _escHtml", "function _escHtmlUnused"))});
  globalThis.playerAccolades = () => {json.dumps(_CHAMPION)};
  globalThis.playerTags = () => {json.dumps(_TAGS)};
  const tags = document.getElementById("revealTags");
  tags.hidden = true;
  const visible = () => !tags.hidden;
  drawCard();
  out.firstVisible = null; out.firstShown = null; out.visibleWhileEntering = false;
  for (let i = 0; i < 400; i++) {{
    await advance(10);
    if (out.firstShown === null && shown()) out.firstShown = NOW;
    if (visible() && modal().classList.contains("reveal-overlay--entering")) out.visibleWhileEntering = true;
    if (visible() && out.firstVisible === null) out.firstVisible = NOW;
  }}
  const flip = ANIMS.find(a => JSON.stringify(a.keyframes).includes("rotateY"));
  out.flipEnd = flip ? flip.at + flip.opts.duration : null;
  out.finalVisible = visible();
  out.filled = Boolean(tags.innerHTML);
"""
        out = _run_draw(steps)
        assert out["filled"] is True and out["finalVisible"] is True
        assert out["flipEnd"] is not None
        assert out["visibleWhileEntering"] is False
        assert out["firstShown"] < out["flipEnd"] <= out["firstVisible"]
        reduced = _run_draw(steps, reduced=True)
        assert reduced["flipEnd"] is None
        assert reduced["finalVisible"] is True and reduced["visibleWhileEntering"] is False
        assert reduced["firstVisible"] == reduced["firstShown"]


# ---------------------------------------------------------------------------
# Step 4: CSS placement and tokens
# ---------------------------------------------------------------------------

class TestDetailsCss:

    def test_details_css_before_guided_tour_and_tokens_only(self):
        """The Tags and Accolades section rules in style.css appear before the
        'GUIDED TOUR (issue #144)' header and use colour tokens (var(--...)) only:
        no hex, rgb() or rgba() literals."""
        css = _fe("style.css")
        rules = _details_rules(css)
        selectors = {sel for sel, _ in rules}
        for wanted in (".reveal-details", ".card-details-title", ".card-details-list", ".card-detail",
                       ".card-detail-seasons"):
            assert wanted in selectors, wanted
        tour = css.index("GUIDED TOUR (issue #144)")
        assert max(m.start() for m in re.finditer(_DETAILS_CSS, css)) < tour
        for sel, body in rules:
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", body), sel
            for prop in ("color", "background", "border-color"):
                for m in re.finditer(rf"(?<![-\w]){prop}:\s*([^;]+);", body):
                    assert m.group(1).strip().startswith("var(--"), (sel, prop)
        assert "issue 228" in css and "#228" not in css

    def test_details_css_wraps_at_phone_width(self):
        """The section rules allow wrapping (flex-wrap: wrap or block flow, no
        white-space: nowrap, no fixed width wider than 343px), so the section has no
        sideways scroll at phone width."""
        css = _fe("style.css")
        rules = _details_rules(css)
        for sel, body in rules:
            assert "nowrap" not in body, sel
            for m in re.finditer(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", body):
                assert int(m.group(1)) <= 343, sel
        assert "flex-wrap: wrap" in _rule(css, ".card-detail-seasons")[0]
        assert "overflow-wrap: anywhere" in _rule(css, ".card-detail-text")[0]
        assert "min-width: 0" in _rule(css, ".card-detail")[0]
        assert "max-width: 280px" in _rule(css, ".reveal-details")[0]
