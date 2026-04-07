import os
import time

import requests

from schedule import build_team_lookup, find_team_id, resolve_series_result

TOORNAMENT_CLIENT_ID     = os.getenv("TOORNAMENT_CLIENT_ID", "")
TOORNAMENT_CLIENT_SECRET = os.getenv("TOORNAMENT_CLIENT_SECRET", "")
TOORNAMENT_API_KEY       = os.getenv("TOORNAMENT_API_KEY", "")
TOORNAMENT_TOURNAMENT_ID = os.getenv("TOORNAMENT_TOURNAMENT_ID", "")

_BASE_URL   = "https://api.toornament.com/organizer/v2"
_OAUTH_URL  = "https://api.toornament.com/oauth/v2/token"

_token_cache: dict = {"access_token": None, "expires_at": 0.0}


def get_access_token() -> str:
    """Return a cached OAuth2 access token, refreshing if expired."""
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    resp = requests.post(_OAUTH_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     TOORNAMENT_CLIENT_ID,
        "client_secret": TOORNAMENT_CLIENT_SECRET,
        "scope":         "organizer:result",
    }, timeout=15)

    if resp.status_code != 200:
        raise RuntimeError(f"[TOORNAMENT] OAuth2 token request failed: {resp.status_code} {resp.text}")

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"]   = time.time() + data.get("expires_in", 3600) - 60
    return _token_cache["access_token"]


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "X-Api-Key":     TOORNAMENT_API_KEY,
    }


def fetch_tournament_matches(tournament_id: str) -> list[dict]:
    """Fetch all matches in a tournament, handling Range-based pagination."""
    matches = []
    page_size = 100
    offset = 0

    while True:
        range_header = f"objects={offset}-{offset + page_size - 1}"
        resp = requests.get(
            f"{_BASE_URL}/tournaments/{tournament_id}/matches",
            headers={**_auth_headers(), "Range": range_header},
            timeout=15,
        )
        if resp.status_code not in (200, 206):
            print(f"[TOORNAMENT] fetch_tournament_matches error: {resp.status_code} {resp.text}")
            break

        batch = resp.json()
        if not batch:
            break
        matches.extend(batch)

        # Check Content-Range to know if more pages remain
        content_range = resp.headers.get("Content-Range", "")
        # Format: "objects 0-99/250"
        try:
            total = int(content_range.split("/")[-1])
        except (ValueError, IndexError):
            break

        offset += len(batch)
        if offset >= total:
            break

    return matches


def push_match_result(tournament_id: str, match_id: str, opponents: list[dict]) -> bool:
    """PATCH a toornament match with updated scores and results. Returns True on success."""
    try:
        resp = requests.patch(
            f"{_BASE_URL}/tournaments/{tournament_id}/matches/{match_id}",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json={"opponents": opponents},
            timeout=15,
        )
        if resp.status_code in (200, 204):
            return True
        print(f"[TOORNAMENT] push_match_result {match_id} failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[TOORNAMENT] push_match_result {match_id} exception: {e}")
        return False


def _is_configured() -> bool:
    return all([TOORNAMENT_CLIENT_ID, TOORNAMENT_CLIENT_SECRET,
                TOORNAMENT_API_KEY, TOORNAMENT_TOURNAMENT_ID])


def sync_toornament_results(db, dry_run: bool = False) -> dict:
    """Push match results from our DB to toornament.com.

    Returns {"pushed": int, "skipped": int, "errors": list[str]}.
    When dry_run=True, logs what would be pushed but skips the actual PATCH.
    """
    from models import ToornamentSyncLog

    result = {"pushed": 0, "skipped": 0, "errors": []}

    if not _is_configured():
        print("[TOORNAMENT] Not configured (missing env vars), skipping sync.")
        return result

    try:
        team_lookup = build_team_lookup(db)
        toornament_matches = fetch_tournament_matches(TOORNAMENT_TOURNAMENT_ID)
    except Exception as e:
        msg = f"Setup error: {e}"
        print(f"[TOORNAMENT] {msg}")
        result["errors"].append(msg)
        return result

    for tm in toornament_matches:
        match_id = tm.get("id")
        status   = tm.get("status", "")
        opponents = tm.get("opponents") or []

        if status not in ("running", "completed"):
            result["skipped"] += 1
            continue

        if len(opponents) != 2:
            result["skipped"] += 1
            continue

        opp0 = opponents[0] or {}
        opp1 = opponents[1] or {}
        part0 = opp0.get("participant") or {}
        part1 = opp1.get("participant") or {}
        name0 = part0.get("name")
        name1 = part1.get("name")

        if not name0 or not name1:
            result["skipped"] += 1
            continue

        tid0 = find_team_id(name0, team_lookup)
        tid1 = find_team_id(name1, team_lookup)
        if not tid0 or not tid1:
            print(f"[TOORNAMENT] Could not map teams '{name0}' / '{name1}' to DB — skipping match {match_id}")
            result["skipped"] += 1
            continue

        series = resolve_series_result(db, name0, name1, team_lookup)
        if not series or series["game_count"] == 0:
            result["skipped"] += 1
            continue

        score0 = series["team1_wins"]
        score1 = series["team2_wins"]

        def _result_str(a, b):
            if a > b:
                return "win"
            if a < b:
                return "loss"
            return "draw"

        new_opponents = [
            {"score": score0, "result": _result_str(score0, score1)},
            {"score": score1, "result": _result_str(score1, score0)},
        ]

        # Idempotency: skip if toornament already has these exact scores
        existing_score0 = opp0.get("score")
        existing_score1 = opp1.get("score")
        existing_result0 = opp0.get("result")
        existing_result1 = opp1.get("result")
        if (existing_score0 == score0 and existing_score1 == score1
                and existing_result0 == new_opponents[0]["result"]
                and existing_result1 == new_opponents[1]["result"]):
            result["skipped"] += 1
            continue

        if dry_run:
            print(f"[TOORNAMENT][DRY RUN] Would push match {match_id}: "
                  f"'{name0}' {score0} – {score1} '{name1}'")
            result["pushed"] += 1
            continue

        success = push_match_result(TOORNAMENT_TOURNAMENT_ID, match_id, new_opponents)
        if success:
            # Upsert sync log
            try:
                log_row = db.query(ToornamentSyncLog).filter(
                    ToornamentSyncLog.toornament_match_id == match_id
                ).first()
                if log_row is None:
                    log_row = ToornamentSyncLog(toornament_match_id=match_id)
                    db.add(log_row)
                log_row.team1_name  = name0
                log_row.team2_name  = name1
                log_row.team1_score = score0
                log_row.team2_score = score1
                log_row.pushed_at   = int(time.time())
                db.commit()
            except Exception as e:
                print(f"[TOORNAMENT] Log upsert failed for match {match_id}: {e}")

            print(f"[TOORNAMENT] Pushed match {match_id}: '{name0}' {score0} – {score1} '{name1}'")
            result["pushed"] += 1
        else:
            msg = f"Push failed for match {match_id} ('{name0}' vs '{name1}')"
            result["errors"].append(msg)

    return result
