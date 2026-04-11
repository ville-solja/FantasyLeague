"""
Kanaliiga / Dotabuff league hub pages: discover team icons (img.img-team.img-icon),
download missing PNGs under {card_assets}/dotabuff_league_logos/, use on cards before HTTP logo_url.

Pages default to league *overview* paths (not .../teams) to align with robots.txt Disallow on /teams.

Configure with DOTABUFF_LEAGUE_LOGO_PAGES (comma-separated URLs). Unset = default Kanaliiga URLs.
Set to empty string to disable fetching entirely.
"""
from __future__ import annotations

import html
import os
import re
import unicodedata

import requests

# Default: league overview URLs (no trailing /teams)
_DEFAULT_PAGES = (
    "https://www.dotabuff.com/esports/leagues/19368-kanaliiga-season-15,"
    "https://www.dotabuff.com/esports/leagues/19369-kanaliiga-season-15-lower"
)

IMG_RE = re.compile(
    r'<img\s+alt="([^"]*)"\s+class="img-team img-icon"\s+src="(https://[^"]+)"\s*/>',
    re.I,
)

_TEMPLATE_FILES = (
    "Card_Template_Common.png",
    "Card_Template_Rare.png",
    "Card_Template_Epic.png",
    "Card_Template_Legendary.png",
)


def resolve_card_assets_dir() -> str:
    """Same resolution as main._resolve_assets_dir (directory that holds card templates)."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(here, ".."))
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
        if all(os.path.exists(os.path.join(c, f)) for f in _TEMPLATE_FILES):
            return c
    return os.path.join(repo_root, "assets")


def league_logo_dir(assets_dir: str | None = None) -> str:
    base = assets_dir if assets_dir is not None else resolve_card_assets_dir()
    return os.path.join(base, "dotabuff_league_logos")


def dotabuff_page_urls() -> list[str]:
    raw = os.getenv("DOTABUFF_LEAGUE_LOGO_PAGES")
    if raw is not None:
        s = raw.strip()
        if not s:
            return []
        return [u.strip() for u in s.split(",") if u.strip()]
    return [u.strip() for u in _DEFAULT_PAGES.split(",") if u.strip()]


def team_logo_png_filename(team_name: str) -> str:
    s = unicodedata.normalize("NFC", team_name.strip())
    s = html.unescape(s)
    for ch in r'\/:*?"<>|':
        s = s.replace(ch, "_")
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s or "unknown")[:120] + ".png"


def resolve_local_team_logo_path(logo_dir: str, team_name: str | None) -> str | None:
    if not team_name or not team_name.strip():
        return None
    if not os.path.isdir(logo_dir):
        return None
    want = team_logo_png_filename(team_name)
    exact = os.path.join(logo_dir, want)
    if os.path.isfile(exact):
        return exact
    wl = want.lower()
    try:
        for f in os.listdir(logo_dir):
            if f.lower() == wl:
                return os.path.join(logo_dir, f)
    except OSError:
        return None
    return None


def ensure_dotabuff_league_logos() -> None:
    """Fetch Dotabuff league pages; download any team icon PNG not already on disk."""
    pages = dotabuff_page_urls()
    if not pages:
        return
    try:
        import cloudscraper
    except ImportError:
        print("[DOTABUFF] cloudscraper missing; skip league logos (pip install cloudscraper)")
        return

    logo_dir = league_logo_dir()
    os.makedirs(logo_dir, exist_ok=True)

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    found: dict[str, str] = {}
    for url in pages:
        try:
            print(f"[DOTABUFF] GET {url}")
            r = scraper.get(url, timeout=60)
            r.raise_for_status()
            for alt, src in IMG_RE.findall(r.text):
                found[html.unescape(alt.strip())] = src
        except Exception as e:
            print(f"[DOTABUFF] page failed {url!r}: {e}")

    if not found:
        print("[DOTABUFF] no img-team icons parsed (HTML change?)")
        return

    ua = {"User-Agent": "FantasyLeague/1.0 (+local ingest; league logos)"}
    n_new = 0
    for alt, img_url in found.items():
        fn = team_logo_png_filename(alt)
        path = os.path.join(logo_dir, fn)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            continue
        try:
            ir = requests.get(img_url, timeout=30, headers=ua)
            ir.raise_for_status()
            with open(path, "wb") as f:
                f.write(ir.content)
            n_new += 1
            print(f"[DOTABUFF] saved {fn}")
        except Exception as e:
            print(f"[DOTABUFF] skip {fn!r}: {e}")
    if n_new:
        print(f"[DOTABUFF] downloaded {n_new} new logo(s) -> {logo_dir}")
    else:
        print(f"[DOTABUFF] all {len(found)} league icons already present under {logo_dir}")
