"""
Tests for plan-issue-251-architecture-maturity-review.md (resolves GitHub issue #251).

Two read-only operator tools (`scripts/usage_report.py`, `scripts/load_test.py`) and a
written review (`markdown/research/architecture-maturity-review.md`) that sizes the
current architecture against season 16's load. No production code changes.

  Story 1: See the Season's Real Load          (scripts/usage_report.py)
  Story 2: Know the Headroom                   (scripts/load_test.py)
  Story 3: A Ranked List of Off-Season Improvements (the review document and its index rows)

Approach notes (for the developer filling these in):

- Both scripts live in the repo-root `scripts/` folder (next to `bench_leaderboards.py`),
  not `backend/scripts/`. Load them with importlib (`_mod()` below, the pattern of
  test_issue_233_season_placements_backfill.py: no sys.modules entry, so no @dataclass
  in the scripts). Each script should expose a `main(argv, out=print)`-style entry
  point plus plain functions (e.g. `build_report(path)`, `is_local(url)`,
  `percentiles(samples)`, `run(...)`, `ramp(...)`) so tests need no subprocess. If a
  subprocess is needed, follow test_issue_149_points_rounding.py (`sys.executable`,
  cwd = repo root, real keys such as STEAM_API_KEY popped from the env).
- The usage report opens a database FILE read-only (`sqlite3` URI, `mode=ro`), so the
  conftest `db` (plain `:memory:`) cannot be used. This module's `db` fixture
  overrides it with a file-backed SQLite database under `tmp_path`; `db_path` is the
  file to pass as `--db`. Commit the session before running the report. Never point a
  test at the real `data/fantasy.db`.
- Checked against the code (the plan is partly wrong, follow the code):
    * audit actions in use: draws are `token_draw` and `token_booster_draw`
      (routers/cards.py), logins are `user_login` (routers/auth.py and
      steam_openid.py), token drops are `twitch_token_drop` with `pool_size=<n>` in
      `detail` (twitch.py `_drop_audit_detail`).
    * roster saves (`PUT /roster`, `/roster/{id}/activate`, `/deactivate`, `/reorder`,
      `/swap`) write NO audit row today. The report must say roster saves are not
      recorded rather than print 0 as if measured; rosters per week come from
      `weekly_roster_entries` (distinct `user_id` per `week_id`).
    * soft accounts are `users.account_type == "twitch"`, website accounts `"full"`.
    * `twitch_presence` holds only the current heartbeat rows, so the largest presence
      pool of the season comes from the `pool_size=` values in the token-drop audit
      details; `twitch_mvp` and `twitch_token_drops` give MVPs, drops and channels.
    * `audit_logs.timestamp` and `weeks.start_time` / `end_time` are Unix seconds;
      bucket activity into weeks by those bounds.
    * `rate_limit.py` has no on/off switch: limits are env strings read at import
      (`RATE_LIMIT_GLOBAL`, `RATE_LIMIT_CARD_ACTION`, `RATE_LIMIT_CARD_ACTION_IP`,
      `RATE_LIMIT_USER_ACTION`). The pointer doc names these as the way to relax them.
- Load test: never touch the network. Run it against a stub `http.server`
  (`ThreadingHTTPServer` on 127.0.0.1 port 0, in a daemon thread) whose handler
  records method and path and can be told to sleep or answer 500 per path, or inject
  a fake request function / clock. Keep `--users` and `--seconds` tiny (2 users,
  under a second). Tests of the ramp should inject measured levels rather than sleep.
- Document tests are source-reading only, as in
  test_issue_108_kana_hub_integration_feasibility.py (`_REPO_ROOT`, read the file,
  assert on headings and table rows). Parse markdown by lines, no HTML regexes.
  GitHub is not called: an issue link is checked by its URL shape only.

Run with: cd backend && python -m pytest tests/test_issue_251_architecture_maturity_review.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hashlib
import importlib.util
import json
import re
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401  (registers every table for the db fixture)
from database import Base
from models import (AuditLog, Card, TwitchMVP, TwitchTokenDrop, User, Week,
                    WeeklyRosterEntry)

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_USAGE_REPORT = os.path.join(_REPO_ROOT, "scripts", "usage_report.py")
_LOAD_TEST = os.path.join(_REPO_ROOT, "scripts", "load_test.py")
_REVIEW_DOC = os.path.join(_REPO_ROOT, "markdown", "research", "architecture-maturity-review.md")
_POINTER_DOC = os.path.join(_REPO_ROOT, "markdown", "features", "reference",
                            "architecture-maturity-review.md")
_FEATURES_README = os.path.join(_REPO_ROOT, "markdown", "features", "README.md")
_ISSUE_INDEX = os.path.join(_REPO_ROOT, "markdown", "plans", ".issue-index")

AREAS = (
    "process model", "SQLite", "background jobs", "external services",
    "caching and rate limits", "deployment and recovery", "observability",
    "frontend delivery", "test and release tooling",
)
VERDICTS = ("fine at target load", "fix before season 17", "watch")


@pytest.fixture
def db_path(tmp_path):
    """Path of a throwaway SQLite file with every table created (never data/fantasy.db)."""
    path = tmp_path / "season.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return str(path)


@pytest.fixture
def db(db_path):
    """Session on the file behind `db_path` (overrides conftest's in-memory `db`)."""
    engine = create_engine(f"sqlite:///{db_path}")
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _mod(path):
    """Load a repo-root script by path, without a sys.modules entry."""
    name = os.path.splitext(os.path.basename(path))[0] + "_251"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _usage(db_path, *extra):
    """Run usage_report.main on the file; returns (exit code, printed text, errors)."""
    out, errs = [], []
    code = _mod(_USAGE_REPORT).main(["--db", db_path, *extra], out=out.append, err=errs.append)
    return code, "\n".join(out), errs


def _flat(text):
    """The report with runs of spaces collapsed, so `label: value` can be matched."""
    return re.sub(r"[ \t]+", " ", text)


def _user(db, n, account_type="full"):
    user = User(username=f"user{n}" if account_type == "full" else None,
                email=f"user{n}@example.org" if account_type == "full" else None,
                account_type=account_type, tokens=0)
    db.add(user)
    db.flush()
    return user


def _weeks(db, bounds=((1000, 1999), (2000, 2999))):
    weeks = [Week(label=f"Week {i}", start_time=s, end_time=e, is_locked=True)
             for i, (s, e) in enumerate(bounds, 1)]
    db.add_all(weeks)
    db.flush()
    return weeks


def _audit(db, ts, action, detail=None, actor_username=None):
    db.add(AuditLog(timestamp=ts, action=action, detail=detail, actor_username=actor_username))


def _seed_season(db):
    """A small season touching every section of the report."""
    weeks = _weeks(db)
    users = [_user(db, n) for n in range(3)] + [_user(db, 9, "twitch")]
    for i, user in enumerate(users[:2]):
        db.add(Card(id=i + 1, player_id=100 + i, owner_id=user.id, card_type="common"))
        db.add(WeeklyRosterEntry(week_id=weeks[0].id, user_id=user.id, card_id=i + 1))
    _audit(db, 1100, "token_draw")
    _audit(db, 1200, "token_booster_draw")
    _audit(db, 2100, "user_login")
    _audit(db, 2200, "twitch_token_drop", detail="channel=c1 match=5 count=2 pool_size=17 excluded_new=0 winners=a,b")
    db.add(TwitchMVP(match_id=5, player_id=100, channel_id="c1", selected_at=2200))
    db.add(TwitchTokenDrop(channel_id="c1", series_id="5", dropped_at=2200, count=2))
    db.commit()


def _table_counts(db_path):
    con = sqlite3.connect(db_path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        con.close()


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------
# Story 1: See the Season's Real Load (scripts/usage_report.py)
# ---------------------------------------------------------------------------

class TestUsageReport:

    def test_usage_report_prints_report_for_db_file(self, db, db_path):
        """AC Run: `usage_report.py --db <path>` on a seeded database file exits 0 and prints a report with Accounts, Activity, Twitch and Data sections."""
        _seed_season(db)
        code, text, errs = _usage(db_path)
        assert code == 0
        assert errs == []
        lines = text.splitlines()
        headings = [ln for ln in lines if ln and not ln.startswith(" ")]
        assert [h.split(" (")[0] for h in headings] == ["Accounts", "Activity", "Twitch", "Data"]
        assert "Website accounts: 3" in _flat(text)

    def test_usage_report_json_has_same_numbers_as_text(self, db, db_path):
        """AC Run: `--json` emits valid JSON whose account, activity, Twitch and data numbers equal the ones in the printed report for the same database."""
        _seed_season(db)
        _, text, _ = _usage(db_path)
        code, raw, _ = _usage(db_path, "--json")
        assert code == 0
        data = json.loads(raw)
        assert set(data) == {"accounts", "activity", "twitch", "data"}
        flat = _flat(text)
        acc, act, tw, dat = data["accounts"], data["activity"], data["twitch"], data["data"]
        assert (acc["website"], acc["soft"], acc["with_card"]) == (3, 1, 2)
        assert f"Website accounts: {acc['website']}" in flat
        assert f"Twitch soft accounts: {acc['soft']}" in flat
        assert f"Accounts with a card: {acc['with_card']}" in flat
        for w in acc["rosters_per_week"]:
            assert f"Week {w['week']}: {w['accounts']}\n" in flat + "\n"
        for w in act["weeks"]:
            assert f"Week {w['week']}: draws {w['draws']}, logins {w['logins']}" in flat
        assert sum(w["draws"] for w in act["weeks"]) == 2
        assert f"Busiest hour: {act['busiest_hour']['count']} actions, starting {act['busiest_hour']['start_utc']}" in flat
        assert f"Busiest minute: {act['busiest_minute']['count']} actions" in flat
        assert f"Channels: {tw['channels']}" in flat and tw["channels"] == 1
        assert f"MVPs set: {tw['mvps_set']}" in flat and tw["mvps_set"] == 1
        assert f"Token drops: {tw['token_drops']}" in flat and tw["token_drops"] == 1
        assert f"Largest presence pool: {tw['largest_presence_pool']}" in flat and tw["largest_presence_pool"] == 17
        assert f"File size: {dat['file_size_bytes']} bytes" in flat
        top = dat["tables"][0]
        assert f"{top['table']}: {top['rows']}" in flat

    def test_usage_report_leaves_database_unchanged(self, db, db_path):
        """AC Run: the file's bytes (sha256) and every table's row count are identical before and after a run, and the script's connection uses `mode=ro` (a write through it raises `sqlite3.OperationalError`)."""
        _seed_season(db)
        db.close()
        before_hash, before_counts = _sha256(db_path), _table_counts(db_path)
        assert _usage(db_path)[0] == 0
        assert _usage(db_path, "--json")[0] == 0
        assert _sha256(db_path) == before_hash
        assert _table_counts(db_path) == before_counts
        con = _mod(_USAGE_REPORT).connect(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                con.execute("INSERT INTO weeks (label) VALUES ('x')")
            with pytest.raises(sqlite3.OperationalError):
                con.execute("CREATE TABLE usage_report_probe (a INTEGER)")
        finally:
            con.close()
        assert _sha256(db_path) == before_hash

    def test_usage_report_missing_db_file_fails_without_creating_it(self, tmp_path):
        """Failure path: `--db` pointing at a file that does not exist exits non-zero with a message naming the path, and no file is created there."""
        missing = str(tmp_path / "nowhere" / "missing.db")
        code, text, errs = _usage(missing)
        assert code != 0
        assert text == ""
        assert any(missing in e for e in errs)
        assert not os.path.exists(missing)
        assert not os.path.exists(os.path.dirname(missing))

    def test_usage_report_account_counts(self, db, db_path):
        """AC Accounts: with 3 `full` users, 2 `twitch` users, 4 users owning a card and rosters from 3 users in week 1 and 1 user in week 2, the report gives website=3, soft=2, with_card=4 and rosters per week {week 1: 3, week 2: 1} (distinct users, bench entries not double counted)."""
        w1, w2 = _weeks(db)
        full = [_user(db, n) for n in range(3)]
        soft = [_user(db, 10 + n, "twitch") for n in range(2)]
        owners = full + soft[:1]                      # 4 accounts own a card
        card_id = 0
        for user in owners:
            for _ in range(2):                        # two cards each: still one owner
                card_id += 1
                db.add(Card(id=card_id, player_id=card_id, owner_id=user.id, card_type="common"))
        for user in full:                             # week 1: 3 users, an active and a bench entry each
            db.add(WeeklyRosterEntry(week_id=w1.id, user_id=user.id, card_id=1))
            db.add(WeeklyRosterEntry(week_id=w1.id, user_id=user.id, card_id=2, is_bench=True, bench_order=0))
        db.add(WeeklyRosterEntry(week_id=w2.id, user_id=full[0].id, card_id=1))
        db.add(WeeklyRosterEntry(week_id=w2.id, user_id=full[0].id, card_id=2, is_bench=True, bench_order=0))
        db.commit()
        acc = _mod(_USAGE_REPORT).build_report(db_path)["accounts"]
        assert acc["website"] == 3
        assert acc["soft"] == 2
        assert acc["with_card"] == 4
        assert acc["rosters_per_week"] == [{"week": 1, "accounts": 3}, {"week": 2, "accounts": 1}]

    def test_usage_report_weekly_activity_from_audit_logs(self, db, db_path):
        """AC Activity: audit rows are bucketed by `weeks.start_time`/`end_time`; draws count `token_draw` plus `token_booster_draw`, logins count `user_login`, other actions are ignored, and roster saves are reported as not recorded in `audit_logs` (no audit action exists for them) rather than as a measured 0."""
        _weeks(db)                                    # week 1: 1000..1999, week 2: 2000..2999
        for ts, action in [(1000, "token_draw"), (1500, "token_draw"), (1999, "token_booster_draw"),
                           (1200, "user_register"), (1300, "admin_ingest"),
                           (2000, "user_login"), (2500, "user_login"), (2999, "token_draw"),
                           (2600, "roster_save"),      # not a real action: must not be counted
                           (5000, "token_draw"), (999, "user_login")]:
            _audit(db, ts, action)
        db.commit()
        act = _mod(_USAGE_REPORT).build_report(db_path)["activity"]
        assert act["weeks"] == [{"week": 1, "draws": 3, "logins": 0},
                                {"week": 2, "draws": 1, "logins": 2}]
        assert act["outside_weeks"] == {"draws": 1, "logins": 1}
        assert isinstance(act["roster_saves"], str) and "not recorded" in act["roster_saves"]
        _, text, _ = _usage(db_path)
        saves = [ln for ln in _flat(text).splitlines() if ln.strip().startswith("Roster saves:")]
        assert len(saves) == 1 and "not recorded" in saves[0]
        assert not re.search(r"Roster saves: \d", saves[0])

    def test_usage_report_busiest_hour_and_minute(self, db, db_path):
        """AC Activity: with 5 audit rows inside one minute, 7 in another hour spread over several minutes and 1 elsewhere, the busiest minute has count 5 and the busiest hour has count 7, each with its UTC start time."""
        _weeks(db)
        hour_a = 3600 * 480000                        # an exact clock hour
        hour_b = hour_a + 5 * 3600
        minute = hour_a + 17 * 60
        for i in range(5):
            _audit(db, minute + i * 10, "token_draw")
        for i in range(7):
            _audit(db, hour_b + i * 8 * 60, "user_login")   # one per 8 minutes
        _audit(db, hour_a + 30 * 3600 + 5, "user_register")
        db.commit()
        act = _mod(_USAGE_REPORT).build_report(db_path)["activity"]

        def utc(ts):
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        assert act["busiest_minute"] == {"start_utc": utc(minute), "count": 5}
        assert act["busiest_hour"] == {"start_utc": utc(hour_b), "count": 7}
        assert act["audit_rows"] == 13

    def test_usage_report_activity_empty_audit_log(self, db, db_path):
        """Failure path: a database with weeks but no audit rows reports 0 draws and logins per week and no busiest hour or minute (None / "n/a"), without raising."""
        _weeks(db)
        db.commit()
        act = _mod(_USAGE_REPORT).build_report(db_path)["activity"]
        assert act["weeks"] == [{"week": 1, "draws": 0, "logins": 0},
                                {"week": 2, "draws": 0, "logins": 0}]
        assert act["busiest_hour"] is None and act["busiest_minute"] is None
        code, text, errs = _usage(db_path)
        assert code == 0 and errs == []
        flat = _flat(text)
        assert "Busiest hour: n/a" in flat and "Busiest minute: n/a" in flat
        assert "Largest presence pool: n/a" in flat

    def test_usage_report_twitch_numbers(self, db, db_path):
        """AC Twitch: channels = distinct `channel_id` across `twitch_mvp` and `twitch_token_drops`, MVPs set = `twitch_mvp` rows, token drops = `twitch_token_drops` rows, and the largest presence pool = the highest `pool_size=` in `twitch_token_drop` audit details (entries without it skipped)."""
        for match_id, channel in [(1, "chan-a"), (2, "chan-a"), (3, "chan-b")]:
            db.add(TwitchMVP(match_id=match_id, player_id=1, channel_id=channel, selected_at=1500))
        for series, channel in [("1", "chan-b"), ("2", "chan-c")]:
            db.add(TwitchTokenDrop(channel_id=channel, series_id=series, dropped_at=1500, count=1))
        _audit(db, 1500, "twitch_token_drop", "channel=chan-a match=1 count=3 pool_size=12 excluded_new=0 winners=a,b,c")
        _audit(db, 1600, "twitch_token_drop", "channel=chan-b match=2 count=5 pool_size=40 excluded_new=1 pool_spike=true winners=a")
        _audit(db, 1700, "twitch_token_drop", "channel=chan-a match=3 count=1 winners=a")   # before pool_size existed
        _audit(db, 1800, "twitch_token_drop", None)
        _audit(db, 1900, "admin_note", "pool_size=999")                                    # another action
        db.commit()
        tw = _mod(_USAGE_REPORT).build_report(db_path)["twitch"]
        assert tw == {"channels": 3, "mvps_set": 3, "token_drops": 2, "largest_presence_pool": 40}

    def test_usage_report_table_rows_file_size_and_weekly_growth(self, db, db_path):
        """AC Data: the report lists the largest tables by row count in descending order with correct counts, the file size equal to `os.path.getsize(db_path)`, and growth per week (rows added per week from timestamped tables, and size divided by the number of weeks)."""
        _weeks(db)
        for i in range(6):
            _audit(db, 1100 + i, "token_draw")        # 6 audit rows in week 1
        _audit(db, 2100, "user_login")                # 1 in week 2
        _audit(db, 9000, "user_login")                # outside both weeks
        user = _user(db, 1)
        user.created_at = 2200                        # 1 user row in week 2
        for i in range(3):
            db.add(Card(id=i + 1, player_id=i + 1, owner_id=user.id, card_type="common"))
        db.commit()
        db.close()
        data = _mod(_USAGE_REPORT).build_report(db_path)["data"]
        counts = _table_counts(db_path)
        assert {t["table"]: t["rows"] for t in data["tables"]} == counts
        rows = [t["rows"] for t in data["tables"]]
        assert rows == sorted(rows, reverse=True)
        assert [(t["table"], t["rows"]) for t in data["tables"][:3]] == [
            ("audit_logs", 8), ("cards", 3), ("weeks", 2)]
        assert data["total_rows"] == sum(counts.values())
        size = os.path.getsize(db_path)
        assert data["file_size_bytes"] == size
        assert data["weeks"] == 2
        assert data["size_per_week_bytes"] == round(size / 2)
        assert data["rows_added_per_week"] == [{"week": 1, "rows": 6}, {"week": 2, "rows": 2}]
        _, text, _ = _usage(db_path)
        flat = _flat(text)
        assert flat.index("audit_logs: 8") < flat.index("cards: 3") < flat.index("weeks: 2")
        assert f"Size per week: {round(size / 2)} bytes" in flat

    def test_usage_report_output_has_no_usernames_emails_or_ids(self, db, db_path):
        """AC Privacy: with users seeded with distinctive usernames, emails, Steam ids, Twitch user ids and channel ids (also inside `audit_logs.actor_username` and `detail`), none of those strings appears in the text or the `--json` output."""
        secrets = ["Zanzibarius", "zanzi@secret-mail.example", "76561198012345678",
                   "U918273645", "tw-acct-5550001", "chan-77700077", "Quixotica"]
        _weeks(db)
        db.add(User(id=424242, username=secrets[0], email=secrets[1], steam_id=secrets[2],
                    twitch_user_id=secrets[3], twitch_account_id=secrets[4], created_at=1100))
        db.add(User(id=434343, username=secrets[6], email="other@secret-mail.example", created_at=1200))
        db.add(Card(id=1, player_id=1, owner_id=424242, card_type="common"))
        db.add(TwitchMVP(match_id=1, player_id=1, channel_id=secrets[5], selected_at=1500))
        db.add(TwitchTokenDrop(channel_id=secrets[5], series_id="1", dropped_at=1500, count=1))
        db.add(AuditLog(timestamp=1500, actor_id=424242, actor_username=secrets[0], action="user_login",
                        detail=f"from {secrets[1]}"))
        db.add(AuditLog(timestamp=1600, actor_id=434343, actor_username=secrets[6], action="twitch_token_drop",
                        detail=f"channel={secrets[5]} match=1 count=1 pool_size=3 excluded_new=0 winners={secrets[0]},{secrets[6]}"))
        db.commit()
        _, text, _ = _usage(db_path)
        _, raw, _ = _usage(db_path, "--json")
        for output in (text, raw):
            assert output
            for secret in secrets + ["secret-mail", "424242", "434343"]:
                assert secret not in output
        assert json.loads(raw)["twitch"]["largest_presence_pool"] == 3


# ---------------------------------------------------------------------------
# Story 2: Know the Headroom (scripts/load_test.py)
# ---------------------------------------------------------------------------

_ROSTER = {"active": [{"id": 1, "player_id": 10}, {"id": 2, "player_id": 11}],
           "bench": [{"id": 3, "player_id": 12}], "version": "v1"}


class _Stub:
    """A local stand-in for the app: records every request, answers JSON, and can
    answer 500 or sleep for chosen paths. Never leaves 127.0.0.1."""

    def __init__(self, fail=(), slow=None):
        self.requests = []          # (method, path without query, full path, user from cookie)
        self.registered, self.logins = [], []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):

            def log_message(self, *args):
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                path = urlparse(self.path).path
                cookie = self.headers.get("Cookie") or ""
                who = cookie.split("uid=", 1)[1].split(";")[0] if "uid=" in cookie else None
                set_cookie = None
                if self.command == "POST" and path in ("/register", "/login"):
                    who = json.loads(raw)["username"]
                    set_cookie = f"uid={who}; Path=/"
                with stub._lock:
                    stub.requests.append((self.command, path, self.path, who))
                    if path == "/register":
                        stub.registered.append(who)
                    if path == "/login":
                        stub.logins.append(who)
                if slow and path in slow:
                    time.sleep(slow[path])
                status = 500 if path in fail else 200
                if path == "/me":
                    body = {"user_id": 7}
                elif path == "/weeks":
                    body = [{"id": 2}, {"id": 3}]
                elif path.startswith("/roster"):
                    body = _ROSTER
                else:
                    body = {}
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                if set_cookie:
                    self.send_header("Set-Cookie", set_cookie)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.handle_error = lambda *args: None   # a client that timed out and left
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def seen(self):
        return {(m, p) for m, p, _, _ in self.requests}


@pytest.fixture
def stub():
    servers = []

    def make(**kwargs):
        servers.append(_Stub(**kwargs))
        return servers[-1]

    yield make
    for s in servers:
        s.close()


def _load(*args, request=None):
    out, errs = [], []
    code = _mod(_LOAD_TEST).main(list(args), out=out.append, err=errs.append, request=request)
    return code, "\n".join(out), errs


def _closed_port_url():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


def _client_sources():
    root = os.path.join(_REPO_ROOT, "frontend")
    text = ""
    for name in sorted(os.listdir(root)):
        if name.startswith("app-") and name.endswith(".js"):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                text += f.read()
    with open(os.path.join(_REPO_ROOT, "twitch-extension", "panel.js"), encoding="utf-8") as f:
        return text, f.read()


# (method, path pattern) -> the call as written in frontend/app-*.js or panel.js
_REAL_CALLS = {
    ("POST", r"/register"): "`${API}/register`",
    ("POST", r"/login"): "`${API}/login`",
    ("GET", r"/me"): "`${API}/me`",
    ("GET", r"/weeks"): "`${API}/weeks`",
    ("GET", r"/leaderboard/season"): "`${API}/leaderboard/season`",
    ("GET", r"/leaderboard/weekly"): "`${API}/leaderboard/weekly?week_id=${weekId}`",
    ("GET", r"/roster/\d+"): "`${API}/roster/${activeUserId}`",
    ("GET", r"/schedule"): "`${API}/schedule`",
    ("GET", r"/players"): "`${API}/players`",
    ("GET", r"/twitch/panel"): 'ebsGet("/twitch/panel")',
    ("POST", r"/draw"): "`${API}/draw`",
    ("PUT", r"/roster"): "`${API}/roster`",
}


class TestLoadTest:

    def test_load_test_drives_read_and_write_mix_against_stub_server(self, stub):
        """AC Run: `--base-url http://127.0.0.1:<port> --users 2 --seconds S` against a stub server hits the leaderboard, roster, schedule, players and Twitch panel reads and the draw and roster-save writes; every path requested is one the frontend or panel really calls."""
        server = stub()
        code, text, errs = _load("--base-url", server.url, "--users", "2", "--seconds", "0.3", "--think", "0")
        assert code == 0 and errs == []
        seen = server.seen()
        for call in [("GET", "/leaderboard/season"), ("GET", "/leaderboard/weekly"), ("GET", "/roster/7"),
                     ("GET", "/schedule"), ("GET", "/players"), ("GET", "/twitch/panel"),
                     ("POST", "/draw"), ("PUT", "/roster")]:
            assert call in seen, call
        assert any(full == "/leaderboard/weekly?week_id=3" for _, _, full, _ in server.requests)
        site, panel = _client_sources()
        for method, path in seen:
            needles = [needle for (m, pattern), needle in _REAL_CALLS.items()
                       if m == method and re.fullmatch(pattern, path)]
            assert len(needles) == 1, (method, path)
            assert needles[0] in (panel if path.startswith("/twitch/") else site), needles[0]
        assert "TOTAL" in text

    def test_load_test_registers_and_logs_in_its_own_users(self, stub):
        """AC Run: with `--users 3` the stub server sees exactly 3 registrations with distinct, clearly marked test usernames, each followed by a login, before that user's first draw or roster save."""
        server = stub()
        code, _, _ = _load("--base-url", server.url, "--users", "3", "--seconds", "0.3", "--think", "0")
        assert code == 0
        assert len(server.registered) == 3
        assert len(set(server.registered)) == 3
        assert all(name.startswith("loadtest-") for name in server.registered)
        assert sorted(server.logins) == sorted(server.registered)
        for name in server.registered:
            mine = [(m, p) for m, p, _, who in server.requests if who == name]
            register, login = mine.index(("POST", "/register")), mine.index(("POST", "/login"))
            writes = [i for i, call in enumerate(mine) if call in (("POST", "/draw"), ("PUT", "/roster"))]
            assert writes, name
            assert register < login < min(writes)

    def test_load_test_refuses_non_local_base_url(self):
        """AC Refuses production (failure path): `--base-url https://example.com` without `--allow-remote` exits non-zero with a message naming the flag and sends no request (the request function is never called)."""
        calls = []

        def request(*args, **kwargs):
            calls.append(args)
            raise AssertionError("no request may be sent")

        code, text, errs = _load("--base-url", "https://example.com", "--users", "1", "--seconds", "0.1",
                                 request=request)
        assert code != 0
        assert text == ""
        assert any("--allow-remote" in e for e in errs)
        assert calls == []

    def test_load_test_local_hosts_and_allow_remote_are_accepted(self):
        """AC Refuses production: `localhost`, `127.0.0.1` and `[::1]` pass the check, hosts that only contain the word (`localhost.example.com`, `example.com/localhost`) do not, and a remote URL passes only with `--allow-remote` (hostname parsed with `urlparse`, exact match)."""
        mod = _mod(_LOAD_TEST)
        for url in ("http://localhost:8000", "http://LOCALHOST", "http://127.0.0.1:8251/", "http://[::1]:8000"):
            assert mod.is_local(url), url
        for url in ("http://localhost.example.com", "https://example.com/localhost",
                    "http://localhost@example.com", "http://127.0.0.1.example.com",
                    "https://example.com", "http://192.168.1.10:8000", "localhost:8000", ""):
            assert not mod.is_local(url), url

        calls = []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {}

        def request(session, method, url, **kwargs):
            calls.append((method, url))
            return Response()

        args = ("--base-url", "https://staging.example.com", "--users", "1", "--seconds", "0.05", "--think", "0")
        assert _load(*args, request=request)[0] != 0
        assert calls == []
        code, _, errs = _load(*args, "--allow-remote", request=request)
        assert code == 0 and errs == []
        assert calls and all(urlparse(url).hostname == "staging.example.com" for _, url in calls)

    def test_load_test_reports_per_endpoint_rate_errors_and_percentiles(self, stub):
        """AC Reports: for each endpoint the report gives the request count, requests per second, error rate and p50/p95/p99 latency; a stub path that always answers 500 shows error rate 1.0, the others 0, and injected latencies 1..100 ms give p50=50, p95=95, p99=99 (within the script's interpolation rule)."""
        mod = _mod(_LOAD_TEST)
        server = stub(fail={"/players"})
        result = mod.run(server.url, 2, 0.3, think=0)
        assert set(result["endpoints"]) == set(mod.ENDPOINTS)
        for name, s in result["endpoints"].items():
            assert s["count"] > 0, name
            assert s["rps"] == round(s["count"] / result["seconds"], 2)
            assert s["error_rate"] == (1.0 if name == "players" else 0.0), name
            assert 0 < s["p50_ms"] <= s["p95_ms"] <= s["p99_ms"]
        assert 0 < result["total"]["error_rate"] < 1
        assert result["total"]["count"] == sum(s["count"] for s in result["endpoints"].values())

        shuffled = [((i * 37) % 100 + 1) / 1000 for i in range(100)]      # 1..100 ms, out of order
        assert mod.percentiles(shuffled) == {"p50": 0.050, "p95": 0.095, "p99": 0.099}
        assert mod.percentiles([0.2]) == {"p50": 0.2, "p95": 0.2, "p99": 0.2}
        assert mod.percentiles([]) == {"p50": None, "p95": None, "p99": None}

    def test_load_test_json_has_same_numbers_as_text(self, stub):
        """AC Reports: `--json` emits valid JSON with one entry per endpoint holding the same count, requests per second, error rate and p50/p95/p99 as the printed report, plus the rate-limit settings the run assumed."""
        mod = _mod(_LOAD_TEST)
        server = stub()
        code, raw, _ = _load("--base-url", server.url, "--users", "2", "--seconds", "0.2", "--think", "0", "--json")
        assert code == 0
        data = json.loads(raw)
        assert set(data["endpoints"]) == set(mod.ENDPOINTS)
        for s in data["endpoints"].values():
            assert {"count", "rps", "error_rate", "p50_ms", "p95_ms", "p99_ms"} <= set(s)
        settings = data["rate_limits"]["settings"]
        for name in ("RATE_LIMIT_GLOBAL", "RATE_LIMIT_CARD_ACTION", "RATE_LIMIT_CARD_ACTION_IP",
                     "RATE_LIMIT_ROSTER_MUTATION", "RATE_LIMIT_REGISTER", "RATE_LIMIT_LOGIN"):
            assert name in settings
        # The text report is rendered from the same numbers.
        rows = {ln.split()[0]: ln.split()[1:] for ln in mod.format_result(data).splitlines()
                if ln.startswith("  ") and ln.split()[0] in data["endpoints"]}
        assert set(rows) == set(data["endpoints"])
        for name, s in data["endpoints"].items():
            assert s["count"] > 0, name
            assert rows[name] == [str(s[k]) for k in
                                  ("count", "rps", "error_rate", "refused", "p50_ms", "p95_ms", "p99_ms")]
        assert "RATE_LIMIT_GLOBAL" in mod.format_result(data)

    def test_load_test_counts_connection_errors_instead_of_crashing(self, stub):
        """Failure path: when the server is unreachable (closed port) or a request times out, the run finishes, counts those requests as errors for their endpoint and exits with the report rather than a traceback."""
        code, raw, errs = _load("--base-url", _closed_port_url(), "--users", "2", "--seconds", "0.2",
                                "--think", "0", "--timeout", "0.5", "--json")
        assert code == 0 and errs == []
        data = json.loads(raw)
        assert data["total"]["count"] > 0
        assert data["total"]["error_rate"] == 1.0
        assert data["setup"]["register"] == {**data["setup"]["register"], "count": 2, "errors": 2}

        server = stub(slow={"/schedule": 0.6})
        result = _mod(_LOAD_TEST).run(server.url, 2, 0.3, think=0, timeout=0.15)
        assert result["endpoints"]["schedule"]["count"] > 0
        assert result["endpoints"]["schedule"]["error_rate"] == 1.0
        assert result["endpoints"]["players"]["error_rate"] == 0.0

    @staticmethod
    def _measure(levels, calls):
        """A fake measurement: `levels` maps the n-th call to (p95 ms, error rate)."""
        def measure(users):
            p95, error_rate = levels[len(calls)]
            calls.append(users)
            return {"total": {"rps": 10.0, "error_rate": error_rate, "p50_ms": p95 / 2,
                              "p95_ms": p95, "p99_ms": p95 * 1.2}}
        return measure

    def test_load_test_ramp_stops_when_p95_passes_one_second(self):
        """AC Steps: `--ramp` raises the user count step by step; with measured levels whose p95 is 0.2 s, 0.6 s, then 1.3 s it stops at the third level, runs no further level and reports that user count and "p95 > 1 s" as the limit."""
        mod = _mod(_LOAD_TEST)
        calls = []
        levels = [(200.0, 0.0), (600.0, 0.0), (1300.0, 0.0), (100.0, 0.0), (100.0, 0.0)]
        result = mod.ramp(self._measure(levels, calls), start=10, step=10, max_users=50)
        assert calls == [10, 20, 30]
        assert [lv["users"] for lv in result["levels"]] == [10, 20, 30]
        assert result["limit_users"] == 30
        assert result["reason"] == "p95 > 1 s"
        text = mod.format_ramp(result)
        assert "Limit: 30 users (p95 > 1 s)." in text
        # Exactly one second is not over the limit.
        calls = []
        result = mod.ramp(self._measure([(1000.0, 0.0), (1000.1, 0.0)], calls), start=5, step=5, max_users=10)
        assert result["limit_users"] == 10

    def test_load_test_ramp_stops_when_errors_pass_one_percent(self):
        """AC Steps: with p95 under 1 s throughout and error rates 0%, 1.0%, then 2% the ramp continues past exactly 1% and stops at the 2% level, reporting it with "errors > 1%" as the reason."""
        mod = _mod(_LOAD_TEST)
        calls = []
        levels = [(100.0, 0.0), (100.0, 0.01), (100.0, 0.02), (100.0, 0.0)]
        result = mod.ramp(self._measure(levels, calls), start=20, step=20, max_users=80)
        assert calls == [20, 40, 60]
        assert result["limit_users"] == 60
        assert result["reason"] == "errors > 1%"
        assert "Limit: 60 users (errors > 1%)." in mod.format_ramp(result)

    def test_load_test_ramp_reports_no_limit_when_threshold_never_reached(self):
        """Failure path: when every level up to the maximum stays under both thresholds, the ramp ends at the maximum and reports that no limit was found up to N users, not the last level as the limit."""
        mod = _mod(_LOAD_TEST)
        calls = []
        result = mod.ramp(self._measure([(300.0, 0.001)] * 4, calls), start=10, step=10, max_users=40)
        assert calls == [10, 20, 30, 40]
        assert result["limit_users"] is None and result["reason"] is None
        assert result["max_users"] == 40
        text = mod.format_ramp(result)
        assert "No limit found up to 40 users" in text
        assert "Limit:" not in text


# ---------------------------------------------------------------------------
# Story 3: A Ranked List of Off-Season Improvements (review document and index rows)
# ---------------------------------------------------------------------------

_ISSUE_PATH = re.compile(r"/ville-solja/FantasyLeague/issues/\d+")
_PLACEHOLDERS = ("TBD", "TODO", "*(planned)*")


def _read(path):
    assert os.path.exists(path), f"missing: {os.path.relpath(path, _REPO_ROOT)}"
    with open(path, encoding="utf-8") as f:
        return f.read()


def _section(doc, title):
    """Lines under the `## <title>` heading, up to the next `## ` heading."""
    lines, inside = [], False
    for line in doc.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower() == title.lower()
            continue
        if inside:
            lines.append(line)
    assert lines, f"no '## {title}' section"
    return "\n".join(lines)


def _table_rows(text):
    """Cells of every markdown table body row in `text` (header and rule rows skipped)."""
    rows, header_seen = [], False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            header_seen = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not header_seen:
            header_seen = True
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def _issue_links(text):
    """URLs in `text` that are issues of this repository."""
    links = []
    for url in re.findall(r"https?://[^\s)>\]]+", text):
        parsed = urlparse(url)
        if parsed.hostname == "github.com" and _ISSUE_PATH.fullmatch(parsed.path.rstrip("/")):
            links.append(url)
    return links


def _area_rows(doc):
    rows = _table_rows(_section(doc, "Verdict per area"))
    assert all(len(r) == 3 for r in rows), "area table columns: Area | Verdict | Evidence"
    return rows


def _area_row(doc, area):
    found = [r for r in _area_rows(doc) if area.lower() in r[0].lower()]
    assert len(found) == 1, f"expected exactly one row for area '{area}', found {len(found)}"
    return found[0]


class TestReviewDocument:

    def test_review_document_exists_with_measured_target_and_headroom(self):
        """AC Document: `markdown/research/architecture-maturity-review.md` exists and has sections for the measured load, the target load (stated as a multiple of season 16's measured peak) and the headroom found, each containing at least one number."""
        doc = _read(_REVIEW_DOC)
        for title in ("Measured load", "Target load", "Headroom"):
            assert re.search(r"\d", _section(doc, title)), f"no number in '{title}'"
        target = _section(doc, "Target load")
        assert re.search(r"\d+(\.\d+)?\s?[×x]", target), "target load is not stated as a multiple"
        assert "season 16" in target.lower() and "peak" in target.lower()

    def test_review_document_has_no_placeholder_numbers(self):
        """Failure path: the review contains no `TBD`, `TODO`, `*(planned)*` or `<...>` placeholders, and it embeds or quotes output of both `usage_report.py` and `load_test.py --ramp`."""
        doc = _read(_REVIEW_DOC)
        for placeholder in _PLACEHOLDERS:
            assert placeholder not in doc, placeholder
        outside_code = re.sub(r"`[^`\n]*`", "", doc)
        assert not re.search(r"<[A-Za-z][^<>\n]*>", outside_code), "a <...> placeholder is left"
        assert "usage_report.py" in doc and "load_test.py" in doc and "--ramp" in doc
        flat = _flat(doc)
        assert re.search(r"Website accounts: \d+", flat), "no usage report output quoted"
        assert re.search(r"Busiest minute: \d+ actions", flat)
        assert re.search(r"Limit: \d+ users \((p95 > 1 s|errors > 1%)\)\.", flat) or \
            re.search(r"No limit found up to \d+ users", flat), "no ramp output quoted"

    def test_review_document_gives_a_verdict_and_evidence_for_every_area(self):
        """AC Verdict per area: each of the nine AREAS (process model and single-process rule, SQLite, background jobs, external services, caching and rate limits, deployment and recovery, observability, frontend delivery, test and release tooling) has a row or section with exactly one of VERDICTS and non-empty evidence."""
        doc = _read(_REVIEW_DOC)
        assert len(_area_rows(doc)) == len(AREAS)
        for area in AREAS:
            _, verdict, evidence = _area_row(doc, area)
            assert verdict.strip("*").lower() in VERDICTS, (area, verdict)
            assert len(evidence) >= 40, f"evidence for '{area}' is empty or too thin"
        assert "single-process" in _area_row(doc, "process model")[0].lower() + _area_row(doc, "process model")[2].lower()

    def test_review_document_names_all_four_external_services(self):
        """AC Verdict per area: the external services area covers OpenDota, Steam, Twitch and Toornament by name, and the SQLite area covers write contention, backups and size."""
        doc = _read(_REVIEW_DOC)
        external = _area_row(doc, "external services")[2]
        for service in ("OpenDota", "Steam", "Twitch", "Toornament"):
            assert service in external, service
        sqlite_evidence = _area_row(doc, "SQLite")[2].lower()
        for topic in ("write contention", "backup", "size"):
            assert topic in sqlite_evidence, topic

    def test_review_document_ranks_improvements_with_risk_effort_and_load(self):
        """AC Ranked: the improvements list is numbered 1..N without gaps, and every item states a risk, an effort and the load at which it becomes necessary."""
        doc = _read(_REVIEW_DOC)
        section = _section(doc, "Ranked improvements")
        header = [ln for ln in section.splitlines() if ln.strip().startswith("|")][0]
        columns = [c.strip().lower() for c in header.strip().strip("|").split("|")]
        assert columns[:5] == ["#", "improvement", "risk", "effort", "needed at"], columns
        rows = _table_rows(section)
        assert rows, "no improvements listed"
        assert [r[0] for r in rows] == [str(i) for i in range(1, len(rows) + 1)]
        for row in rows:
            number, improvement, risk, effort, needed_at = row[:5]
            assert improvement, number
            assert risk.lower() in ("high", "medium", "low"), (number, risk)
            assert effort.lower() in ("small", "medium", "large"), (number, effort)
            assert re.search(r"\d", needed_at), f"improvement {number}: no load stated"

    def test_review_document_links_an_issue_for_every_fix_before_season_17_item(self):
        """AC Issues: every area or improvement marked "fix before season 17" carries a link whose URL is a GitHub issue of this repository (`.../issues/<N>`, parsed with `urlparse`); a "fix before season 17" item without one fails the test."""
        doc = _read(_REVIEW_DOC)
        marked = [ln for ln in doc.splitlines()
                  if ln.strip().startswith("|") and "fix before season 17" in ln.lower()]
        for line in marked:
            assert _issue_links(line), f"no issue link: {line[:80]}"
        # The check itself: other repositories, pull requests and look-alikes don't count.
        assert _issue_links("see https://github.com/ville-solja/FantasyLeague/issues/251)")
        for bad in ("https://github.com/ville-solja/FantasyLeague/pull/251",
                    "https://github.com/other/FantasyLeague/issues/251",
                    "https://github.com.example.org/ville-solja/FantasyLeague/issues/251",
                    "https://example.org/?u=github.com/ville-solja/FantasyLeague/issues/251",
                    "issue #251"):
            assert not _issue_links(bad), bad

    def test_review_document_is_listed_in_features_readme_research_table(self):
        """AC Indexed: the table under `## Research` in `markdown/features/README.md` has a row linking `../research/architecture-maturity-review.md`, and the Reference row for #251 no longer says "planned"."""
        readme = _read(_FEATURES_README)
        research = _table_rows(_section(readme, "Research"))
        assert any("(../research/architecture-maturity-review.md)" in r[0] and len(r[1]) > 20
                   for r in research)
        assert os.path.exists(_REVIEW_DOC)
        reference = [ln for ln in readme.splitlines()
                     if "(reference/architecture-maturity-review.md)" in ln]
        assert len(reference) == 1
        assert "planned" not in reference[0].lower()

    def test_plan_index_lists_issue_251(self):
        """AC Indexed: `markdown/plans/.issue-index` has exactly one line `251 plan-issue-251-architecture-maturity-review` and that plan file exists."""
        lines = _read(_ISSUE_INDEX).splitlines()
        assert lines.count("251 plan-issue-251-architecture-maturity-review") == 1
        assert [ln for ln in lines if ln.split()[:1] == ["251"]] == \
            ["251 plan-issue-251-architecture-maturity-review"]
        assert os.path.exists(os.path.join(_REPO_ROOT, "markdown", "plans",
                                           "plan-issue-251-architecture-maturity-review.md"))

    def test_pointer_doc_explains_tools_and_links_review(self):
        """Critical Files: `markdown/features/reference/architecture-maturity-review.md` is no longer a planning stub (no "*(planned)*", no "stub created at feature planning time"), shows both script invocations, names the `RATE_LIMIT_*` env vars to relax for a load test, and links the review document; both scripts it names exist under `scripts/`."""
        doc = _read(_POINTER_DOC)
        assert "*(planned)*" not in doc
        assert "stub created at feature planning time" not in doc
        assert "scripts/usage_report.py --db" in doc
        assert "scripts/load_test.py --base-url http://localhost" in doc
        assert "--ramp" in doc and "--allow-remote" in doc
        for name in _mod(_LOAD_TEST).RATE_LIMIT_SETTINGS:
            assert name in doc, name
        assert "markdown/research/architecture-maturity-review.md" in doc
        for script in re.findall(r"scripts/([a-z_]+\.py)", doc):
            assert os.path.exists(os.path.join(_REPO_ROOT, "scripts", script)), script
