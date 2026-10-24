"""Tests for Card Formatting (plan-issue-218-card-formatting.md).

Chosen layout: A · Classic TCG on the 597 x 845 card. Name bar with the card
number, a 368 x 368 portrait slot between two pillars (rarity gems and the #221
rank medal slot on the left, up to 4 accolade discs on the right, "+N" in the
fourth place on overflow), a type line with a 100 x 60 logo slot, and a cream
rules box with up to 3 modifier lines and the accolade names at its foot.

Covers the stories:
  - Choose a New Card Layout (done on the design canvas; one check that the
    plan records the chosen layout)
  - Accolades Have Their Own Place on the Card
  - Card Reads at Every Size (including the rank medal from #221 Step 6)
  - See Accolade Names in the Card Viewer

"Counted Accolades" is not yet implemented and has no stubs.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib.util
import json
import subprocess
import time

import pytest

import models  # noqa: F401  -- register all tables before the db fixture runs
import image
from models import Card, Player, PlayerMatchStats, TagDefinition, Team, User, UserTag
from routers import cards as cards_router
from scoring import STAT_LABELS
from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _fn_body, _read
from tests.test_issue_159_flicker_free_tab_switching import _node

if not image.PIL_AVAILABLE:
    pytest.skip("Pillow not installed", allow_module_level=True)

from PIL import Image, ImageChops, ImageOps  # noqa: E402

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PLAN = os.path.join(_REPO, "markdown", "plans", "plan-issue-218-card-formatting.md")
_GENERATOR = os.path.join(_REPO, "backend", "scripts", "make_card_templates.py")
_APP_CARDS = os.path.join(_REPO, "frontend", "app-cards.js")
_INDEX = os.path.join(_REPO, "frontend", "index.html")
_STYLE = os.path.join(_REPO, "frontend", "style.css")


def _blank():
    return Image.new("RGBA", image._CARD_SIZE, (0, 0, 0, 0))


def _inside(bbox, box):
    return bbox[0] >= box[0] and bbox[1] >= box[1] and bbox[2] <= box[2] and bbox[3] <= box[3]


def _texts(monkeypatch):
    """Record every text image._draw_text draws, as (xy, text)."""
    seen = []
    real = image._draw_text

    def spy(draw, xy, text, *a, **kw):
        seen.append((xy, text))
        return real(draw, xy, text, *a, **kw)

    monkeypatch.setattr(image, "_draw_text", spy)
    return seen


def _render(**kw):
    args = dict(card_type="rare", player_name="Player One", avatar_url=None,
                team_name="No Such Team 218", team_logo_url=None)
    args.update(kw)
    return image.generate_card_image(**args)


def _sticker_dir(tmp_path, monkeypatch, **colours):
    d = tmp_path / "stickers"
    d.mkdir()
    for key, colour in colours.items():
        Image.new("RGBA", (60, 60), colour).save(d / f"{key}.png")
    monkeypatch.setattr(image, "STICKER_DIR", str(d))
    return d


def _accs(n):
    return [{"key": f"nosticker_{i}", "label": f"Tag{i}"} for i in range(n)]


def _seed(db, player_id=11, tags=(), link=True, rank=(None, None)):
    """Owner user 1, a player (optionally linked to user 2 holding `tags`) and an active card."""
    db.add(User(id=1, username="owner", tokens=5))
    db.add(Team(id=7, name="Team Seven"))
    db.add(Player(id=player_id, name="Linked", is_active=True,
                  rank_tier=rank[0], leaderboard_rank=rank[1]))
    db.flush()
    if link:
        db.add(User(id=2, username="pro", tokens=0, player_id=player_id))
        db.flush()
        for key, label in tags:
            td = TagDefinition(key=key, label=label, created_at=int(time.time()))
            db.add(td)
            db.flush()
            db.add(UserTag(user_id=2, tag_id=td.id, granted_at=int(time.time())))
            db.flush()
    db.add(PlayerMatchStats(player_id=player_id, match_id=1, team_id=7, fantasy_points=10.0))
    card = Card(card_type="rare", player_id=player_id, owner_id=1, is_active=True,
                slot_index=0, generation=1)
    db.add(card)
    db.commit()
    return card


def _capture_generate(monkeypatch):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return Image.new("RGB", (2, 2))

    monkeypatch.setattr(image, "generate_card_image", fake)
    return seen


# ===========================================================================
# Story: Choose a New Card Layout
# ===========================================================================

class TestChooseNewCardLayout:

    def test_plan_records_chosen_layout(self):
        """AC: the chosen layout (A · Classic TCG) is written into the plan before implementation."""
        assert "Chosen layout: **A · Classic TCG**" in _read(_PLAN)


# ===========================================================================
# Story: Accolades Have Their Own Place on the Card
# ===========================================================================

class TestAccoladesHaveTheirOwnPlace:

    @pytest.mark.parametrize("rarity", ["common", "rare", "epic", "legendary"])
    @pytest.mark.parametrize("n_mods", [0, 1, 2, 3])
    @pytest.mark.parametrize("n_accolades", [0, 1, 3, 5])
    def test_generate_card_image_renders_every_rarity_modifier_and_accolade_count(
        self, rarity, n_mods, n_accolades
    ):
        """AC: each rarity renders with 0-3 modifiers and 0, 1, 3 and 5 accolades without error at 597 x 845."""
        mods = {k: 10 for k in sorted(STAT_LABELS)[:n_mods]}
        img = _render(card_type=rarity, card_modifiers=mods, accolades=_accs(n_accolades), card_id=5)
        assert img.size == (597, 845)
        assert img.mode == "RGBA"

    def test_draw_accolades_draws_discs_in_right_pillar_only(self):
        """AC: accolades are drawn in the right pillar, never over the name bar, portrait, logo or frame."""
        for n in (1, 3, 4, 7):
            out = image._draw_accolades(_blank(), _accs(n))
            bbox = out.getchannel("A").getbbox()
            assert bbox is not None and _inside(bbox, image._RIGHT_PILLAR), (n, bbox)

    def test_draw_accolades_uses_sticker_icon_for_each_tag(self, tmp_path, monkeypatch):
        """AC: every tag of the linked user is drawn with its own sticker icon from assets/stickers/{key}.png."""
        _sticker_dir(tmp_path, monkeypatch, red=(255, 0, 0, 255), blue=(0, 0, 255, 255))
        out = image._draw_accolades(_blank(), [{"key": "red", "label": "Red"}, {"key": "blue", "label": "Blue"}])
        c1, c2 = image._accolade_centres(2)
        assert out.getpixel(c1) == (255, 0, 0, 255)
        assert out.getpixel(c2) == (0, 0, 255, 255)
        assert image.STICKER_DIR.endswith("stickers")

    def test_draw_accolades_overflow_draws_plus_n_in_fourth_place(self, monkeypatch):
        """AC: past the layout maximum (4 in A), the fourth place shows "+N" for the remaining accolades."""
        seen = _texts(monkeypatch)
        image._draw_accolades(_blank(), _accs(6))
        centres = image._accolade_centres(4)
        assert [t for _, t in seen] == ["T", "T", "T", "+3"]
        assert seen[-1][0] == centres[3]

    def test_draw_accolades_exactly_max_draws_no_plus_n(self, monkeypatch):
        """AC: exactly 4 accolades fill the four places with no "+N" badge."""
        seen = _texts(monkeypatch)
        out = image._draw_accolades(_blank(), _accs(4))
        assert len(seen) == 4 and not any(t.startswith("+") for _, t in seen)
        for c in image._accolade_centres(4):
            assert out.getpixel(c)[3] == 255

    def test_draw_accolades_empty_list_leaves_pillar_clean(self):
        """AC: a card with no accolades shows layout A's empty state (no discs, no broken-looking gap)."""
        base = Image.new("RGBA", image._CARD_SIZE, (30, 30, 30, 255))
        before = base.copy()
        image._draw_accolades(base, [])
        image._draw_accolades(base, None)
        assert ImageChops.difference(before, base).getbbox(alpha_only=False) is None
        a = _render(accolades=[])
        b = _render()
        assert ImageChops.difference(a, b).getbbox(alpha_only=False) is None

    def test_draw_accolades_new_tag_with_sticker_appears_without_code_change(self, tmp_path, monkeypatch):
        """AC: a new tag key whose sticker file exists is drawn with no code change."""
        _sticker_dir(tmp_path, monkeypatch, brand_new_tag=(0, 200, 0, 255))
        assert "brand_new_tag" not in image._ACCOLADE_COLORS
        out = image._draw_accolades(_blank(), [{"key": "brand_new_tag", "label": "Brand New"}])
        assert out.getpixel(image._accolade_centres(1)[0]) == (0, 200, 0, 255)

    def test_draw_accolades_missing_sticker_falls_back_to_letter_badge(self, tmp_path, monkeypatch):
        """AC: a tag without a sticker file shows a generic badge with the label's first letter."""
        _sticker_dir(tmp_path, monkeypatch)
        seen = _texts(monkeypatch)
        out = image._draw_accolades(_blank(), [{"key": "mvp", "label": "match MVP"}])
        centre = image._accolade_centres(1)[0]
        assert seen == [(centre, "M")]
        assert out.getpixel((centre[0], centre[1] - image._ACCOLADE_DISC // 2 + 1))[3] == 255

    def test_draw_accolades_sticker_path_outside_sticker_folder_ignored(self, tmp_path, monkeypatch):
        """Failure path: a tag key that resolves outside assets/stickers (e.g. '../x') loads no file."""
        _sticker_dir(tmp_path, monkeypatch)
        Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(tmp_path / "evil.png")
        opened = []
        real_open = image.Image.open
        monkeypatch.setattr(image.Image, "open",
                            lambda p, *a, **kw: opened.append(str(p)) or real_open(p, *a, **kw))
        seen = _texts(monkeypatch)
        out = image._draw_accolades(_blank(), [{"key": "../evil", "label": "Evil"}])
        assert opened == []
        assert [t for _, t in seen] == ["E"]
        assert out.getpixel(image._accolade_centres(1)[0]) != (0, 0, 255, 255)

    def test_card_image_route_passes_accolades_in_user_tag_order(self, db, monkeypatch):
        """AC: GET /cards/{id}/image resolves {key, label} pairs from the linked user's tags, in tag order."""
        card = _seed(db, tags=[("season_winner", "Season Winner"), ("caster", "Caster")])
        seen = _capture_generate(monkeypatch)
        cards_router.get_card_image(card.id, db=db)
        assert seen["accolades"] == [{"key": "season_winner", "label": "Season Winner"},
                                     {"key": "caster", "label": "Caster"}]
        assert seen["card_id"] == card.id

    def test_card_image_route_player_without_linked_user_has_no_accolades(self, db, monkeypatch):
        """Failure path: a card whose player has no linked user renders with an empty accolade list."""
        card = _seed(db, link=False)
        seen = _capture_generate(monkeypatch)
        cards_router.get_card_image(card.id, db=db)
        assert seen["accolades"] == []


# ===========================================================================
# Story: Card Reads at Every Size
# ===========================================================================

def _quadrants(size, colours):
    w, h = size
    img = Image.new("RGBA", size)
    for (x0, y0), c in zip([(0, 0), (w // 2, 0), (0, h // 2), (w // 2, h // 2)], colours):
        img.paste(c, (x0, y0, x0 + w // 2, y0 + h // 2))
    return img


_Q = [(250, 0, 0, 255), (0, 250, 0, 255), (0, 0, 250, 255), (250, 250, 0, 255)]


def _corner_pixels(img, slot):
    x0, y0, x1, y1 = slot
    return [img.getpixel(p) for p in [(x0, y0), (x1 - 1, y0), (x0, y1 - 1), (x1 - 1, y1 - 1)]]


class TestCardReadsAtEverySize:

    def test_generate_card_image_canvas_is_597_by_845(self):
        """AC: the portrait card stays 597 x 845 so roster and draw-animation aspect ratios hold."""
        assert image._CARD_SIZE == (597, 845)
        for rarity in ("common", "legendary"):
            assert _render(card_type=rarity).size == (597, 845)

    def test_portrait_slot_is_368_square(self):
        """AC: _PORTRAIT_SLOT is 368 x 368 (2x the 184 px avatar)."""
        assert image._slot_size(image._PORTRAIT_SLOT) == (368, 368)

    def test_logo_slot_is_100_by_60(self):
        """AC: _LOGO_SLOT is 100 x 60 (0.4x the 250 x 150 Dotabuff logo, 5:3)."""
        assert image._slot_size(image._LOGO_SLOT) == (100, 60)

    def test_avatar_184_fills_portrait_slot_exactly(self, monkeypatch):
        """AC: a 184 x 184 avatar fills the portrait slot exactly with no crop, stretch or filler."""
        avatar = _quadrants((184, 184), _Q)
        monkeypatch.setattr(image, "_fetch_pil_image", lambda url, size=None: avatar.copy())
        img = _render(card_type="common", avatar_url="https://avatars.example/a.jpg")
        assert _corner_pixels(img, image._PORTRAIT_SLOT) == _Q
        x0, y0, x1, y1 = image._PORTRAIT_SLOT
        frame = image._RARITY_COLORS["common"] + (255,)
        assert img.getpixel((x0 - 1, y0 + 10)) == frame
        assert img.getpixel((x1, y1 - 10)) == frame

    def test_logo_250x150_fills_logo_slot_exactly(self, tmp_path, monkeypatch):
        """AC: a 250 x 150 cached logo fills the logo slot exactly, keeping its 5:3 shape (no circle crop)."""
        path = tmp_path / "Team.png"
        _quadrants((250, 150), _Q).save(path)
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda d, name: str(path))
        logo = image._load_team_logo_for_card("Team", None, image._slot_size(image._LOGO_SLOT))
        assert logo.size == (100, 60)
        img = _render(card_type="common", team_name="Team")
        assert _corner_pixels(img, image._LOGO_SLOT) == _Q

    @pytest.mark.parametrize("size", [(200, 200), (100, 300)])
    def test_fallback_logo_square_or_tall_fits_inside_slot_without_stretch(self, size, monkeypatch):
        """Failure path: a square or tall fallback logo from logo_url is contained in the slot, centred, not stretched."""
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda d, name: None)
        monkeypatch.setattr(image, "_fetch_pil_image", lambda url, s=None: Image.new("RGBA", size, (250, 0, 0, 255)))
        logo = image._load_team_logo_for_card("X", "https://steamcdn-a.akamaihd.net/x.png", (100, 60))
        assert logo.size == (100, 60)
        fw, fh = ImageOps.contain(Image.new("RGBA", size), (100, 60)).size
        assert fw / fh == pytest.approx(size[0] / size[1], rel=0.05)
        red = logo.getchannel("G").point(lambda v: 255 if v == 0 else 0)
        red = ImageChops.multiply(red, logo.getchannel("R").point(lambda v: 255 if v > 200 else 0))
        assert red.getbbox() == ((100 - fw) // 2, (60 - fh) // 2, (100 - fw) // 2 + fw, (60 - fh) // 2 + fh)
        assert logo.getpixel((0, 30)) == image._LOGO_PLATE

    def test_card_templates_have_transparent_cutouts_at_slots(self):
        """AC: each Card_Template_<Rarity>.png is 597 x 845 RGBA with transparent cutouts at the portrait and logo slots."""
        for rarity, name in image._CARD_TEMPLATES.items():
            tpl = Image.open(os.path.join(image._ASSETS_DIR, name))
            assert tpl.size == (597, 845) and tpl.mode == "RGBA", name
            for slot in (image._PORTRAIT_SLOT, image._LOGO_SLOT):
                assert tpl.crop(slot).getchannel("A").getextrema() == (0, 0), (name, slot)
                x0, y0, x1, y1 = slot
                assert tpl.getpixel((x0 - 1, (y0 + y1) // 2))[3] == 255
                assert tpl.getpixel((x1, (y0 + y1) // 2))[3] == 255
                assert tpl.getpixel(((x0 + x1) // 2, y1))[3] == 255

    def test_card_template_generator_script_exists(self):
        """AC: templates are drawn by a generator script in the repo so they can be rebuilt."""
        assert os.path.isfile(_GENERATOR)
        spec = importlib.util.spec_from_file_location("make_card_templates", _GENERATOR)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for rarity, name in image._CARD_TEMPLATES.items():
            drawn = mod.draw_template(rarity)
            committed = Image.open(os.path.join(image._ASSETS_DIR, name)).convert("RGBA")
            assert ImageChops.difference(drawn, committed).getbbox(alpha_only=False) is None, name

    def test_rarity_gem_count_differs_by_rarity(self):
        """AC: rarity is told by more than colour: 1/2/3/4 gems for common/rare/epic/legendary."""
        for rarity, n in (("common", 1), ("rare", 2), ("epic", 3), ("legendary", 4)):
            out = _blank()
            centres = image._draw_rarity_gems(out, rarity)
            assert len(centres) == n
            assert _inside(out.getchannel("A").getbbox(), image._LEFT_PILLAR)
            for c in centres:
                assert out.getpixel((c[0] - 6, c[1] + 4)) == image._RARITY_COLORS[rarity] + (255,)

    def test_type_line_shows_rarity_name(self, monkeypatch):
        """AC: the type line shows the rarity name as text."""
        seen = _texts(monkeypatch)
        _render(card_type="legendary")
        hits = [xy for xy, t in seen if t == "Legendary"]
        assert len(hits) == 1
        assert image._TYPE_LINE[1] <= hits[0][1] <= image._TYPE_LINE[3]

    def test_name_bar_shows_card_number(self, monkeypatch):
        """AC: the name bar shows '#' + card id on the right."""
        seen = _texts(monkeypatch)
        _render(card_id=412)
        (xy,) = [xy for xy, t in seen if t == "#412"]
        x0, y0, x1, y1 = image._NAME_BAR
        assert y0 <= xy[1] <= y1 and xy[0] > (x0 + x1) // 2
        (name_xy,) = [xy for xy, t in seen if t == "Player One"]
        assert name_xy[0] < xy[0]

    def test_legendary_card_has_foil_sheen(self, monkeypatch):
        """AC: legendary cards get a foil sheen; other rarities do not."""
        calls = []
        real = image._apply_foil_sheen
        monkeypatch.setattr(image, "_apply_foil_sheen", lambda img: calls.append(1) or real(img))
        for rarity in ("common", "rare", "epic"):
            _render(card_type=rarity)
        assert calls == []
        _render(card_type="legendary")
        assert calls == [1]
        plain = Image.new("RGBA", (597, 845), (0, 0, 0, 255))
        assert ImageChops.difference(real(plain.copy()), plain).getbbox(alpha_only=False) is not None

    def test_name_and_modifier_values_readable_at_180px(self):
        """AC: at 180 px wide the name, rarity and modifier values use fonts large enough to read."""
        scale = 180 / image._CARD_SIZE[0]
        assert image._NAME_FONT_MIN * scale >= 9
        assert image._NAME_FONT_SIZE * scale >= 12
        assert image._MODIFIER_FONT_SIZE * scale >= 10
        assert image._RARITY_FONT_SIZE * scale >= 8
        assert image._MAX_MODIFIER_LINES == 3

    def test_unknown_card_type_does_not_crash_renderer(self, monkeypatch):
        """Failure path: an unknown rarity string falls back to a default template instead of raising."""
        seen = _texts(monkeypatch)
        img = _render(card_type="mythic")
        assert img.size == (597, 845)
        assert "Common" in [t for _, t in seen]
        assert _render(card_type=None).size == (597, 845)

    def test_generate_card_image_draws_rank_medal_when_rank_tier_set(self, monkeypatch):
        """AC (#221): with rank_tier set, _draw_rank_medal draws the medal in the left-pillar rank slot."""
        seen = _texts(monkeypatch)
        ranked = _render(rank_tier=54)
        unranked = _render()
        diff = ImageChops.difference(ranked, unranked).getbbox(alpha_only=False)
        assert diff is not None and _inside(diff, image._RANK_SLOT)
        assert "LEGEND" in [t for _, t in seen]
        medal = image._MEDAL_COLORS["Legend"] + (255,)
        cx = (image._RANK_SLOT[0] + image._RANK_SLOT[2]) // 2
        assert ranked.getpixel((cx, image._RANK_SLOT[1] + 14)) == medal

    def test_generate_card_image_immortal_rank_medal_shows_leaderboard_place(self, monkeypatch):
        """AC (#221): an Immortal rank with a leaderboard place draws 'Immortal #N' in the rank slot."""
        seen = _texts(monkeypatch)
        _render(rank_tier=80, leaderboard_rank=55)
        texts = {t: xy for xy, t in seen}
        assert "IMMORTAL" in texts and "#55" in texts
        for t in ("IMMORTAL", "#55"):
            x, y = texts[t]
            assert image._RANK_SLOT[0] <= x <= image._RANK_SLOT[2]
            assert image._RANK_SLOT[1] <= y <= image._RANK_SLOT[3]

    def test_generate_card_image_rank_slot_empty_when_rank_tier_null(self, monkeypatch):
        """Failure path (#221): with rank_tier null, no medal is drawn and the rank slot is left empty."""
        assert image._draw_rank_medal(_blank(), None) is False
        img = _render(card_type="rare", rank_tier=None)
        tpl = Image.open(os.path.join(image._ASSETS_DIR, image._CARD_TEMPLATES["rare"])).convert("RGBA")
        slot = image._RANK_SLOT
        assert ImageChops.difference(img.crop(slot), tpl.crop(slot)).getbbox(alpha_only=False) is None

    def test_card_image_route_passes_player_rank_to_renderer(self, db, monkeypatch):
        """AC (#221): GET /cards/{id}/image passes the player's rank_tier and leaderboard_rank to the renderer."""
        card = _seed(db, rank=(80, 7))
        seen = _capture_generate(monkeypatch)
        cards_router.get_card_image(card.id, db=db)
        assert (seen["rank_tier"], seen["leaderboard_rank"]) == (80, 7)

    def test_renderer_draws_no_league_name(self, monkeypatch):
        """AC: the card is league-agnostic: image.py contains no league name or league logo."""
        for path in (image.__file__, _GENERATOR):
            src = _read(path).lower()
            assert "kanaliiga" not in src and "logo_kanaliiga" not in src
        seen = _texts(monkeypatch)
        _render(card_type="legendary", card_modifiers={"kills": 10}, accolades=_accs(2),
                card_id=3, rank_tier=54)
        assert not any("league" in t.lower() or "kanaliiga" in t.lower() for _, t in seen)


# ===========================================================================
# Story: See Accolade Names in the Card Viewer
# ===========================================================================

_CASTER = [("caster", "Caster")]


class TestAccoladeNamesInCardViewer:

    def test_roster_cards_include_accolades_with_labels(self, db):
        """AC: the My Team card list gives each card an `accolades` array of {key, label} from TagDefinition.label."""
        _seed(db, tags=[("caster", "Caster"), ("season_winner", "Season Winner")])
        out = cards_router._build_roster_response(db, 1, None)
        (card,) = out["active"] + out["bench"]
        assert card["accolades"] == [{"key": "caster", "label": "Caster"},
                                     {"key": "season_winner", "label": "Season Winner"}]

    def test_draw_reveal_card_includes_accolades(self, db):
        """AC: the draw reveal card data includes the `accolades` array."""
        db.add(User(id=1, username="drawer", tokens=3))
        db.add(Player(id=62, name="Caster Pro", is_active=True))
        db.flush()
        db.add(User(id=2, username="pro", tokens=0, player_id=62))
        td = TagDefinition(key="caster", label="Caster", created_at=1)
        db.add(td)
        db.flush()
        db.add(UserTag(user_id=2, tag_id=td.id, granted_at=1))
        db.commit()
        out = cards_router.draw_card(db=db, current_user={"user_id": 1, "username": "drawer"})
        assert out["player_id"] == 62
        assert out["accolades"] == [{"key": "caster", "label": "Caster"}]

    def test_card_viewer_data_includes_accolades(self, db):
        """AC: the card viewer data (get_card) includes the `accolades` array."""
        card = _seed(db, tags=_CASTER)
        viewer = cards_router.get_card(card.id, db=db, current_user={"user_id": 1})
        assert viewer["accolades"] == [{"key": "caster", "label": "Caster"}]

    def test_card_lists_player_without_tags_return_empty_accolades(self, db):
        """Failure path: a card whose player has no linked user or no tags returns `accolades: []`."""
        card = _seed(db, link=True, tags=())
        roster = cards_router._build_roster_response(db, 1, None)
        assert (roster["active"] + roster["bench"])[0]["accolades"] == []
        assert cards_router.get_card(card.id, db=db, current_user={"user_id": 1})["accolades"] == []
        db.query(User).filter(User.id == 2).update({"player_id": None})
        db.commit()
        assert cards_router.get_card(card.id, db=db, current_user={"user_id": 1})["accolades"] == []
        assert cards_router._accolades_for_players(db, [card.player_id]) == {}


_VIEWER_HARNESS = r"""
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
    this.attrs = {}; this.className = ""; this.textContent = ""; this.hidden = false; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  replaceChildren(...n) { this.children = []; n.forEach(c => this.appendChild(c)); }
  replaceChild(n, o) { const i = this.children.indexOf(o); this.children[i] = n; n.parentNode = this; o.parentNode = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
}
const list = new El("ul");
const document = { createElement: t => new El(t), getElementById: id => id === "revealAccolades" ? list : null };
__FNS__
const out = {};
_renderRevealAccolades({ accolades: __ACCS__ });
out.hidden = list.hidden;
out.items = list.children.map(li => ({
  icon: li.children[0].tagName, src: li.children[0].src || null, letter: li.children[0].textContent,
  label: li.children[1].textContent }));
const first = list.children[0] && list.children[0].children[0];
if (first && first.onerror) { first.onerror(); out.afterError = list.children[0].children[0].textContent; }
console.log(JSON.stringify(out));
"""


def _viewer(accolades):
    node = _node()
    if not node:
        pytest.skip("node not installed")
    js = _read(_APP_CARDS)
    fns = "\n".join(_fn_body(js, n) + "\n}\n" for n in ("_accoladeChip", "_renderRevealAccolades"))
    script = _VIEWER_HARNESS.replace("__FNS__", fns).replace("__ACCS__", json.dumps(accolades))
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


class TestAccoladeViewerFrontend:

    def test_card_viewer_lists_accolade_icon_and_label_under_image(self):
        """AC: app-cards.js lists each accolade (icon and label) under the card image in the reveal modal."""
        html = _read(_INDEX)
        assert html.index('id="revealCardImg"') < html.index('id="revealRank"') < html.index('id="revealAccolades"')
        js = _read(_APP_CARDS)
        assert "_renderRevealAccolades(card);" in _fn_body(js, "showCard")
        out = _viewer([{"key": "caster", "label": "Caster"}, {"key": "../x", "label": "odd"}])
        assert out["hidden"] is False
        assert out["items"][0] == {"icon": "IMG", "src": "/assets/stickers/caster.png",
                                   "letter": "", "label": "Caster"}
        assert out["items"][1]["icon"] == "SPAN" and out["items"][1]["letter"] == "O"
        assert out["items"][1]["label"] == "odd"
        # A sticker that fails to load becomes a letter chip.
        assert out["afterError"] == "C"

    def test_card_viewer_empty_accolades_takes_no_space(self):
        """Failure path: with no accolades the list is empty and hidden (takes no space)."""
        assert _viewer([]) == {"hidden": True, "items": []}
        assert 'id="revealAccolades" class="reveal-accolades" aria-label="Accolades" hidden' in _read(_INDEX)
        rules = dict(_css_blocks(_read(_STYLE), r"\.reveal-accolades\[hidden\]"))
        assert any("display: none" in body for body in rules.values())
