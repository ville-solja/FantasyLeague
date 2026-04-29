"""Card image generation — PIL compositing extracted from main.py."""
import io
import os

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from dotabuff_league_logos import resolve_local_team_logo_path


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

# Human-readable stat names (must match frontend roster copy / SCORING_STATS)
_STAT_LABELS_CARD = {
<<<<<<< HEAD
    "kills": "Kills",
    "assists": "Assists",
    "deaths": "Deaths",
    "gold_per_min": "GPM",
    "obs_placed": "Observer wards",
    "sen_placed": "Sentry wards",
    "tower_damage": "Tower damage",
=======
    # Must stay aligned with `SCORING_STATS` + deaths (card modifier pool)
    "kills": "Kills",
    "last_hits": "Last hits",
    "denies": "Denies",
    "deaths": "Deaths",
    "gold_per_min": "GPM",
    "obs_placed": "Observer wards",
    "towers_killed": "Towers",
    "roshan_kills": "Roshan",
    "teamfight_participation": "Teamfight",
    "camps_stacked": "Camps stacked",
    "rune_pickups": "Runes",
    "firstblood_claimed": "First blood",
    "stuns": "Stuns",
>>>>>>> 25cc59e (Initial commit)
}

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
    """Team badge from DB `logo_url` (HTTP)."""
    u = _normalize_image_url(team_logo_url)
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
            "User-Agent": "FantasyLeagueCardBot/1.0 (+https://github.com/)",
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
        label = _STAT_LABELS_CARD.get(stat_key, stat_key.replace("_", " ")).upper()
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


def generate_card_image(
    card_type: str,
    player_name: str | None,
    avatar_url: str | None,
    team_name: str | None,
    team_logo_url: str | None,
    card_modifiers: dict | None = None,
):
    """Composite a player card PNG and return a PIL Image."""
    ct = (card_type or "common").lower()
    template_file = _CARD_TEMPLATES.get(ct, _CARD_TEMPLATES["common"])
    template = Image.open(os.path.join(_ASSETS_DIR, template_file)).convert("RGBA")

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
    logo = _load_team_logo_for_card(team_name, team_logo_url, sr * 2)
    if logo:
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
