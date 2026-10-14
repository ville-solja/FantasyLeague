"""
Tests for plan-issue-189-retroactive-bench-substitution.md (resolves GitHub issue #189).

A one-off operator backfill: `backend/scripts/backfill_bench.py` adds bench rows
(`weekly_roster_entries.is_bench = 1`) to weeks locked before benches were saved at lock
(#129), then runs `weeks.run_substitutions`. No endpoint, schema change or UI.

  Story 1: Operator Backfills the Bench for Earlier Weeks
  Story 2: Bench Uses Only Cards the User Provably Had

Functions under test:
  - `weeks.backfill_bench_candidates(db, week) -> {user_id: [card_id, ...]}` in bench order
  - `weeks.backfill_bench(db, week) -> (users, bench_cards, substitutions)`; raises
    `ValueError` when the week already has bench rows; the caller commits
  - `scripts/backfill_bench.py`: `--weeks "Week 2,Week 3"` (label or id), `--dry-run`;
    exit 1 for an unknown week, else 0; one `admin_bench_backfill` audit entry per
    applied week (`actor_username=script`, detail has id, label, users, bench_cards,
    substitutions)

Approach notes:

- `db` fixture from conftest (in-memory SQLite, `Base.metadata.create_all`).
- Seed like `_seed` in test_issue_129_automatic_bench_substitution.py: weights, users,
  teams, players, cards (`slot_index` set), weeks, matches + stats, then
  `card_points.rebuild_all(db)` so readers see stored `card_match_points`.
- Proof of ownership is a lock-time snapshot: insert `WeeklyRosterEntry(is_bench=False)`
  rows directly for weeks 1..N (as pre-#129 locks did; no bench rows), set
  `is_locked=True` and `substitutions_at` (the first #129 deploy stamped those weeks).
- Clock: weeks.py reads "now" via `clock.now(db)`; control it with
  `patch("clock.time.time", return_value=T)`. Set SUBSTITUTION_DELAY_HOURS with
  `monkeypatch.setenv`.
- Script tests: `_run` calls the script's `main(argv)` with `database.SessionLocal`
  patched to return the test session and captures stdout with `capsys`. A dry run does
  each week's work in the session and rolls it back before any commit.
- Readers for the "after applying" criteria: `routers.cards._build_roster_response`,
  `routers.leaderboard.weekly_leaderboard(week_id=..., db=db)`,
  `routers.leaderboard.compute_season_standings(db)`.

Run with: cd backend && python -m pytest tests/test_issue_189_retroactive_bench_substitution.py -v
"""

import importlib.util
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import text

import card_points
import models  # noqa: F401  (registers every table for the db fixture)
import weeks
from models import (
    AuditLog, Card, Match, Player, PlayerMatchStats, Team, User, Week, WeeklyRosterEntry,
    Weight,
)
from routers.cards import _build_roster_response
from routers.leaderboard import compute_season_standings, weekly_leaderboard
from scoring import display_points, fantasy_score

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backfill_bench.py"
_spec = importlib.util.spec_from_file_location("backfill_bench_script", _SCRIPT)
backfill_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_script)

_WEIGHTS = {
    "kills": 0.3, "gold_per_min": 0.002,
    "death_pool": 3.0, "death_deduction": 0.3, "mvp_bonus_pct": 10.0,
    "rarity_common": 0.0, "rarity_rare": 1.0, "rarity_epic": 2.0, "rarity_legendary": 3.0,
    "modifier_count_common": 0.0, "modifier_count_rare": 1.0, "modifier_count_epic": 2.0,
    "modifier_count_legendary": 3.0, "modifier_bonus_pct": 10.0, "team_booster_cost": 3.0,
}

A, B, C, D, E, F, G = 101, 102, 103, 104, 105, 106, 107
_WEEKS = [(1, "Week 1", 0, 1000), (2, "Week 2", 1001, 2000), (3, "Week 3", 2001, 3000),
          (4, "Week 4", 3001, 4000)]
NOW = 1_000_000  # well past every week's substitution time

# Default scenario (pre-#129 snapshots: roster rows only, no bench rows):
#   alice (1): W1 [1 A, 2 B], W2 [1 A, 3 C], W3 [1 A, 7 G]; card 4 (D) never rostered.
#   bob   (2): W1 [5 E, 6 F], W2 [5 E], W3 [5 E].
#   carol (3): W1-W3 [8 A]; card 9 (B) never rostered (roster never changed).
# Week 2 matches: A, B, F play; C and E don't -> alice C out / B in, bob E out / F in.
_CARDS = [  # (card_id, owner_id, player_id, is_active, slot_index)
    (1, 1, A, True, 0), (2, 1, B, False, 1), (3, 1, C, True, 1), (4, 1, D, False, 0),
    (7, 1, G, False, 2), (5, 2, E, True, 0), (6, 2, F, False, 0),
    (8, 3, A, True, 0), (9, 3, B, False, 0),
]
_SNAPSHOTS = {
    1: {1: [1, 2], 2: [5, 6], 3: [8]},
    2: {1: [1, 3], 2: [5], 3: [8]},
    3: {1: [1, 7], 2: [5], 3: [8]},
}
_MATCHES = [  # (match_id, start_time, {player_id: (kills, deaths, gpm)})
    (1, 100, {A: (5, 2, 437), B: (3, 1, 391), E: (2, 2, 400), F: (1, 0, 350)}),
    (2, 1100, {A: (2, 1, 403), B: (4, 0, 455), F: (6, 0, 512)}),
    (3, 2100, {A: (1, 1, 300), C: (2, 2, 380), E: (3, 1, 420), G: (4, 0, 470)}),
]
_USERS = [(1, "alice"), (2, "bob"), (3, "carol")]


def _seed(db, cards=_CARDS, snapshots=_SNAPSHOTS, matches=_MATCHES, users=_USERS,
          locked=(1, 2, 3)):
    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    for uid, name in users:
        db.add(User(id=uid, username=name, email=f"{name}@test", password_hash="x", tokens=5))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    for pid in (A, B, C, D, E, F, G):
        db.add(Player(id=pid, name=f"P{pid}", is_active=True))
    for cid, owner, pid, active, slot in cards:
        db.add(Card(id=cid, player_id=pid, owner_id=owner, card_type="common",
                    is_active=active, slot_index=slot))
    for wid, label, start, end in _WEEKS:
        # The first #129 deploy stamped substitutions_at on the old locked weeks.
        db.add(Week(id=wid, label=label, start_time=start, end_time=end,
                    is_locked=wid in locked, substitutions_at=5000 if wid in locked else None))
    db.flush()
    for wid, by_user in snapshots.items():
        for uid, card_ids in by_user.items():
            for cid in card_ids:
                db.add(WeeklyRosterEntry(week_id=wid, user_id=uid, card_id=cid, is_bench=False))
    for match_id, start, players in matches:
        db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=2, start_time=start,
                     radiant_win=True, league_id=1))
        for pid, (kills, deaths, gpm) in players.items():
            stats = {"kills": kills, "deaths": deaths, "gold_per_min": gpm}
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=1,
                                    fantasy_points=round(fantasy_score(stats, _WEIGHTS), 4),
                                    is_mvp=False, **stats))
    db.commit()
    card_points.rebuild_all(db)


def _week(db, wid):
    return db.get(Week, wid)


def _candidates(db, wid):
    return weeks.backfill_bench_candidates(db, _week(db, wid))


def _apply(db, wid):
    result = weeks.backfill_bench(db, _week(db, wid))
    db.commit()
    return result


def _entries(db, wid, uid):
    return {e.card_id: e for e in db.query(WeeklyRosterEntry).filter_by(week_id=wid, user_id=uid)}


def _card_week_pts(db, card_id, wid):
    w = _week(db, wid)
    return db.execute(text("""
        SELECT COALESCE(SUM(cmp.points), 0) FROM card_match_points cmp
        JOIN matches m ON m.match_id = cmp.match_id
        WHERE cmp.card_id = :cid AND m.start_time BETWEEN :ws AND :we
    """), {"cid": card_id, "ws": w.start_time, "we": w.end_time}).scalar()


def _week_points(db, wid):
    return {r["username"]: r["week_points"] for r in weekly_leaderboard(week_id=wid, db=db)}


def _audits(db, action):
    return db.query(AuditLog).filter_by(action=action).all()


def _state(db):
    """Everything a dry run must leave unchanged."""
    rows = [(e.id, e.week_id, e.user_id, e.card_id, bool(e.is_bench), e.bench_order,
             bool(e.subbed_in), bool(e.subbed_out), e.subbed_for_entry_id)
            for e in db.query(WeeklyRosterEntry).order_by(WeeklyRosterEntry.id)]
    audits = [(a.action, a.detail) for a in db.query(AuditLog).order_by(AuditLog.id)]
    subs_at = [(w.id, w.substitutions_at) for w in db.query(Week).order_by(Week.id)]
    return rows, audits, subs_at


def _run(db, capsys, *argv, now=NOW):
    """Call the script's main() on the test session; returns (exit code, stdout)."""
    capsys.readouterr()
    with patch("database.SessionLocal", return_value=db), \
            patch("clock.time.time", return_value=now):
        code = backfill_script.main(list(argv))
    return code, capsys.readouterr().out


def _block(out, label):
    """The report block of one week: its header line and the indented user lines."""
    lines = out.splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith(f"{label}:"))
    block = [lines[i]]
    for line in lines[i + 1:]:
        if not line.startswith("  "):
            break
        block.append(line)
    return block


_USER_LINE = re.compile(r"^  (\S+): (\S+) -> (\S+) \(([+-][\d.]+)\)$")


# ---------------------------------------------------------------------------
# Story 1: Operator Backfills the Bench for Earlier Weeks
# ---------------------------------------------------------------------------

class TestBackfillBenchApply:
    """weeks.backfill_bench(db, week)."""

    def test_backfill_bench_inserts_bench_rows_with_bench_order(self, db):
        """Apply inserts the candidate rows with is_bench = 1 and bench_order 0..n per user."""
        _seed(db)
        with patch("clock.time.time", return_value=NOW):
            _apply(db, 3)
        bench = (db.query(WeeklyRosterEntry)
                 .filter_by(week_id=3, is_bench=True)
                 .order_by(WeeklyRosterEntry.user_id, WeeklyRosterEntry.bench_order).all())
        assert [(e.user_id, e.card_id, e.bench_order) for e in bench] == [
            (1, 2, 0), (1, 3, 1), (2, 6, 0)]
        # Roster rows are untouched; other weeks get nothing.
        assert db.query(WeeklyRosterEntry).filter_by(week_id=3, is_bench=False).count() == 4
        assert db.query(WeeklyRosterEntry).filter(
            WeeklyRosterEntry.week_id != 3, WeeklyRosterEntry.is_bench == True).count() == 0  # noqa: E712

    def test_backfill_bench_makes_substitutions_and_changes_week_points(self, db):
        """Apply runs run_substitutions: a roster card that didn't play is subbed out, a bench card that played is subbed in, and the user's week points change."""
        _seed(db)
        before = _week_points(db, 2)
        assert before["alice"] == display_points(_card_week_pts(db, 1, 2))
        with patch("clock.time.time", return_value=NOW):
            _apply(db, 2)
        alice = _entries(db, 2, 1)
        assert alice[3].subbed_out and not alice[3].subbed_in
        assert alice[2].subbed_in and alice[2].subbed_for_entry_id == alice[3].id
        assert not alice[1].subbed_out
        bob = _entries(db, 2, 2)
        assert bob[5].subbed_out and bob[6].subbed_in
        after = _week_points(db, 2)
        assert after["alice"] == display_points(_card_week_pts(db, 1, 2) + _card_week_pts(db, 2, 2))
        assert after["bob"] == display_points(_card_week_pts(db, 6, 2))
        assert after["alice"] > before["alice"] and after["bob"] > before["bob"]
        assert after["carol"] == before["carol"]

    def test_backfill_bench_returns_users_bench_cards_substitutions(self, db):
        """backfill_bench returns (users, bench_cards, substitutions) counts for the week."""
        _seed(db)
        with patch("clock.time.time", return_value=NOW):
            assert _apply(db, 2) == (2, 2, 2)
            assert _apply(db, 3) == (2, 3, 0)
            # No candidates: nothing written, run_substitutions not called.
            audits = len(_audits(db, "weekly_substitutions"))
            assert _apply(db, 1) == (0, 0, 0)
        assert len(_audits(db, "weekly_substitutions")) == audits
        assert _week(db, 1).substitutions_at == 5000

    def test_backfill_bench_raises_when_week_has_bench_rows(self, db):
        """A week that already has is_bench = 1 rows raises ValueError and is left unchanged."""
        _seed(db)
        with patch("clock.time.time", return_value=NOW):
            _apply(db, 2)
            state = _state(db)
            with pytest.raises(ValueError):
                weeks.backfill_bench(db, _week(db, 2))
        db.commit()
        assert _state(db) == state


class TestBackfillScript:
    """scripts/backfill_bench.py."""

    def test_backfill_script_resolves_weeks_by_label_and_id(self, db, capsys):
        """--weeks accepts week labels and week ids, e.g. "Week 2,3"."""
        _seed(db)
        code, out = _run(db, capsys, "--weeks", "Week 2,3,2")
        assert code == 0
        assert len(out.splitlines()) == 2 + 1 + 1  # a week named twice runs once
        assert _block(out, "Week 2")[0] == "Week 2: 2 users get a bench, 2 bench cards, 2 substitutions"
        assert _block(out, "Week 3")[0] == "Week 3: 2 users get a bench, 3 bench cards, 0 substitutions"
        for wid in (2, 3):
            assert db.query(WeeklyRosterEntry).filter_by(week_id=wid, is_bench=True).count() > 0

    def test_backfill_script_skips_week_with_bench_saved(self, db, capsys):
        """A week with is_bench = 1 rows is skipped with "<label>: bench already saved, skipped" and the other weeks still run."""
        _seed(db)
        db.add(WeeklyRosterEntry(week_id=2, user_id=1, card_id=4, is_bench=True, bench_order=0))
        db.commit()
        code, out = _run(db, capsys, "--weeks", "Week 2,Week 3")
        assert code == 0
        assert "Week 2: bench already saved, skipped" in out.splitlines()
        assert db.query(WeeklyRosterEntry).filter_by(week_id=2, is_bench=True).count() == 1
        assert db.query(WeeklyRosterEntry).filter_by(week_id=3, is_bench=True).count() == 3

    def test_backfill_script_skips_unlocked_week(self, db, capsys):
        """An unlocked week is skipped with the reason printed; the other weeks still run."""
        _seed(db)
        db.add(WeeklyRosterEntry(week_id=4, user_id=1, card_id=1, is_bench=False))
        db.add(WeeklyRosterEntry(week_id=4, user_id=1, card_id=2, is_bench=False))
        db.commit()
        code, out = _run(db, capsys, "--weeks", "Week 4,Week 2")
        assert code == 0
        assert "Week 4: not locked, skipped" in out.splitlines()
        assert db.query(WeeklyRosterEntry).filter_by(week_id=4, is_bench=True).count() == 0
        assert db.query(WeeklyRosterEntry).filter_by(week_id=2, is_bench=True).count() == 2

    def test_backfill_script_skips_week_before_substitution_time(self, db, capsys, monkeypatch):
        """A locked week before end_time + SUBSTITUTION_DELAY_HOURS is skipped with the reason printed."""
        _seed(db)
        monkeypatch.setenv("SUBSTITUTION_DELAY_HOURS", "1")
        # Week 2 ends at 2000, so it is due at 5600; Week 1 (due at 4600) still runs.
        code, out = _run(db, capsys, "--weeks", "Week 2,Week 1", now=5000)
        assert code == 0
        assert "Week 2: substitution time not reached, skipped" in out.splitlines()
        assert "Week 1: no bench cards to add" in out.splitlines()
        assert db.query(WeeklyRosterEntry).filter_by(is_bench=True).count() == 0
        code, out = _run(db, capsys, "--weeks", "Week 2", now=5600)
        assert code == 0 and "skipped" not in out
        assert db.query(WeeklyRosterEntry).filter_by(week_id=2, is_bench=True).count() == 2

    def test_backfill_script_dry_run_prints_report(self, db, capsys):
        """--dry-run prints per week the number of users with a bench, bench cards and substitutions, and one 'username before -> after' line per affected user, largest change first."""
        _seed(db)
        before = _week_points(db, 2)
        code, out = _run(db, capsys, "--weeks", "Week 2", "--dry-run")
        assert code == 0
        assert out.splitlines()[0] == "Dry run: nothing is written."
        block = _block(out, "Week 2")
        assert block[0] == "Week 2: 2 users get a bench, 2 bench cards, 2 substitutions"
        users = [_USER_LINE.match(line) for line in block[1:]]
        assert all(users) and len(users) == 2  # carol is unaffected and not listed
        deltas = [abs(float(m.group(4))) for m in users]
        assert deltas == sorted(deltas, reverse=True)
        b_pts, f_pts = _card_week_pts(db, 2, 2), _card_week_pts(db, 6, 2)
        expected_first = "alice" if b_pts >= f_pts else "bob"
        assert users[0].group(1) == expected_first
        assert {m.group(1): float(m.group(2)) for m in users} == {
            "alice": before["alice"], "bob": before["bob"]}

    def test_backfill_script_dry_run_writes_nothing(self, db, capsys):
        """--dry-run leaves weekly_roster_entries, audit_log and substitutions_at unchanged (rolled back before any commit)."""
        _seed(db)
        state = _state(db)
        code, out = _run(db, capsys, "--weeks", "Week 1,Week 2,Week 3", "--dry-run")
        assert code == 0
        assert "2 substitutions" in out
        db.rollback()
        assert _state(db) == state
        assert _audits(db, "admin_bench_backfill") == []

    def test_backfill_script_report_points_match_weekly_leaderboard(self, db, capsys):
        """The before/after points in the report equal what the weekly leaderboard shows before and after the apply."""
        _seed(db)
        before = _week_points(db, 2)
        _, out = _run(db, capsys, "--weeks", "Week 2")
        after = _week_points(db, 2)
        users = {m.group(1): (float(m.group(2)), float(m.group(3)))
                 for m in (_USER_LINE.match(line) for line in _block(out, "Week 2")[1:])}
        assert users == {u: (before[u], after[u]) for u in ("alice", "bob")}

    def test_backfill_script_apply_writes_bench_rows_and_substitutions(self, db, capsys):
        """Without --dry-run, the bench rows and substitution flags are committed for each processed week."""
        _seed(db)
        code, _ = _run(db, capsys, "--weeks", "Week 2,Week 3")
        assert code == 0
        db.rollback()  # anything not committed by the script would disappear here
        alice = _entries(db, 2, 1)
        assert alice[2].is_bench and alice[2].bench_order == 0 and alice[2].subbed_in
        assert alice[3].subbed_out
        assert _entries(db, 2, 2)[6].subbed_in
        assert sorted(c for c, e in _entries(db, 3, 1).items() if e.is_bench) == [2, 3]
        assert _week(db, 2).substitutions_at == NOW

    def test_backfill_script_apply_writes_audit_entry(self, db, capsys):
        """Each applied week gets one admin_bench_backfill audit entry with actor_username=script and id, label, users, bench_cards, substitutions in detail."""
        _seed(db)
        _run(db, capsys, "--weeks", "Week 1,Week 2,Week 3")
        audits = sorted(_audits(db, "admin_bench_backfill"), key=lambda a: a.id)
        assert [a.detail for a in audits] == [
            "id=2 label=Week 2 users=2 bench_cards=2 substitutions=2",
            "id=3 label=Week 3 users=2 bench_cards=3 substitutions=0",
        ]
        assert all(a.actor_username == "script" and a.actor_id is None for a in audits)
        assert all(a.timestamp == NOW for a in audits)

    def test_backfill_script_apply_prints_same_report_as_dry_run(self, db, capsys):
        """The apply prints the same per-week report the dry run printed."""
        _seed(db)
        _, dry = _run(db, capsys, "--weeks", "Week 1,Week 2,Week 3", "--dry-run")
        _, applied = _run(db, capsys, "--weeks", "Week 1,Week 2,Week 3")
        assert dry.splitlines()[0] == "Dry run: nothing is written."
        assert dry.splitlines()[1:] == applied.splitlines()

    def test_backfill_script_apply_commits_each_week_separately(self, db, capsys):
        """Each week is its own transaction: a failure in one week does not roll back a week already applied."""
        _seed(db)
        real = weeks.backfill_bench

        def failing_on_week_3(session, week):
            result = real(session, week)  # rows inserted and flushed, then the week fails
            if week.id == 3:
                raise RuntimeError("boom")
            return result

        with patch.object(weeks, "backfill_bench", failing_on_week_3):
            code, out = _run(db, capsys, "--weeks", "Week 2,Week 3")
        assert code == 1
        assert "Week 3: failed (RuntimeError: boom), rolled back" in out.splitlines()
        db.rollback()
        assert db.query(WeeklyRosterEntry).filter_by(week_id=2, is_bench=True).count() == 2
        assert db.query(WeeklyRosterEntry).filter_by(week_id=3, is_bench=True).count() == 0
        assert [a.detail.split()[0] for a in _audits(db, "admin_bench_backfill")] == ["id=2"]
        assert _week(db, 3).substitutions_at == 5000

    def test_backfill_script_exits_0_when_weeks_skipped(self, db, capsys):
        """Skipped weeks do not change the exit code: the run exits 0."""
        _seed(db)
        code, out = _run(db, capsys, "--weeks", "Week 4,Week 1", "--dry-run")
        assert code == 0
        assert "Week 4: not locked, skipped" in out

    def test_backfill_script_unknown_week_exits_1(self, db, capsys):
        """A named week that doesn't exist makes the script exit 1."""
        _seed(db)
        state = _state(db)
        code, out = _run(db, capsys, "--weeks", "Week 2,Week 9,42")
        assert code == 1
        assert "Unknown week: Week 9" in out and "Unknown week: 42" in out
        assert _state(db) == state  # nothing processed when a name is wrong

    def test_backfill_script_second_run_skips_every_week(self, db, capsys):
        """After an apply, a second run reports every week as skipped and changes nothing."""
        _seed(db)
        _run(db, capsys, "--weeks", "Week 2,Week 3")
        state = _state(db)
        code, out = _run(db, capsys, "--weeks", "Week 2,Week 3", now=NOW + 100)
        assert code == 0
        assert out.splitlines() == ["Week 2: bench already saved, skipped",
                                    "Week 3: bench already saved, skipped"]
        assert _state(db) == state


# ---------------------------------------------------------------------------
# Story 2: Bench Uses Only Cards the User Provably Had
# ---------------------------------------------------------------------------

class TestBackfillBenchCandidates:
    """weeks.backfill_bench_candidates(db, week)."""

    def test_backfill_bench_candidates_includes_card_from_earlier_roster(self, db):
        """A card on U's roster snapshot (is_bench = 0) in an earlier week, not on the roster in W, is a candidate."""
        _seed(db)
        assert _candidates(db, 2) == {1: [2], 2: [6]}

    def test_backfill_bench_candidates_excludes_card_first_rostered_later(self, db):
        """A card whose first roster snapshot is in a week after W (drawn later) is not a candidate for W."""
        _seed(db)
        # Card 7 is first on alice's roster in Week 3 (and is on her bench today).
        assert 7 not in _candidates(db, 2)[1]
        # Card 3 is first on her roster in Week 2, so it is a candidate for Week 3 only.
        assert 3 in _candidates(db, 3)[1]

    def test_backfill_bench_candidates_excludes_never_rostered_card(self, db):
        """A card U owns now but never had on a roster snapshot up to W is not a candidate."""
        _seed(db)
        for wid in (1, 2, 3):
            cands = _candidates(db, wid)
            assert 4 not in cands.get(1, [])
            assert 9 not in cands.get(3, [])

    def test_backfill_bench_candidates_excludes_card_on_roster_in_week(self, db):
        """A card already on U's roster in W is not a candidate."""
        _seed(db)
        assert 1 not in _candidates(db, 2)[1] and 3 not in _candidates(db, 2)[1]
        assert 5 not in _candidates(db, 2)[2]

    def test_backfill_bench_candidates_excludes_card_owned_by_someone_else(self, db):
        """A card on U's earlier snapshot but now owned by another user is not a candidate for either user."""
        _seed(db)
        db.get(Card, 2).owner_id = 2  # alice's Week 1 card now belongs to bob
        db.commit()
        cands = _candidates(db, 2)
        assert 1 not in cands
        assert cands[2] == [6]

    def test_backfill_bench_candidates_excludes_inactive_player(self, db):
        """A card whose player is inactive (players.is_active = 0, e.g. removed and refunded) is not a candidate."""
        _seed(db)
        db.get(Player, B).is_active = False  # card 2 keeps its owner, as a refund does
        db.commit()
        cands = _candidates(db, 2)
        assert 1 not in cands
        assert cands[2] == [6]

    def test_backfill_bench_candidates_orders_by_current_my_team_order(self, db):
        """bench_order follows the order the lock-time snapshot uses (weeks._slot_order: slot_index, NULL last, then card id) for current bench cards, then current roster cards in slot order."""
        cards = [(1, 1, A, True, 0), (2, 1, B, True, 1), (3, 1, C, False, 2),
                 (4, 1, D, False, 0), (5, 1, E, False, None), (6, 1, F, False, 1),
                 (7, 1, G, False, 1)]
        _seed(db, cards=cards, snapshots={1: {1: [7, 6, 5, 4, 3, 2]}, 2: {1: [1]}})
        assert _candidates(db, 2) == {1: [4, 6, 7, 3, 5, 2]}

    def test_backfill_bench_candidates_first_week_empty(self, db):
        """A week with no earlier locked week gets no bench cards."""
        _seed(db)
        assert _candidates(db, 1) == {}

    def test_backfill_bench_candidates_unchanged_roster_empty(self, db):
        """A user whose roster never changed has no candidates."""
        _seed(db)
        for wid in (1, 2, 3):
            assert 3 not in _candidates(db, wid)

    def test_backfill_script_reports_no_bench_cards_to_add(self, db, capsys):
        """For a week with no candidates the script report says "no bench cards to add"."""
        _seed(db)
        code, out = _run(db, capsys, "--weeks", "Week 1")
        assert code == 0
        assert out.splitlines() == ["Week 1: no bench cards to add"]
        assert _audits(db, "admin_bench_backfill") == []


class TestBackfillSubstitutionRules:
    """run_substitutions applies its normal rules to backfilled benches."""

    def test_backfill_bench_never_replaces_card_whose_player_played(self, db):
        """A roster card whose player played is never subbed out, however few points it scored."""
        # alice's Week 2 roster card 1 (A) scores less than her candidate card 2 (B).
        _seed(db)
        assert _card_week_pts(db, 1, 2) < _card_week_pts(db, 2, 2)
        with patch("clock.time.time", return_value=NOW):
            _apply(db, 2)
        alice = _entries(db, 2, 1)
        assert not alice[1].subbed_out
        assert [c for c, e in alice.items() if e.subbed_out] == [3]

    def test_backfill_bench_never_counts_player_twice(self, db):
        """A bench card whose player is already counted in the week is not subbed in."""
        cards = [(1, 1, A, True, 0), (3, 1, C, True, 1), (10, 1, A, False, 0)]
        _seed(db, cards=cards, snapshots={1: {1: [1, 10]}, 2: {1: [1, 3]}})
        assert _candidates(db, 2) == {1: [10]}
        with patch("clock.time.time", return_value=NOW):
            assert _apply(db, 2) == (1, 1, 0)
        alice = _entries(db, 2, 1)
        assert alice[3].subbed_out and not alice[10].subbed_in

    def test_backfill_bench_each_bench_card_fills_one_slot(self, db):
        """With two roster cards out and one eligible bench card, only one slot is filled."""
        cards = [(1, 1, A, False, 0), (2, 1, D, False, 1), (3, 1, C, True, 0), (4, 1, E, True, 1)]
        matches = [(2, 1100, {A: (2, 1, 403)})]  # only A plays in Week 2
        _seed(db, cards=cards, snapshots={1: {1: [1, 2]}, 2: {1: [3, 4]}}, matches=matches)
        with patch("clock.time.time", return_value=NOW):
            assert _apply(db, 2) == (1, 2, 1)
        alice = _entries(db, 2, 1)
        assert sorted(c for c, e in alice.items() if e.subbed_out) == [3, 4]
        assert [c for c, e in alice.items() if e.subbed_in] == [1]
        assert alice[1].subbed_for_entry_id == alice[3].id


class TestBackfillReaders:
    """After applying, live readers show the substitutions."""

    def test_backfill_bench_roster_response_shows_substitution_labels(self, db):
        """My Team for the week marks the bench card as subbed in for the roster card's player and the roster card as did not play."""
        _seed(db)
        with patch("clock.time.time", return_value=NOW):
            _apply(db, 2)
        r = _build_roster_response(db, 1, 2)
        by_id = {c["id"]: c for c in r["active"] + r["bench"]}
        assert by_id[2]["subbed_in"] and by_id[2]["subbed_in_for"] == f"P{C}"
        assert by_id[3]["subbed_out"] and not by_id[3]["subbed_in"]
        assert {c["id"] for c in r["active"]} == {1, 2}
        assert r["combined_value"] == display_points(
            _card_week_pts(db, 1, 2) + _card_week_pts(db, 2, 2))

    def test_backfill_bench_leaderboards_include_substituted_points(self, db):
        """The weekly and season leaderboards include the substituted bench card's points and drop the subbed-out card."""
        _seed(db)
        season_before = {r["username"]: r["points"] for r in compute_season_standings(db)}
        with patch("clock.time.time", return_value=NOW):
            _apply(db, 2)
        weekly = {r["username"]: r for r in weekly_leaderboard(week_id=2, db=db)}
        assert {c["card_id"] for c in weekly["alice"]["cards"]} == {1, 2}
        assert {c["card_id"] for c in weekly["bob"]["cards"]} == {6}
        season = {r["username"]: r["points"] for r in compute_season_standings(db)}

        def exact(*card_weeks):
            return display_points(sum(_card_week_pts(db, c, w) for c, w in card_weeks))

        assert season["alice"] == exact((1, 1), (2, 1), (1, 2), (2, 2), (1, 3), (7, 3))
        assert season["bob"] == exact((5, 1), (6, 1), (6, 2), (5, 3))
        assert season["alice"] > season_before["alice"] and season["bob"] > season_before["bob"]
        assert season["carol"] == season_before["carol"]
