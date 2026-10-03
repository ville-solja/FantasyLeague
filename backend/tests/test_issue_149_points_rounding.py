"""Tests for plan-issue-149-points-rounding (GitHub issue #149).

Every displayed points value is rounded once, on the server, by
`scoring.display_points(x, places=1)`: one decimal, half away from zero
(`ROUND_HALF_UP` on `Decimal(repr(float(x)))`), None -> 0.0. Totals are rounded
from their exact sums, never added up from rounded card values. The frontend
only formats the server's value with `toFixed(1)`.

Fixture approach:
- Helper unit cases call `scoring.display_points` directly (no db).
- Reader tests seed users/players/cards/weeks/roster entries/matches/stats
  directly into the `db` fixture, together with `card_match_points` rows holding
  chosen exact values (no `rebuild_all`, so the stored points are exactly the
  halfway cases below), and call readers as plain functions: `routers.cards._build_roster_response(db, uid, week_id)`,
  `routers.leaderboard.weekly_leaderboard(week_id=..., db=db)`,
  `routers.leaderboard.compute_season_standings(db)`, `season_leaderboard(db=db)`,
  `top_performances(db=db)`, `leaderboard(db=db)`, `archived_season_detail(...)`,
  `simulate_match(...)`, `routers.weekly_summary._build_week_summary(...)` and
  `twitch.current_matches` (via the `_current(db)` / `twitch_env` pattern in
  test_issue_139_early_mvp_selection.py). Seed stored points such as 2.25 or
  240.45 where Python's `round(x, 1)` / `round(x, 2)` + JS `toFixed(1)` disagree
  with `display_points`, so the tests distinguish the old and new behaviour.
- Benchmark-season consistency: `scripts/bench_leaderboards.py` sets
  DATABASE_URL to its own temp file *at import* and binds the module-level
  `database.engine` / `SessionLocal`. Inside pytest, `database` is already
  imported (bound to another URL), so importing the bench module in-process
  would seed the wrong database. The comparison therefore runs in a
  subprocess (`sys.executable -c ...`, cwd = repo root, env with
  BACKGROUND_TASKS_ENABLED=false and DEBUG=true) that imports
  `bench_leaderboards`, calls `seed(60, 10, 8, 5, 2, 15, 5, random.Random(141))`
  (the script's defaults, which already ends with `card_points.rebuild_all`),
  then compares `_build_roster_response(db, uid, wk)["combined_value"]` with
  `weekly_leaderboard(wk, db=db)` `week_points` for every user and week, and
  `season_points` with `compute_season_standings(db)` `points` for every user,
  printing the mismatches as JSON for the test to assert on (expect []).
  `main` is never imported or reloaded.
- Source search: parse backend/routers/*.py and backend/twitch.py with `ast`,
  collect every `round(...)` call (`ast.Call` whose func is `Name("round")`) with
  `ast.get_source_segment`, and fail on any call not in an explicit allowlist of
  non-display rounds. The allowlist (file, segment) starts with
  `routers/admin_ingest.py`: `round(stat.fantasy_points * (1 + bonus_pct / 100), 4)`
  (a stored value, not a displayed one). Any new entry needs a reason comment.
- Frontend checks are static reads of frontend/*.js and frontend/index.html
  (How to Play pinned phrases in test_how_to_play_role_subtabs.py and
  test_issue_103_team_draw_explanation.py must stay intact).
- Manual: compare My Team and the weekly leaderboard on test.kana-cards.com;
  bench timings via `scripts/bench_leaderboards.py --compare`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ast
import json
import re
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from models import (
    Card, CardMatchPoints, Match, Player, PlayerMatchStats, SeasonArchive, Team, User, Week,
    WeeklyRosterEntry,
)
from scoring import display_points

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"

# Stored per-card points (week 1 = [0, 1000], locked). alice's chips round to
# 2.3 + 1.1 + 1.1 = 4.5 while her exact total 4.37 rounds to 4.4; bob's single
# card is the issue's 240.45 case (old round(x, 2) + toFixed(1) showed 240.4).
_ALICE_CARDS = {1: 2.25, 2: 1.05, 3: 1.07}
_BOB_CARDS = {4: 240.45}


def _seed_points(db):
    db.add(User(id=1, username="alice", email="a@test", password_hash="x", tokens=0))
    db.add(User(id=2, username="bob", email="b@test", password_hash="x", tokens=0))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    for pid in (101, 102, 103):
        db.add(Player(id=pid, name=f"P{pid}"))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=1000, is_locked=True))
    db.add(Match(match_id=1, radiant_team_id=1, dire_team_id=2, start_time=100, radiant_win=True))
    for card_id, owner, pid, slot in ((1, 1, 101, 0), (2, 1, 102, 1), (3, 1, 103, 2), (4, 2, 101, 0)):
        db.add(Card(id=card_id, player_id=pid, owner_id=owner, card_type="common",
                    is_active=True, slot_index=slot))
        db.add(WeeklyRosterEntry(week_id=1, user_id=owner, card_id=card_id))
    for card_id, pts in {**_ALICE_CARDS, **_BOB_CARDS}.items():
        pid = {1: 101, 2: 102, 3: 103, 4: 101}[card_id]
        db.add(CardMatchPoints(card_id=card_id, match_id=1, player_id=pid, points=pts))
    db.commit()


def _exact(cards: dict) -> float:
    return sum(cards.values())


_BENCH_SCRIPT = r"""
import json, random, sys
sys.path.insert(0, "scripts")
import bench_leaderboards as b
from database import SessionLocal
from models import User
from routers.cards import _build_roster_response
from routers.leaderboard import compute_season_standings, weekly_leaderboard

info = b.seed(60, 10, 8, 5, 2, 15, 5, random.Random(141))
db = SessionLocal()
try:
    uids = [u for (u,) in db.query(User.id).filter(User.is_tester == False).order_by(User.id)]  # noqa: E712
    week_mm, user_weeks = [], 0
    for wk in info["weeks"]:
        lb = {r["id"]: r["week_points"] for r in weekly_leaderboard(wk, db=db)}
        for uid in uids:
            user_weeks += 1
            mine = _build_roster_response(db, uid, wk)["combined_value"]
            if mine != lb.get(uid):
                week_mm.append([wk, uid, mine, lb.get(uid)])
    season = {r["id"]: r["points"] for r in compute_season_standings(db)}
    season_mm = []
    for uid in uids:
        mine = _build_roster_response(db, uid, info["weeks"][-1])["season_points"]
        if mine != season.get(uid):
            season_mm.append([uid, mine, season.get(uid)])
finally:
    db.close()
print(json.dumps({"user_weeks": user_weeks, "users": len(uids),
                  "week_mismatches": week_mm, "season_mismatches": season_mm}))
"""

_bench_cache: dict = {}


def _bench_comparison() -> dict:
    """Run the seed-141 benchmark season once, in a subprocess (see the module docstring)."""
    if "result" not in _bench_cache:
        env = {**os.environ, "BACKGROUND_TASKS_ENABLED": "false", "DEBUG": "true"}
        env.pop("DATABASE_URL", None)
        proc = subprocess.run([sys.executable, "-c", _BENCH_SCRIPT], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, proc.stderr[-4000:]
        _bench_cache["result"] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _bench_cache["result"]

# ---------------------------------------------------------------------------
# Story 1 — Same Week Points Everywhere
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (240.45, 240.5),
    (231.25, 231.3),
    (227.35, 227.4),
    (0.05, 0.1),
    (-0.05, -0.1),
    (2.675, 2.7),
])
def test_display_points_rounds_half_away_from_zero_on_decimal_value(value, expected):
    """AC: display_points rounds to one decimal, half away from zero, on Decimal(repr(x)) (240.45 -> 240.5, -0.05 -> -0.1)."""
    assert display_points(value) == expected


def test_display_points_places_two():
    """AC: display_points(2.675, places=2) == 2.68 (binary round(2.675, 2) gives 2.67)."""
    assert round(2.675, 2) == 2.67  # the binary artefact the helper avoids
    assert display_points(2.675, places=2) == 2.68


def test_display_points_none_returns_zero():
    """AC (invalid input): display_points(None) returns 0.0 (a float), not an error."""
    result = display_points(None)
    assert result == 0.0 and isinstance(result, float)


def test_display_points_avoids_double_rounding_artefact():
    """AC: display_points(240.4506) == 240.5, whereas round(240.4506, 2) then 1-decimal display gives 240.4."""
    old = round(round(240.4506, 2), 1)  # server round(x, 2), then a one-decimal display
    assert old == 240.4
    assert display_points(240.4506) == 240.5


def test_build_roster_response_values_rounded_once_from_exact_sum(db):
    """AC: My Team's combined_value, season_points and each card's total_points equal display_points of the exact stored sum."""
    from routers.cards import _build_roster_response
    _seed_points(db)

    alice = _build_roster_response(db, 1, 1)
    assert alice["combined_value"] == display_points(_exact(_ALICE_CARDS)) == 4.4
    assert alice["season_points"] == 4.4
    assert {c["id"]: c["total_points"] for c in alice["active"]} == {1: 2.3, 2: 1.1, 3: 1.1}
    # Rounded once from the exact sum, not added up from the rounded cards (4.5).
    assert sum(c["total_points"] for c in alice["active"]) == pytest.approx(4.5)

    bob = _build_roster_response(db, 2, 1)
    assert bob["combined_value"] == bob["season_points"] == 240.5
    assert bob["active"][0]["total_points"] == 240.5


def test_build_roster_response_no_scored_points_returns_zero(db):
    """AC (failure path): a user with no scored matches gets combined_value, season_points and total_points of 0.0, not None."""
    from routers.cards import _build_roster_response
    _seed_points(db)
    db.add(User(id=3, username="carol", email="c@test", password_hash="x", tokens=0))
    db.add(Card(id=5, player_id=102, owner_id=3, card_type="common", is_active=True, slot_index=0))
    db.add(WeeklyRosterEntry(week_id=1, user_id=3, card_id=5))
    db.commit()

    carol = _build_roster_response(db, 3, 1)
    assert carol["combined_value"] == 0.0 and isinstance(carol["combined_value"], float)
    assert carol["season_points"] == 0.0 and isinstance(carol["season_points"], float)
    assert [c["total_points"] for c in carol["active"]] == [0.0]


def test_leaderboard_rows_total_rounded_from_exact_sum_not_rounded_cards(db):
    """AC: weekly/season totals are display_points(exact sum) and each card chip's points is display_points(card sum), even when the chips' sum differs by 0.1."""
    from routers.leaderboard import compute_season_standings, weekly_leaderboard
    _seed_points(db)

    weekly = {r["username"]: r for r in weekly_leaderboard(week_id=1, db=db)}
    assert weekly["alice"]["week_points"] == display_points(_exact(_ALICE_CARDS)) == 4.4
    chips = sorted(c["points"] for c in weekly["alice"]["cards"])
    assert chips == [1.1, 1.1, 2.3]
    assert sum(chips) == pytest.approx(4.5)  # the documented 0.1 card-sum difference
    assert weekly["bob"]["week_points"] == 240.5
    assert [c["points"] for c in weekly["bob"]["cards"]] == [240.5]

    season = {r["username"]: r for r in compute_season_standings(db)}
    assert season["alice"]["points"] == 4.4
    assert sorted(c["points"] for c in season["alice"]["cards"]) == [1.1, 1.1, 2.3]
    assert season["bob"]["points"] == 240.5


def test_weekly_leaderboard_unknown_week_returns_404(db):
    """AC (failure path): the weekly leaderboard for a missing week still raises 404 after the rounding change."""
    from routers.leaderboard import weekly_leaderboard
    with pytest.raises(HTTPException) as exc:
        weekly_leaderboard(week_id=999, db=db)
    assert exc.value.status_code == 404


def test_benchmark_season_roster_week_total_equals_weekly_leaderboard():
    """AC: for every user and week of the seed-141 benchmark season, My Team's combined_value equals the weekly leaderboard's week_points exactly (0 of 600 mismatches; subprocess run)."""
    result = _bench_comparison()
    assert result["user_weeks"] == 600
    assert result["week_mismatches"] == []


def test_benchmark_season_roster_season_points_equals_season_leaderboard():
    """AC: for every benchmark-season user, My Team's season_points equals the season leaderboard total exactly (subprocess run)."""
    result = _bench_comparison()
    assert result["users"] == 60
    assert result["season_mismatches"] == []


_BROADCASTER = {"channel_id": "test_channel", "role": "broadcaster", "opaque_user_id": "Utest"}


@pytest.fixture(autouse=True)
def _twitch_env(monkeypatch):
    """No real Twitch calls (PubSub/chat short-circuit under TWITCH_LOCAL_DEV)."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)


# Non-display rounds: (file relative to backend/, source segment).
_ROUND_ALLOWLIST = [
    # Stores the MVP-boosted fantasy_points at 4 decimals; never shown as-is.
    ("routers/admin_ingest.py", "round(stat.fantasy_points * (1 + bonus_pct / 100), 4)"),
]


def _round_calls() -> list[tuple[str, str]]:
    files = sorted((BACKEND / "routers").glob("*.py")) + [BACKEND / "twitch.py"]
    calls = []
    for path in files:
        src = path.read_text()
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "round"):
                calls.append((path.relative_to(BACKEND).as_posix(), ast.get_source_segment(src, node)))
    return calls


_POINTS_KEY = re.compile(
    r"\b(points|week_points|season_points|combined_value|total_points|avg_points|fantasy_points)\b"
    r"|\[ptsKey\]")
_POINTS_ACCESS = re.compile(
    r"\.(points|week_points|season_points|combined_value|total_points|avg_points|fantasy_points)\b"
    r"|\[ptsKey\]")


def _points_lines():
    """(file, line) for every frontend JS line that renders a points value."""
    for path in sorted(FRONTEND.glob("*.js")):
        for line in path.read_text().splitlines():
            if "${" in line and _POINTS_ACCESS.search(line):
                yield path.name, line
            elif "textContent" in line and re.search(r"\b(season_points|combined_value)\b", line):
                yield path.name, line



# ---------------------------------------------------------------------------
# Story 2 — One Rounding Rule for All Points
# ---------------------------------------------------------------------------

def test_twitch_current_matches_player_points_use_display_points(db):
    """AC: GET /twitch/matches/current player fantasy_points use display_points (stored 2.25 -> 2.3, where round(2.25, 1) gives 2.2)."""
    import twitch
    now = int(time.time())
    db.add(Team(id=11, name="Alpha"))
    db.add(Team(id=12, name="Beta"))
    db.add(Player(id=500, name="Halfway"))
    db.add(Match(match_id=7001, radiant_team_id=11, dire_team_id=12, start_time=now - 3600,
                 radiant_win=True))
    db.add(PlayerMatchStats(player_id=500, match_id=7001, team_id=11, fantasy_points=2.25,
                            kills=3, is_mvp=False))
    db.commit()

    result = twitch.current_matches(payload=dict(_BROADCASTER), db=db)
    players = [p for s in result["series"] for m in s["matches"] for p in m["players"]]
    assert round(2.25, 1) == 2.2
    assert [p["fantasy_points"] for p in players] == [2.3]


def test_weekly_summary_match_points_use_display_points(db):
    """AC: Weekly Report per-match points use display_points (2.25 -> 2.3)."""
    from routers.weekly_summary import _build_week_summary
    _seed_points(db)
    db.add(PlayerMatchStats(player_id=101, match_id=1, team_id=1, fantasy_points=2.25, is_mvp=False))
    db.commit()

    summary = _build_week_summary(db, db.get(Week, 1), True, 1)
    players = [p for s in summary["series"] for m in s["matches"] for p in m["players"]]
    assert [p["points"] for p in players] == [2.3]


def test_weekly_summary_excluded_match_points_still_none(db):
    """AC (failure path): an excluded/unparsed match's per-match points stay None rather than display_points(None) == 0.0."""
    from routers.weekly_summary import _build_week_summary
    _seed_points(db)
    db.add(PlayerMatchStats(player_id=101, match_id=1, team_id=1, fantasy_points=2.25, is_mvp=False))
    db.get(Match, 1).excluded_from_scoring = True
    db.commit()

    summary = _build_week_summary(db, db.get(Week, 1), True, 1)
    players = [p for s in summary["series"] for m in s["matches"] for p in m["players"]]
    assert [p["points"] for p in players] == [None]


def test_top_and_leaderboard_points_use_display_points(db):
    """AC: /top fantasy_points and /leaderboard avg_points are display_points of the stored/averaged value."""
    from routers.leaderboard import leaderboard, top_performances
    db.add(Team(id=1, name="Radiant"))
    db.add(Player(id=101, name="P101"))
    for match_id, pts in ((1, 2.2), (2, 2.3), (3, 2.25)):
        db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=1, start_time=100 * match_id))
        db.add(PlayerMatchStats(player_id=101, match_id=match_id, team_id=1, fantasy_points=pts))
    db.commit()

    top = top_performances(db=db)
    assert sorted(r["fantasy_points"] for r in top) == [2.2, 2.3, 2.3]

    # The average of 2.2, 2.3 and 2.25 is 2.25 (round(2.25, 1) gives 2.2).
    rows = leaderboard(db=db)
    assert [r["avg_points"] for r in rows] == [2.3]


def test_archived_season_standings_points_use_display_points(db):
    """AC: archived season standings (End Season archive / GET /leaderboard/seasons/{id}) carry display_points values."""
    from routers.leaderboard import archived_season_detail
    db.add(SeasonArchive(id=1, season_label="S1", user_id=1, username="alice", points=240.45,
                         rank=1, archived_at=1000))
    db.commit()

    detail = archived_season_detail(1, db=db)
    assert [r["points"] for r in detail["standings"]] == [240.5]


def test_simulate_match_uses_display_points_two_places(db):
    """AC: /simulate player fantasy_points use display_points(x, places=2) (a score of 2.675 -> 2.68)."""
    from routers.leaderboard import SimulateBody, simulate_match
    db.add(Player(id=101, name="P101"))
    db.add(Match(match_id=1, start_time=100))
    db.add(PlayerMatchStats(player_id=101, match_id=1, kills=1, deaths=0, fantasy_points=0.0))
    db.commit()

    result = simulate_match(1, db=db, body=SimulateBody(kills=2.675))
    assert [p["fantasy_points"] for p in result["players"]] == [2.68]


def test_simulate_match_unknown_match_returns_404(db):
    """AC (failure path): /simulate for a missing match still raises 404."""
    from routers.leaderboard import simulate_match
    with pytest.raises(HTTPException) as exc:
        simulate_match(999, db=db, body=None)
    assert exc.value.status_code == 404


def test_no_points_round_in_routers_or_twitch_source():
    """AC: no `round(` on a points value remains in backend/routers/*.py or backend/twitch.py (ast search; non-display rounds allowlisted)."""
    unexpected = [call for call in _round_calls() if call not in _ROUND_ALLOWLIST]
    assert unexpected == []


def test_round_allowlist_entries_still_present():
    """AC (failure path): every allowlisted non-display round(...) still exists in source, so a stale allowlist cannot hide a new points round."""
    calls = _round_calls()
    assert [entry for entry in _ROUND_ALLOWLIST if entry not in calls] == []


def test_frontend_points_only_formatted_with_tofixed_one():
    """AC: frontend points values (points, week_points, season_points, combined_value, total_points, avg_points, fantasy_points) are shown only via Number(...).toFixed(1)."""
    lines = list(_points_lines())
    assert lines
    for name, line in lines:
        assert "toFixed(1)" in line, f"{name}: points shown without toFixed(1): {line.strip()}"
    lb = (FRONTEND / "app-leaderboard.js").read_text()
    roster = (FRONTEND / "app-roster.js").read_text()
    summary = (FRONTEND / "app-weekly-summary.js").read_text()
    assert "Number(r[ptsKey] || 0).toFixed(1)" in lb
    assert "Number(c.points).toFixed(1)" in lb
    assert "Number(combined_value).toFixed(1)" in roster
    assert "Number(season_points).toFixed(1)" in roster
    assert "Number(p.points).toFixed(1)" in summary


def test_frontend_has_no_other_points_rounding():
    """AC (failure path): no Math.round/floor/ceil, toPrecision or toFixed(n != 1) is applied to a points value in frontend JS (gold_per_min, avg_gpm, win_rate allowlisted)."""
    rounding = re.compile(r"Math\.(round|floor|ceil)\(|toPrecision\(|toFixed\((?!1\))")
    allowed = ("gold_per_min", "avg_gpm", "win_rate")
    offenders = []
    for path in sorted(FRONTEND.glob("*.js")):
        for line in path.read_text().splitlines():
            if rounding.search(line) and _POINTS_KEY.search(line) and not any(a in line for a in allowed):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []


# ---------------------------------------------------------------------------
# Story 3 — Explain Card Totals
# ---------------------------------------------------------------------------

_FOOTNOTE = "Totals are rounded from exact points, so card values may differ by 0.1 in sum"


def _standings_row_source() -> str:
    lb = (FRONTEND / "app-leaderboard.js").read_text()
    start = lb.index("function _lbStandingsRow(")
    return lb[start:lb.index("\n}\n", start)]


def _howtoplay_panel(name: str) -> str:
    html = (FRONTEND / "index.html").read_text()
    start = html.index(f'id="howtoplay-panel-{name}"')
    nxt = html.find('id="howtoplay-panel-', start + 1)
    return html[start:nxt if nxt != -1 else len(html)]


def test_leaderboard_card_list_has_rounding_footnote():
    """AC: where app-leaderboard.js lists a user's cards under their total (the card detail row), the one-line footnote text appears."""
    src = _standings_row_source()
    detail = src[src.index("const detailRow"):]
    assert _FOOTNOTE in detail


def test_leaderboard_footnote_not_shown_without_card_list():
    """AC (failure path): the footnote is only in the card-list branch (after `if (!hasCards) return mainRow;`), so rows without cards, e.g. the season standings, show no note."""
    src = _standings_row_source()
    guard = src.index("if (!hasCards) return mainRow;")
    assert _FOOTNOTE not in src[:guard]
    lb = (FRONTEND / "app-leaderboard.js").read_text()
    assert lb.count(_FOOTNOTE) == 1
    # Season standings pass showCards=false, so their rows never reach the card list.
    assert '_lbStandingsRow(r, i, "season_points", false)' in lb


def test_how_to_play_scoring_section_has_rounding_note_once():
    """AC: the How to Play scoring section (Users panel, 'Scoring & Modifiers') contains the note exactly once."""
    users = _howtoplay_panel("users")
    scoring = users[users.index("Scoring &amp; Modifiers"):]
    assert scoring.count(_FOOTNOTE) == 1
    assert users.count(_FOOTNOTE) == 1


def test_how_to_play_rounding_note_not_duplicated_in_other_panels():
    """AC (failure path): the note appears in no other How to Play panel (players/streamers/developers), and pinned phrases ('Draw a card', '5 cards', 'locks automatically') remain."""
    for panel in ("players", "streamers", "developers"):
        assert _FOOTNOTE not in _howtoplay_panel(panel), panel
    html = (FRONTEND / "index.html").read_text()
    assert html.count(_FOOTNOTE) == 1
    for phrase in ("Draw a card", "5 cards", "locks automatically"):
        assert phrase in html
