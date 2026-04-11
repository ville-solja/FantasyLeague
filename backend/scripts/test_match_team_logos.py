"""
Fetch a match from OpenDota and:
  1) HEAD Valve default team_logos/{team_id}.png (Akamai + Cloudflare).
  2) For each side's team_id, GET /teams/{team_id}/matches, find this match_id, print
     opposing_team_logo and HEAD it when present (OpenDota's string URL for the opponent).

Run from repo root:  python backend/scripts/test_match_team_logos.py
"""
from __future__ import annotations

import sys

import requests

MATCH_ID = 8760881999
OPEN_DOTA = "https://api.opendota.com/api"
# Valve default assets (pro teams); many amateur team_ids 404 here — OpenDota may still expose logo_url when indexed.
TEAM_LOGO_TEMPLATES = (
    "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/{team_id}.png",
    "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/team_logos/{team_id}.png",
)
# OpenDota caps vary; raise if your match is old and not in the window.
TEAM_MATCHES_LIMIT = 10_000


def _head_image(url: str, ua: dict) -> tuple[int, str, bool]:
    r = requests.head(url, timeout=20, allow_redirects=True, headers=ua)
    ct = r.headers.get("content-type", "")
    ok = r.status_code == 200 and "image" in ct
    return r.status_code, ct, ok


def opposing_team_logo_from_match_list(team_id: int, match_id: int, ua: dict) -> tuple[dict | None, int]:
    """(row or None, n_rows) from GET /teams/{team_id}/matches."""
    r = requests.get(
        f"{OPEN_DOTA}/teams/{team_id}/matches",
        params={"limit": TEAM_MATCHES_LIMIT},
        timeout=120,
        headers=ua,
    )
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list):
        return None, -1
    for row in rows:
        if row.get("match_id") == match_id:
            return row, len(rows)
    return None, len(rows)


def main() -> None:
    m = requests.get(f"{OPEN_DOTA}/matches/{MATCH_ID}", timeout=45)
    m.raise_for_status()
    data = m.json()

    print(f"match_id={data.get('match_id')} radiant_team_id={data.get('radiant_team_id')} dire_team_id={data.get('dire_team_id')}")
    print(f"radiant_name={data.get('radiant_name')!r} dire_name={data.get('dire_name')!r}")
    print(f"radiant_logo={data.get('radiant_logo')!r} dire_logo={data.get('dire_logo')!r}")
    print()

    ua = {"User-Agent": "FantasyLeagueLogoTest/1.0"}
    print("--- Valve team_logos/{team_id}.png ---")
    for side, tid in (("radiant", data.get("radiant_team_id")), ("dire", data.get("dire_team_id"))):
        if not tid:
            print(f"{side}: no team_id, skip")
            continue
        print(f"{side} team_id={tid}")
        for tpl in TEAM_LOGO_TEMPLATES:
            url = tpl.format(team_id=tid)
            status, _ct, ok = _head_image(url, ua)
            mark = "OK" if ok else f"{status}"
            print(f"  [{mark}] {url}")

    print()
    print(f"--- opposing_team_logo (GET /teams/{{id}}/matches?limit={TEAM_MATCHES_LIMIT}) ---")
    for side, tid in (("radiant", data.get("radiant_team_id")), ("dire", data.get("dire_team_id"))):
        if not tid:
            print(f"{side}: no team_id, skip")
            continue
        print(f"{side} perspective team_id={tid}")
        try:
            row, n = opposing_team_logo_from_match_list(tid, MATCH_ID, ua)
        except requests.RequestException as e:
            print(f"  request failed: {e}")
            continue
        if n == -1:
            print("  unexpected JSON (not a list).")
            continue
        if n == 0:
            print("  OpenDota returned 0 matches for this team_id - no opposing_team_logo available.")
            continue
        if row is None:
            print(f"  fetched {n} matches but none match match_id={MATCH_ID} (raise TEAM_MATCHES_LIMIT or match not indexed).")
            continue
        logo = row.get("opposing_team_logo")
        print(f"  opposing_team_id={row.get('opposing_team_id')} opposing_team_name={row.get('opposing_team_name')!r}")
        print(f"  opposing_team_logo={logo!r}")
        if isinstance(logo, str) and logo.startswith(("http://", "https://")):
            status, ct, ok = _head_image(logo, ua)
            mark = "OK" if ok else f"{status} ct={ct!r}"
            print(f"  HEAD [{mark}]")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        sys.exit(1)
