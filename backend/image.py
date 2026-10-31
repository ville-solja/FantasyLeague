"""Card image generation — PIL compositing extracted from main.py."""
import io
import logging
import os

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from accolades import ACCOLADE_KINDS
from dotabuff_league_logos import resolve_local_team_logo_path
from logo_hosts import safe_logo_url
from scoring import STAT_LABELS

logger = logging.getLogger(__name__)


def _resolve_assets_dir() -> str:
    here = os.path.dirname(__file__)
    repo_root = os.path.normpath(os.path.join(here, ".."))

    template_files = [
        os.path.join("card_templates", "Card_Grey.png"),
        os.path.join("card_templates", "Card_Blue.png"),
        os.path.join("card_templates", "Card_Purple.png"),
        os.path.join("card_templates", "Card_Gold.png"),
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

# Card Art Accolade Redesign: new illustrated templates with purpose-built slots for
# photo, logo, name, team, stats and a 3x2 accolade grid. Opaque slot fills, not
# transparent cutouts — the template is pasted first as the base, dynamic content on
# top. A real Holo template always ships; there is no procedural sheen fallback.
_CARD_TEMPLATES = {
    "common":    os.path.join("card_templates", "Card_Grey.png"),
    "rare":      os.path.join("card_templates", "Card_Blue.png"),
    "epic":      os.path.join("card_templates", "Card_Purple.png"),
    "legendary": os.path.join("card_templates", "Card_Gold.png"),
}
_HOLO_TEMPLATE = os.path.join("card_templates", "Card_Holo.png")

_ACCOLADES_DIR = "accolades"

_CARD_SIZE = (687, 1024)

# Slot rects measured by pixel-scanning assets/card_templates/Card_Grey.png (the
# templates' opaque interior fills) — (x0, y0, x1, y1), all rarities share the same
# layout.
_PHOTO_SLOT = (222, 119, 473, 372)          # square portrait crop
_NAME_BAR = (125, 416, 571, 469)            # player name bar's text area
_TEAM_NAME_BAR = (217, 499, 542, 545)       # team name bar's text area (right of its icon)
_STATS_BOX = (93, 575, 601, 771)
_LOGO_BOX = (93, 815, 338, 937)             # aspect-fit box, not a circle

# 3x2 accolade badge grid, reading order (left to right, top to bottom).
_ACCOLADE_COLS = (378, 460, 542)
_ACCOLADE_ROWS = (804, 888)
_ACCOLADE_CELL = (58, 59)                   # (w, h) per cell
_ACCOLADE_MAX = 6

_NAME_FONT_SIZE = 34
_TEAM_FONT_SIZE = 24
_STAT_FONT_SIZE = 28
_STAT_LINE_GAP = 44
_ACCOLADE_COUNT_FONT_SIZE = 17
_ACCOLADE_COUNT_BADGE_RADIUS = 11

# Each ACCOLADE_KINDS key's badge icon in assets/accolades/ — distinct from the
# Lucide icon names ACCOLADE_KINDS carries for use elsewhere on the site. Kept local
# to image.py (not merged into ACCOLADE_KINDS) since that struct is parity-tested
# against frontend/app-globals.js (test_issue_230).
_ACCOLADE_ICON_FILES = {
    "div1":           "Accolade_Div1_Champion.png",
    "div2":           "Accolade_Div2_Champion.png",
    "div1_runner_up": "Accolade_Div1_Runnerup.png",
    "div2_runner_up": "Accolade_Div2_Runnerup.png",
    "div1_third":     "Accolade_Div1_Third.png",
    "div2_third":     "Accolade_Div2_Third.png",
    "most_points":    "Accolade_Most_Points.png",
    "best_average":   "Accolade_Best_Average.png",
    "best_match":     "Accolade_Best_Single_Match.png",
    "fantasy_winner": "Accolade_Season_Winner.png",
    "played":         "Accolade_Played.png",
}
# Every ACCOLADE_KINDS key has a badge — test_card_art_accolade_redesign.py checks
# the maps agree.

# Card-face priority (champion > runner-up > third > fantasy winner > performance
# awards > played) — distinct from accolades._KIND_ORDER (ACCOLADE_KINDS list order,
# which puts performance awards before fantasy_winner; that order is for the detail
# list, not the card).
_ACCOLADE_PRIORITY = {
    "div1": 0, "div2": 0,
    "div1_runner_up": 1, "div2_runner_up": 1,
    "div1_third": 2, "div2_third": 2,
    "fantasy_winner": 3,
    "most_points": 4, "best_average": 4, "best_match": 4,
    "played": 5,
}


_FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# The name/team bars on the new templates are near-black fills (unlike the old
# templates' light plates), so the text needs to be light, with a dark shadow for
# pop against the template's varied gold/silver trim — not the old dark-on-light
# combination (confirmed unreadable by mock-up review).
_NAME_TEAM_FILL = (235, 230, 220, 255)
_NAME_TEAM_SHADOW = (15, 14, 12, 220)


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


def _aspect_fit(img, w: int, h: int):
    """Scale img to fit within a w x h box, preserving aspect ratio (no crop, no
    distortion) — may come out smaller than the box on one axis."""
    sw, sh = img.size
    if sw <= 0 or sh <= 0:
        return img.resize((w, h), Image.LANCZOS)
    scale = min(w / sw, h / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    return img.resize((nw, nh), Image.LANCZOS)


def _paste_fitted(base, img, box):
    """alpha_composite `img` centred within `box` (x0, y0, x1, y1), used for anything
    already sized to fit (aspect-fit logos/icons, or a placeholder matching the box)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    fx = x0 + (w - img.width) // 2
    fy = y0 + (h - img.height) // 2
    base.alpha_composite(img, (fx, fy))


def _fetch_team_logo_image(team_logo_url: str | None, size):
    """Team badge from DB `logo_url` (HTTP), fetched only from an allowlisted host (issue #171)."""
    u = safe_logo_url(_normalize_image_url(team_logo_url))
    return _fetch_pil_image(u, size) if u else None


def _load_team_logo_for_card(team_name: str | None, team_logo_url: str | None, size):
    """Prefer PNG under {assets}/dotabuff_league_logos/ (ingest), else HTTP logo_url.
    `size` is a (w, h) box; the logo is aspect-fit into it (plain aspect-fit of the
    source file as-is — no padding trim, confirmed by mock-up review)."""
    logo_dir = os.path.join(_ASSETS_DIR, "dotabuff_league_logos")
    path = resolve_local_team_logo_path(logo_dir, team_name)
    if path and PIL_AVAILABLE:
        try:
            img = Image.open(path).convert("RGBA")
            w, h = size if isinstance(size, tuple) else (size, size)
            return _aspect_fit(img, w, h)
        except Exception:
            pass
    return _fetch_team_logo_image(team_logo_url, size)


def _blank_logo_placeholder(w: int, h: int):
    """Solid black placeholder for a card's team-logo slot when no logo can be
    resolved yet (e.g. before a team's local Dotabuff PNG has been scraped or
    logo_url populated) — cleaner than leaving the slot unpainted."""
    return Image.new("RGBA", (w, h), (0, 0, 0, 255))


def _normalize_image_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    u = str(url).strip()
    if u.startswith("//"):
        u = "https:" + u
    return u


def _fetch_pil_image(url: str, size):
    """Download an image and return it decoded (RGBA), fit to `size`: a (w, h) tuple
    is aspect-fit (no distortion); a bare int stretches to size x size (legacy square
    behaviour, kept for the avatar). Returns None on any failure."""
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
        if isinstance(size, tuple):
            return _aspect_fit(img, *size)
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


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


def _draw_text_in_box(draw, text: str, box, font, fill, shadow, pad: int = 16):
    """Centre `text` within its own box's text area — not the full card width."""
    if not text:
        return
    x0, y0, x1, y1 = box
    max_w = max(1, (x1 - x0) - pad * 2)
    t = _truncate_centered_line(draw, text, font, max_w)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    _draw_centered_text(draw, t, cx, cy, font, fill, shadow=shadow)


def _modifier_lines_from_map(mods: dict) -> list[str]:
    if not mods:
        return []
    lines: list[str] = []
    for stat_key, bonus in sorted(mods.items()):
        label = STAT_LABELS.get(stat_key, stat_key.replace("_", " ")).upper()
        pct = int(bonus) if float(bonus).is_integer() else bonus
        lines.append(f"{label} +{pct}%")
    return lines


def _draw_stat_modifiers(draw, mods: dict, box):
    """Stack modifier lines inside the template's stats box, centred as a block."""
    lines = _modifier_lines_from_map(mods)
    if not lines:
        return
    font = _get_font(_STAT_FONT_SIZE)
    fill = (200, 230, 210, 255)
    shadow = (15, 18, 20, 220)
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    max_w = max(1, (x1 - x0) - 24)
    block_h = len(lines) * _STAT_LINE_GAP
    cy = y0 + max(_STAT_LINE_GAP // 2, ((y1 - y0) - block_h) // 2 + _STAT_LINE_GAP // 2)
    for line in lines:
        t = _truncate_centered_line(draw, line, font, max_w)
        _draw_centered_text(draw, t, cx, cy, font, fill, shadow=shadow)
        cy += _STAT_LINE_GAP


def _accolade_counts(accolade_keys) -> dict:
    """How many times the player holds each accolade kind. accolade_keys repeats a
    key once per season it was earned (e.g. three "played" entries for 3 seasons, or
    two "div1" entries for two championships), so this collapses that into a count
    per kind for the card-face count badge."""
    counts: dict = {}
    for k in accolade_keys or []:
        counts[k] = counts.get(k, 0) + 1
    return counts


def _select_accolade_keys(accolade_keys, limit: int = _ACCOLADE_MAX) -> list[str]:
    """The top `limit` *unique* keys by card-face priority (champion > runner-up >
    third > fantasy winner > performance awards > played) — deduplicated first, so a
    kind earned in multiple seasons takes one grid slot (with a count badge) rather
    than several identical icons. A stable sort on first-seen order keeps same-tier
    keys in the order given, so passing accolades.accolades_for's newest-season-first
    list keeps each tier newest first too."""
    seen: list[str] = []
    for k in accolade_keys or []:
        if k not in seen:
            seen.append(k)
    ordered = sorted(seen, key=lambda k: _ACCOLADE_PRIORITY.get(k, 99))
    return ordered[:limit]


def _accolade_cell_rect(index: int):
    col, row = index % 3, index // 3
    cw, ch = _ACCOLADE_CELL
    x0 = _ACCOLADE_COLS[col]
    y0 = _ACCOLADE_ROWS[row]
    return (x0, y0, x0 + cw, y0 + ch)


def _draw_accolade_count_badge(draw, count: int, cell_box):
    """A small count badge over the cell's bottom-right corner, shown only when the
    player holds 2 or more of that accolade (e.g. division champion in more than one
    season) — a single accolade shows no badge."""
    if count < 2:
        return
    x0, y0, x1, y1 = cell_box
    r = _ACCOLADE_COUNT_BADGE_RADIUS
    cx, cy = x1 - r - 1, y1 - r - 1
    draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                 fill=(20, 18, 14, 235), outline=(210, 180, 120, 255), width=1)
    font = _get_font(_ACCOLADE_COUNT_FONT_SIZE)
    text = str(count) if count < 10 else "9+"
    draw.text((cx, cy), text, font=font, fill=(255, 250, 235, 255), anchor="mm")


def _composite_accolades(base, accolade_keys):
    """Paste up to 6 accolade badge icons into the 3x2 grid, one per unique accolade
    kind the player holds, each with a small count badge when held 2+ times. An
    accolade key with no entry in _ACCOLADE_ICON_FILES (stale/unmapped) or a missing
    icon file is skipped rather than breaking the render; that cell is simply left
    blank."""
    counts = _accolade_counts(accolade_keys)
    selected = _select_accolade_keys(accolade_keys)
    draw = None
    for i, key in enumerate(selected):
        filename = _ACCOLADE_ICON_FILES.get(key)
        if not filename:
            continue
        path = os.path.join(_ASSETS_DIR, _ACCOLADES_DIR, filename)
        try:
            icon = Image.open(path).convert("RGBA")
        except Exception:
            continue
        box = _accolade_cell_rect(i)
        w, h = box[2] - box[0], box[3] - box[1]
        _paste_fitted(base, _aspect_fit(icon, w, h), box)
        if counts.get(key, 1) >= 2:
            if draw is None:
                draw = ImageDraw.Draw(base)
            _draw_accolade_count_badge(draw, counts[key], box)


def _load_template(ct: str, is_holo: bool):
    """The rarity template, or the dedicated Holo template for a Holo Legendary. No
    fallback: a real Holo template always ships, so a missing file raises rather than
    quietly substituting a generated sheen."""
    if is_holo and ct == "legendary":
        template_file = _HOLO_TEMPLATE
    else:
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
    accolade_keys: list[str] | None = None,
):
    """Composite a player card PNG and return a PIL Image.

    The template is the base (its slots are opaque fills, not transparent cutouts):
    it is pasted first, then the photo, the team logo, the name/team text, the stat
    modifiers and up to 6 accolade badge icons are pasted on top. User tags are not
    drawn: the card viewer lists them under the card (issue #228)."""
    ct = (card_type or "common").lower()
    base = _load_template(ct, is_holo)

    # ── Player photo (square, no circular crop) ──────────────────────────────
    px0, py0, px1, py1 = _PHOTO_SLOT
    pw, ph = px1 - px0, py1 - py0
    avatar = _fetch_pil_image(avatar_url, max(pw, ph))
    if avatar:
        base.alpha_composite(avatar.resize((pw, ph), Image.LANCZOS), (px0, py0))

    # ── Team logo (aspect-fit box, no circular crop) ─────────────────────────
    lx0, ly0, lx1, ly1 = _LOGO_BOX
    lw, lh = lx1 - lx0, ly1 - ly0
    logo = _load_team_logo_for_card(team_name, team_logo_url, (lw, lh))
    if logo is None:
        logo = _blank_logo_placeholder(lw, lh)
    _paste_fitted(base, logo, _LOGO_BOX)

    # ── Accolade badges (up to 6, 3x2 grid) ───────────────────────────────────
    _composite_accolades(base, accolade_keys or [])

    # ── Text ────────────────────────────────────────────────────────────────
    draw = ImageDraw.Draw(base)

    name_font = _get_font(_NAME_FONT_SIZE)
    name = (player_name or "Unknown").upper()
    _draw_text_in_box(draw, name, _NAME_BAR, name_font, _NAME_TEAM_FILL, _NAME_TEAM_SHADOW)

    team_font = _get_font(_TEAM_FONT_SIZE)
    team = (team_name or "").upper()
    if team:
        _draw_text_in_box(draw, team, _TEAM_NAME_BAR, team_font, _NAME_TEAM_FILL, _NAME_TEAM_SHADOW)

    _draw_stat_modifiers(draw, card_modifiers or {}, _STATS_BOX)

    return base
