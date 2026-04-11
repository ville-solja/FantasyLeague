"""
Manual run of the same Dotabuff league logo fetch as ingest (missing files only).

Requires: cloudscraper (listed in backend/requirements.txt)

  python backend/scripts/scrape_dotabuff_league_team_logos.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotabuff_league_logos import ensure_dotabuff_league_logos

if __name__ == "__main__":
    ensure_dotabuff_league_logos()
