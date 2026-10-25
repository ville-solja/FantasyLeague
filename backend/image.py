"""Card image generation — PIL compositing extracted from main.py."""
import colorsys
import io
import logging
import os

try:
    from PIL import Image, ImageDraw, ImageFont
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

# Layout positions discovered by pixel analysis of the 597×845 templates
_BIG_CIRCLE    = (298, 375, 175)   # (cx, cy, radius) — player avatar
_SMALL_CIRCLE  = (444, 258,  52)   # (cx, cy, radius) — team logo
_PLAYER_NAME_Y = 90
_TEAM_NAME_Y   = 155
_CARD_SIZE     = (597, 845)
# Stat modifiers — bottom band of the template (below portrait)
_MODIFIERS_START_Y = 620
_MODIFIER_LINE_GAP = 50
_MODIFIER_MAX_WIDTH = 500
# Epic/Legendary templates' cutouts/plates sit slightly higher than common/rare — nudge content down.
_CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY = 8


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


def _fetch_team_logo_image(team_logo_url: str | None, diameter: int):
    """Team badge from DB `logo_url` (HTTP), fetched only from an allowlisted host (issue #171)."""
    u = safe_logo_url(_normalize_image_url(team_logo_url))
    return _fetch_pil_image(u, diameter) if u else None


def _load_team_logo_for_card(team_name: str | None, team_logo_url: str | None, diameter: int):
    """Prefer PNG under {assets}/dotabuff_league_logos/ (ingest), else HTTP logo_url."""
    logo_dir = os.path.join(_ASSETS_DIR, "dotabuff_league_logos")
    path = resolve_local_team_logo_path(logo_dir, team_name)
    if path and PIL_AVAILABLE:
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((diameter, diameter), Image.LANCZOS)
            return img
        except Exception:
            pass
    return _fetch_team_logo_image(team_logo_url, diameter)


def _blank_logo_placeholder(diameter: int):
    """Solid black circular placeholder for a card's team-logo slot when no logo
    can be resolved yet (e.g. before a team's local Dotabuff PNG has been scraped
    or logo_url populated) — cleaner than leaving the slot unpainted."""
    return Image.new("RGBA", (diameter, diameter), (0, 0, 0, 255))


def _normalize_image_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    u = str(url).strip()
    if u.startswith("//"):
        u = "https:" + u
    return u


def _fetch_pil_image(url: str, diameter: int):
    """Download an image, resize to diameter×diameter, return RGBA PIL Image or None."""
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
        img = img.resize((diameter, diameter), Image.LANCZOS)
        return img
    except Exception:
        return None


def _circle_crop(img):
    """Apply a circular alpha mask to a square PIL RGBA image."""
    sz = img.size[0]
    mask = Image.new("L", (sz, sz), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, sz, sz), fill=255)
    result = img.copy()
    result.putalpha(mask)
    return result


def _draw_centered_text(draw, text: str, cx: int, cy: int, font, fill,
                        shadow=(0, 0, 0, 160)):
    """Draw text centred at (cx, cy) with a configurable drop shadow."""
    try:
        draw.text((cx + 2, cy + 2), text, font=font, fill=shadow, anchor="mm")
        draw.text((cx, cy), text, font=font, fill=fill, anchor="mm")
        return
    except (TypeError, ValueError):
        pass
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - w // 2, cy - h // 2
    draw.text((x + 2, y + 2), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _truncate_centered_line(draw, text: str, font, max_w: int) -> str:
    t = text
    if hasattr(draw, "textlength"):
        while len(t) > 3 and draw.textlength(t, font=font) > max_w:
            t = t[:-1]
    return t


def _modifier_lines_from_map(mods: dict) -> list[str]:
    if not mods:
        return []
    lines: list[str] = []
    for stat_key, bonus in sorted(mods.items()):
        label = STAT_LABELS.get(stat_key, stat_key.replace("_", " ")).upper()
        pct = int(bonus) if float(bonus).is_integer() else bonus
        lines.append(f"{label} +{pct}%")
    return lines


def _draw_card_modifiers(draw, mods: dict, y_offset: int = 0):
    """Stack modifier lines in the empty lower area of the card template."""
    lines = _modifier_lines_from_map(mods)
    if not lines:
        return
    font = _get_font(30)
    fill = (200, 230, 210, 255)
    shadow = (15, 18, 20, 220)
    cy = _MODIFIERS_START_Y + y_offset
    for line in lines:
        t = _truncate_centered_line(draw, line, font, _MODIFIER_MAX_WIDTH)
        _draw_centered_text(draw, t, _CARD_SIZE[0] // 2, cy, font, fill, shadow=shadow)
        cy += _MODIFIER_LINE_GAP


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


def _holo_sheen(template):
    """A diagonal rainbow sheen, visible only where the frame template is opaque, so
    the avatar and the team logo stay untouched."""
    w, h = template.size
    steps = 64
    strip = Image.new("RGBA", (steps, 1))
    strip.putdata([tuple(int(c * 255) for c in colorsys.hsv_to_rgb(i / steps, 0.45, 1.0))
                   + (_HOLO_SHEEN_ALPHA,) for i in range(steps)])
    side = int((w ** 2 + h ** 2) ** 0.5) + 2
    sheen = strip.resize((side, side), Image.BILINEAR).rotate(35, resample=Image.BILINEAR)
    left, top = (side - w) // 2, (side - h) // 2
    sheen = sheen.crop((left, top, left + w, top + h))
    from PIL import ImageChops
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
    """Composite a player card PNG and return a PIL Image. Accolades and user tags are
    not drawn: the card viewer lists them under the card (issue #228)."""
    ct = (card_type or "common").lower()
    template = _load_template(ct, is_holo)

    y_off = _CARD_LAYOUT_Y_OFFSET_EPIC_LEGENDARY if ct in ("epic", "legendary") else 0

    # Dark base matching the card's background colour
    base = Image.new("RGBA", _CARD_SIZE, (35, 37, 40, 255))

    # ── Player avatar (big circle) ──────────────────────────────────────────
    cx, cy, r = _BIG_CIRCLE
    cy += y_off
    avatar = _fetch_pil_image(avatar_url, r * 2)
    if avatar:
        base.paste(_circle_crop(avatar), (cx - r, cy - r), _circle_crop(avatar))

    # ── Team logo (small circle) ────────────────────────────────────────────
    scx, scy, sr = _SMALL_CIRCLE
    scy += y_off
    logo = _load_team_logo_for_card(team_name, team_logo_url, sr * 2) or _blank_logo_placeholder(sr * 2)
    base.paste(_circle_crop(logo), (scx - sr, scy - sr), _circle_crop(logo))

    # ── Composite frame on top ──────────────────────────────────────────────
    base.alpha_composite(template)

    # ── Text ────────────────────────────────────────────────────────────────
    draw = ImageDraw.Draw(base)

    # Player name — big plate (bright silver bg → dark text, light shadow)
    name_font = _get_font(32)
    name = (player_name or "Unknown").upper()
    if hasattr(draw, "textlength"):
        while len(name) > 1 and draw.textlength(name, font=name_font) > 480:
            name = name[:-1]
    _draw_centered_text(draw, name, _CARD_SIZE[0] // 2, _PLAYER_NAME_Y + y_off,
                        name_font, (35, 35, 35, 255), shadow=(200, 200, 200, 100))

    # Team name — use same shadow as player; _draw_centered_text default is dark (0,0,0,160).
    team_font = _get_font(22)
    team = (team_name or "").upper()
    if team:
        _draw_centered_text(draw, team, _CARD_SIZE[0] // 2, _TEAM_NAME_Y + y_off,
                            team_font, (35, 35, 35, 255), shadow=(200, 200, 200, 100))

    _draw_card_modifiers(draw, card_modifiers or {}, y_offset=y_off)

    return base
