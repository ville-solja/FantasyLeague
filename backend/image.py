"""Card image generation (layout A, Classic TCG; issue #218).

The rarity templates (`assets/Card_Template_<Rarity>.png`, and the optional
`Card_Template_Holo.png`) are drawn by `backend/scripts/make_card_templates.py`
from the slot constants below. This module pastes the avatar and team logo under
the template's transparent cutouts, then draws the player name, team name and
modifier lines. The frame's edge colour is the rarity; nothing else names it.
"""
import colorsys
import io
import logging
import math
import os

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from dotabuff_league_logos import resolve_local_team_logo_path
from logo_hosts import safe_logo_url
from scoring import STAT_LABELS

logger = logging.getLogger(__name__)


def _resolve_assets_dir() -> str:
    here = os.path.dirname(__file__)
    repo_root = os.path.normpath(os.path.join(here, ".."))

    template_files = [
        "Card_Template_Common.png",
        "Card_Template_Rare.png",
        "Card_Template_Epic.png",
        "Card_Template_Legendary.png",
    ]

    candidates = [
        os.path.join(here, "Assets"),
        os.path.join(here, "assets"),
        os.path.join(repo_root, "Assets"),
        os.path.join(repo_root, "assets"),
        "Assets",
        "assets",
        "/app/Assets",
        "/app/assets",
    ]
    for c in candidates:
        if not os.path.isdir(c):
            continue
        if all(os.path.exists(os.path.join(c, f)) for f in template_files):
            return c
    return "assets"


_ASSETS_DIR = _resolve_assets_dir()

_CARD_TEMPLATES = {
    "common":    "Card_Template_Common.png",
    "rare":      "Card_Template_Rare.png",
    "epic":      "Card_Template_Epic.png",
    "legendary": "Card_Template_Legendary.png",
}

# Issue #53: Holo Legendaries. The template is optional; without it the Legendary
# template gets a generated iridescent sheen (and one warning per process).
_HOLO_TEMPLATE = "Card_Template_Holo.png"
_HOLO_SHEEN_ALPHA = 70
_holo_warned = False

# ── Layout A on the 597 x 845 card. Boxes are (left, top, right, bottom), right
# and bottom exclusive, as in PIL's crop boxes. ─────────────────────────────────
_CARD_SIZE = (597, 845)
_CARD_RADIUS = 28
_FRAME_WIDTH = 6
_NAME_BAR = (24, 24, 573, 92)
_LEFT_PILLAR = (24, 104, 104, 484)         # tag pips (HTML overlay, #217)
_PORTRAIT_FRAME = (108, 104, 488, 484)     # 6 px rarity border around the slot
_PORTRAIT_SLOT = (114, 110, 482, 478)      # 368 x 368: the 184 px avatar at 2x
_RIGHT_PILLAR = (492, 104, 572, 484)       # season pips (HTML overlay, #50)
_TYPE_LINE = (24, 496, 573, 560)
_LOGO_SLOT = (26, 498, 126, 558)           # 100 x 60: the 250 x 150 logo at 0.4x
_RULES_BOX = (24, 572, 573, 821)

_BASE_COLOR = (35, 37, 40, 255)            # shows through empty cutouts
_LOGO_PLATE = (27, 27, 33, 255)            # behind a contained fallback logo

# Rarity colours match the frontend tokens (--k-rarity-*, colors_and_type.css).
_RARITY_COLORS = {
    "common":    (154, 154, 162),
    "rare":      (90, 160, 232),
    "epic":      (176, 106, 224),
    "legendary": (240, 168, 58),
}
_RARITY_DEEP = {
    "common":    (38, 38, 44),
    "rare":      (15, 42, 70),
    "epic":      (46, 22, 64),
    "legendary": (58, 37, 10),
}
_FOIL_ALPHA = 34                           # the ordinary legendary's light shine

# Text colours from the layout A drawing.
_NAME_COLOR = (243, 234, 216, 255)
_TEAM_COLOR = (216, 208, 192, 255)
_RULES_TEXT = (42, 38, 32, 255)
_RULES_MUTED = (74, 67, 54, 255)
_RULES_LINE = (184, 173, 150, 255)

# Font sizes chosen so the name and modifier values stay readable at 180 px wide
# (x0.30): 40 -> 12 px, 34 -> 10 px.
_NAME_FONT_SIZE = 40
_NAME_FONT_MIN = 30
_TEAM_FONT_SIZE = 28
_TEAM_FONT_MIN = 20
_MODIFIER_FONT_SIZE = 34
_MODIFIER_FIRST_Y = 606
_MODIFIER_LINE_GAP = 58
_MAX_MODIFIER_LINES = 3


_FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _get_font(size: int):
    if not PIL_AVAILABLE:
        return None
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _slot_size(slot) -> tuple[int, int]:
    return slot[2] - slot[0], slot[3] - slot[1]


def _text_width(draw, text: str, font) -> float:
    if hasattr(draw, "textlength"):
        return draw.textlength(text, font=font)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _ellipsize(draw, text: str, font, max_w: int) -> str:
    if _text_width(draw, text, font) <= max_w:
        return text
    t = text
    while len(t) > 1 and _text_width(draw, t + "…", font) > max_w:
        t = t[:-1]
    return t.rstrip() + "…"


def _fit_text(draw, text: str, max_w: int, size: int, min_size: int):
    """(text, font): shrink the font down to min_size, then ellipsize."""
    for s in range(size, min_size - 1, -2):
        font = _get_font(s)
        if _text_width(draw, text, font) <= max_w:
            return text, font
    font = _get_font(min_size)
    return _ellipsize(draw, text, font, max_w), font


# ── Images ──────────────────────────────────────────────────────────────────

def _normalize_image_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    u = str(url).strip()
    if u.startswith("//"):
        u = "https:" + u
    return u


def _fetch_pil_image(url: str, size=None):
    """Download an image as RGBA, or None. `size` (int) resizes it to a square."""
    url = _normalize_image_url(url)
    if not url or not PIL_AVAILABLE:
        return None
    try:
        import requests as _req
        headers = {
            "User-Agent": "KanaCards/1.0 (+https://kana-cards.com)",
            "Accept": "image/*,*/*;q=0.8",
        }
        r = _req.get(url, timeout=10, headers=headers)
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        if size:
            img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        return None


def _fit_into_slot(img, slot_size: tuple[int, int], plate=_LOGO_PLATE):
    """Resize to slot_size when the aspect ratio matches (an exact scale); otherwise
    contain it, centred, on the plate colour. Never stretched or cropped."""
    w, h = slot_size
    if img.width * h == img.height * w:
        return img.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), plate)
    fitted = ImageOps.contain(img, (w, h), Image.LANCZOS)
    out.alpha_composite(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    return out


def _fetch_team_logo_image(team_logo_url: str | None, size=None):
    """Team badge from DB `logo_url` (HTTP), fetched only from an allowlisted host (issue #171)."""
    u = safe_logo_url(_normalize_image_url(team_logo_url))
    return _fetch_pil_image(u, size) if u else None


def _load_team_logo_for_card(team_name: str | None, team_logo_url: str | None,
                             slot_size=None):
    """Logo fitted into the logo slot: the cached 250 x 150 PNG under
    {assets}/dotabuff_league_logos/ (scaled 0.4x), else the HTTP `logo_url`
    contained in the slot. None when neither resolves. No circle crop."""
    if isinstance(slot_size, int):
        slot_size = (slot_size, slot_size)
    slot_size = slot_size or _slot_size(_LOGO_SLOT)
    logo_dir = os.path.join(_ASSETS_DIR, "dotabuff_league_logos")
    path = resolve_local_team_logo_path(logo_dir, team_name)
    if path and PIL_AVAILABLE:
        try:
            return _fit_into_slot(Image.open(path).convert("RGBA"), slot_size)
        except Exception:
            pass
    img = _fetch_team_logo_image(team_logo_url, None)
    return _fit_into_slot(img, slot_size) if img is not None else None


def _blank_logo_placeholder(slot_size=None):
    """Solid black plate for the logo slot when no logo resolves yet (issue #107)."""
    if isinstance(slot_size, int):
        slot_size = (slot_size, slot_size)
    return Image.new("RGBA", slot_size or _slot_size(_LOGO_SLOT), (0, 0, 0, 255))


def _avatar_for_slot(img):
    """The avatar at the portrait slot size: the 184 px Steam avatar scales 2x
    exactly; a non-square source is centre-fitted, never stretched."""
    size = _slot_size(_PORTRAIT_SLOT)
    if img.width == img.height:
        return img.resize(size, Image.LANCZOS)
    return ImageOps.fit(img, size, Image.LANCZOS)


# ── Drawing helpers ─────────────────────────────────────────────────────────

def _draw_text(draw, xy, text: str, font, fill, anchor: str = "lm"):
    try:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
    except (TypeError, ValueError):
        draw.text(xy, text, font=font, fill=fill)


def _modifier_rows_from_map(mods: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for stat_key, bonus in sorted((mods or {}).items()):
        label = STAT_LABELS.get(stat_key, stat_key.replace("_", " ")).upper()
        pct = int(bonus) if float(bonus).is_integer() else bonus
        rows.append((label, f"+{pct}%"))
    return rows


def _modifier_lines_from_map(mods: dict) -> list[str]:
    return [f"{label} {value}" for label, value in _modifier_rows_from_map(mods)]


def _draw_rules_box(draw, mods: dict):
    """Modifier lines (up to 3) in the cream box, or "No stat modifiers"."""
    x0, _, x1, _ = _RULES_BOX
    left, right = x0 + 24, x1 - 24
    rows = _modifier_rows_from_map(mods)[:_MAX_MODIFIER_LINES]
    font = _get_font(_MODIFIER_FONT_SIZE)
    y = _MODIFIER_FIRST_Y
    for label, value in rows:
        vw = _text_width(draw, value, font)
        label = _ellipsize(draw, label, font, int(right - left - vw - 16))
        _draw_text(draw, (left, y), label, font, _RULES_TEXT, anchor="lm")
        _draw_text(draw, (right, y), value, font, _RULES_TEXT, anchor="rm")
        for dx in range(left, right, 6):
            draw.line((dx, y + 24, dx + 2, y + 24), fill=_RULES_LINE, width=2)
        y += _MODIFIER_LINE_GAP
    if not rows:
        _draw_text(draw, ((x0 + x1) // 2, _MODIFIER_FIRST_Y + _MODIFIER_LINE_GAP),
                   "No stat modifiers", _get_font(24), _RULES_MUTED, anchor="mm")


def _apply_foil_sheen(img):
    """The ordinary legendary's light shine: a soft diagonal light band (115 deg)."""
    w, h = img.size
    sw, sh = 60, 85
    small = Image.new("L", (sw, sh), 0)
    dx, dy = math.sin(math.radians(115)), -math.cos(math.radians(115))
    length = abs(w * dx) + abs(h * dy)
    px = small.load()
    for j in range(sh):
        for i in range(sw):
            x, y = (i + 0.5) * w / sw - w / 2, (j + 0.5) * h / sh - h / 2
            t = (x * dx + y * dy) / length + 0.5
            a = 0.0
            if 0.30 < t < 0.60:
                a = (t - 0.30) / 0.15 if t < 0.45 else (0.60 - t) / 0.15
            px[i, j] = int(_FOIL_ALPHA * a)
    alpha = small.resize((w, h), Image.BILINEAR)
    sheen = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    sheen.putalpha(alpha)
    img.alpha_composite(sheen)
    return img


def _card_mask():
    mask = Image.new("L", _CARD_SIZE, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, _CARD_SIZE[0] - 1, _CARD_SIZE[1] - 1),
                                           radius=_CARD_RADIUS, fill=255)
    return mask


# ── Templates and Holo ──────────────────────────────────────────────────────

def _holo_template_path() -> str | None:
    path = os.path.join(_ASSETS_DIR, _HOLO_TEMPLATE)
    return path if os.path.exists(path) else None


def warn_if_holo_template_missing() -> bool:
    """Log once per process that Holo cards use the fallback sheen. Called at startup;
    the first Holo render calls it too. Returns True when it logged."""
    global _holo_warned
    if _holo_warned or _holo_template_path():
        return False
    _holo_warned = True
    logger.warning("%s not found in %s: Holo cards use the Legendary template with a "
                   "generated sheen", _HOLO_TEMPLATE, _ASSETS_DIR)
    return True


def _rainbow(size, saturation: float = 0.45, alpha: int = 255, angle: int = 35, bands: float = 1.0):
    """A diagonal rainbow layer of `size` with a uniform alpha."""
    w, h = size
    steps = 64
    strip = Image.new("RGBA", (steps, 1))
    strip.putdata([tuple(int(c * 255) for c in colorsys.hsv_to_rgb((i * bands / steps) % 1.0,
                                                                  saturation, 1.0))
                   + (alpha,) for i in range(steps)])
    side = int((w ** 2 + h ** 2) ** 0.5) + 2
    layer = strip.resize((side, side), Image.BILINEAR).rotate(angle, resample=Image.BILINEAR)
    left, top = (side - w) // 2, (side - h) // 2
    return layer.crop((left, top, left + w, top + h))


def _holo_sheen(template):
    """A diagonal rainbow sheen, visible only where the frame template is opaque, so
    the avatar and the team logo stay untouched."""
    sheen = _rainbow(template.size, alpha=_HOLO_SHEEN_ALPHA)
    sheen.putalpha(ImageChops.multiply(sheen.getchannel("A"), template.getchannel("A")))
    return sheen


def _load_template(ct: str, is_holo: bool):
    if is_holo and ct == "legendary":
        holo = _holo_template_path()
        if holo:
            return Image.open(holo).convert("RGBA")
        warn_if_holo_template_missing()
        template = Image.open(os.path.join(_ASSETS_DIR, _CARD_TEMPLATES["legendary"])).convert("RGBA")
        template.alpha_composite(_holo_sheen(template))
        return template
    template_file = _CARD_TEMPLATES.get(ct, _CARD_TEMPLATES["common"])
    return Image.open(os.path.join(_ASSETS_DIR, template_file)).convert("RGBA")


def generate_card_image(
    card_type: str,
    player_name: str | None,
    avatar_url: str | None,
    team_name: str | None,
    team_logo_url: str | None,
    card_modifiers: dict | None = None,
    is_holo: bool = False,
):
    """Composite a layout A player card PNG (597 x 845) and return a PIL Image.
    Accolades and user tags are not drawn: the frontend overlays them as HTML pips
    over the right and left pillars (issues #53, #217 and #218)."""
    ct = (card_type or "common").lower()
    if ct not in _CARD_TEMPLATES:
        ct = "common"
    holo = bool(is_holo) and ct == "legendary"
    template = _load_template(ct, holo)

    base = Image.new("RGBA", _CARD_SIZE, _BASE_COLOR)

    avatar = _fetch_pil_image(avatar_url, None)
    if avatar is not None:
        base.paste(_avatar_for_slot(avatar), _PORTRAIT_SLOT[:2])

    logo = _load_team_logo_for_card(team_name, team_logo_url, _slot_size(_LOGO_SLOT))
    if logo is None:
        logo = _blank_logo_placeholder(_slot_size(_LOGO_SLOT))
    plate = Image.new("RGBA", logo.size, _LOGO_PLATE)
    plate.alpha_composite(logo)
    base.paste(plate, _LOGO_SLOT[:2])

    base.alpha_composite(template)
    draw = ImageDraw.Draw(base)

    # Name bar: the player name only.
    nx0, ny0, nx1, ny1 = _NAME_BAR
    name, font = _fit_text(draw, player_name or "Unknown", (nx1 - 28) - (nx0 + 28),
                           _NAME_FONT_SIZE, _NAME_FONT_MIN)
    _draw_text(draw, (nx0 + 28, (ny0 + ny1) // 2), name, font, _NAME_COLOR, anchor="lm")

    # Type line: the logo slot, then the team name.
    tx0, ty0, tx1, ty1 = _TYPE_LINE
    if team_name:
        team_left = _LOGO_SLOT[2] + 14
        team, tfont = _fit_text(draw, team_name, tx1 - 18 - team_left,
                                _TEAM_FONT_SIZE, _TEAM_FONT_MIN)
        _draw_text(draw, (team_left, (ty0 + ty1) // 2), team, tfont, _TEAM_COLOR, anchor="lm")

    _draw_rules_box(draw, card_modifiers or {})

    if ct == "legendary" and not holo:
        _apply_foil_sheen(base)

    base.putalpha(_card_mask())
    return base
