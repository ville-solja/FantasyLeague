"""Issue 257: season end workflow (plan-issue-257-season-end-workflow).

Stubs written by /test-planner and filled in by /developer.

Fixtures and patterns to use (copy from test_issue_133_season_reset_clean_slate.py
rather than importing them, as #133 itself does):
  - `db`: the StaticPool in-memory fixture from #133 (overrides conftest's `db`, so a
    TestClient's request thread sees the same rows). Add the autouse `_clean_caches`
    fixture (season_reset.bust_caches before and after).
  - `_user`, `_client(db, login, reauth)` and `_admin_client(db, reauth=True)`: a
    small FastAPI app mounting routers.admin_season (+ admin_backups) with
    SessionMiddleware and a `/_test/login/{id}?fresh=` route that marks a re-auth.
    `reauth=False` gives the 403 `reauth_required` path. The typed phrase goes as a
    query parameter or JSON field (deps.require_typed_confirmation); the new action is
    `season_archive_remove` -> "REMOVE ARCHIVE" in deps.CONFIRM_PHRASES.
  - `_seed_season(db)` (players 1-4, teams 100/200/300, matches 1001-1005, leagues 1
    and 2) and `_end(db, label, champions, **parts)` calling end_season directly.
    Create at least one user before End Season, or no season_archive rows are written.
  - `_reset(db, monkeypatch, ...)` patches `admin_season.backup_sqlite_db` with
    `lambda *a, **k: ...` (keep that exact monkeypatch text; see lessons-learned).
  - `_fill(db, name, n, **over)`, `_FILL_OVERRIDES`, `_fill_cleared`, `_snapshot`,
    `_count` for table-level checks.
  - Frontend source checks: `_read`, `_fe`, `_fn_source` (string checks on
    frontend/app-admin-season.js, index.html, style.css). app-admin-season.js already
    uses confirm() for finals and team signup, so scope the "no confirm()" check to
    the archive-removal functions with `_fn_source`.
  - Check script: run `scripts/season_end_check.py` with
    `subprocess.run([sys.executable, script, path, ...], cwd=_ROOT, env=env,
    capture_output=True, text=True, timeout=...)` as test_issue_145 does, with
    DATABASE_URL popped from env. Build the backup copy as a tmp_path SQLite FILE:
    create_engine(f"sqlite:///{tmp_path/'copy.db'}") + Base.metadata.create_all, then
    insert rows (SeasonArchive, SeasonAccolade, SeasonPlayerStats). Check the file's
    os.stat().st_mtime_ns and bytes before and after.

Existing tests to update in the same change:
  - test_issue_133 `test_reset_season_keeps_kept_tables` docstring names
    finals_brackets, finals_predictions, promo_codes, token_grant_events and
    notifications as kept; they move to CLEARED_TABLES. Its body iterates
    season_reset.KEPT_TABLES, so it still passes, but fix the docstring.
    `test_reset_table_lists_cover_every_table_exactly_once` pins only UPDATED_TABLES
    and a few members, not the full kept list; it must still pass unchanged.
  - `_fill_cleared` fills every cleared table with dummy rows; the eight new tables
    may need `_FILL_OVERRIDES` entries (unique keys, CHECK constraints).
  - test_issue_145's partition test computes scenarios.EXTRA_DELETED_TABLES from
    season_reset's lists, so it should still hold; run it.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from html.parser import HTMLParser

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Float, Integer, create_engine, select, text
from starlette.middleware.sessions import SessionMiddleware

# Registers every existing table on Base before the db fixture runs create_all.
import models  # noqa: F401
import accolades
import deps
import season_reset
from database import Base, get_db
from models import (
    AuditLog, CodeRedemption, FinalsBracket, FinalsPrediction, League, Match, Notification,
    NotificationDismissal, Player, PlayerMatchStats, PromoCode, SeasonAccolade, SeasonArchive,
    SeasonPlayerStats, SeasonTeamResult, TagDefinition, Team, TokenGrantClaim, TokenGrantEvent,
    User, UserTag, Weight,
)


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_SCRIPT = os.path.join(_ROOT, "scripts", "season_end_check.py")
_ARCHIVE_TABLES = ("season_archive", "season_accolades", "season_player_stats",
                   "season_team_results", "audit_logs")


# ---------------------------------------------------------------------------
# Helpers (copied from test_issue_133_season_reset_clean_slate.py)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_caches():
    season_reset.bust_caches()
    yield
    season_reset.bust_caches()


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fe(name):
    return _read("frontend", name)


def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


def _user(db, username, admin=False, tokens=10):
    from auth import hash_password
    u = User(username=username, email=f"{username}@example.com", password_hash=hash_password("secret123"),
             is_admin=admin, tokens=tokens, created_at=int(time.time()))
    db.add(u)
    db.commit()
    return u


def _client(db, login=None, reauth=True):
    import rate_limit
    import sessions
    from routers import admin_backups, admin_season
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-257")
    app.state.limiter = rate_limit.limiter
    app.include_router(admin_season.router)
    app.include_router(admin_backups.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db

    @app.post("/_test/login/{user_id}")
    def _login(user_id: int, request: Request, fresh: bool = True):
        sessions.start_session(request, db, db.get(User, user_id))
        if fresh:
            sessions.mark_reauth(sessions.current_row(request, db))
        db.commit()
        return {"ok": True}

    client = TestClient(app)
    if login is not None:
        assert client.post(f"/_test/login/{login.id}", params={"fresh": reauth}).status_code == 200
    return client


def _admin_client(db, reauth=True):
    admin = db.query(User).filter_by(username="admin").first() or _user(db, "admin", admin=True)
    return _client(db, login=admin, reauth=reauth)


_T0 = 1_000_000
_DAY = 86400
_MATCHES = [
    (1001, 100, 200, True, _T0, False, 1),
    (1002, 100, 200, False, _T0 + 3600, False, 1),
    (1003, 200, 100, True, _T0 + 7 * _DAY, False, 1),
    (1004, 100, 300, True, _T0 + 8 * _DAY, True, 2),
    (1005, 300, 200, False, _T0 + 9 * _DAY, False, 2),
]
_STATS = [
    (1, 100, 1001, 10, 2, 5, True, 30.0), (1, 100, 1002, 3, 5, 2, False, 8.0),
    (1, 100, 1003, 5, 1, 8, False, 15.0), (1, 100, 1004, 99, 0, 99, True, 999.0),
    (2, 100, 1001, 4, 4, 4, False, 10.0), (2, 100, 1002, 6, 2, 1, False, 12.0),
    (2, 300, 1005, 1, 7, 3, False, 2.0),
    (3, 200, 1001, 2, 6, 9, False, 9.0), (3, 200, 1002, 8, 1, 4, True, 25.0),
    (3, 200, 1003, 7, 0, 6, True, 28.0), (3, 200, 1005, 12, 1, 2, False, 26.0),
    (4, 300, 1004, 20, 0, 0, False, 50.0),
]
_CHAMPS = [{"division": "div1", "team_name": "Blues", "player_account_ids": [3]}]


def _seed_season(db):
    from seed import DEFAULT_WEIGHTS
    for w in DEFAULT_WEIGHTS:
        db.add(Weight(key=w["key"], label=w["label"], value=w["value"]))
    db.add(League(id=1, name="Kanaliiga Season 16", is_monitored=True))
    db.add(League(id=2, name="Kanaliiga Season 16 Lower", is_monitored=True))
    for tid, name in ((100, "Reds"), (200, "Blues"), (300, "Greens")):
        db.add(Team(id=tid, name=name))
    for pid, name in ((1, "Alpha"), (2, "Bravo"), (3, "Charlie"), (4, "Delta")):
        db.add(Player(id=pid, name=name, is_active=True))
    for mid, rad, dire, rw, start, excl, league in _MATCHES:
        db.add(Match(match_id=mid, radiant_team_id=rad, dire_team_id=dire, radiant_win=rw,
                     start_time=start, excluded_from_scoring=excl, league_id=league))
    for pid, tid, mid, k, d, a, mvp, pts in _STATS:
        db.add(PlayerMatchStats(player_id=pid, team_id=tid, match_id=mid, kills=k, deaths=d,
                                assists=a, is_mvp=mvp, fantasy_points=pts, last_hits=10 * k))
    db.commit()


def _end(db, label="Season 16", champions=None, **parts):
    from routers.admin_season import SeasonEndBody, end_season
    body = SeasonEndBody(season_label=label, champions=champions, **parts)
    return end_season(body, db=db, admin=dict(_ADMIN))


def _reset(db, monkeypatch, backup="/tmp/claude-257-fake-backup.db", force=True, label=None):
    from routers import admin_season
    from routers.admin_season import SeasonResetBody, reset_season
    monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda *a, **k: backup)
    monkeypatch.setattr(admin_season, "rename_to_season_backup", lambda path, label: path)
    return reset_season(SeasonResetBody(force=force, season_label=label), db=db, admin=dict(_ADMIN))


def _snapshot(db, names):
    db.expire_all()
    return {name: sorted(map(tuple, db.execute(select(Base.metadata.tables[name])).fetchall()), key=repr)
            for name in names}


def _count(db, name):
    return db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()


def _archived_season(db, label="Season 16"):
    """A seeded season with two users, archived as `label`."""
    _seed_season(db)
    _user(db, "alice")
    _user(db, "bob")
    _end(db, label, champions=_CHAMPS)


def _post_end(client, label):
    return client.post("/admin/season/end", json={"season_label": label, "confirm": "END SEASON"})


def _remove(client, label="Season 16", confirm="REMOVE ARCHIVE"):
    params = {"season_label": label}
    if confirm is not None:
        params["confirm"] = confirm
    return client.delete("/admin/season/archive", params=params)


def _season_only_records(db):
    """One linked parent/child pair (or more) in each of the eight season-only tables."""
    u1, u2 = _user(db, "pat"), _user(db, "sam")
    b = FinalsBracket(season_label="Season 16", division="div1", seed1_team_id=100, seed2_team_id=200,
                      seed3_team_id=300, seed4_team_id=400, seed_names_json="{}", set_at=_T0,
                      group_end_at=_T0, seed_source="standings")
    code = PromoCode(code="S16", token_amount=5, created_by_id=u1.id)
    event = TokenGrantEvent(amount=3, start_time=_T0, end_time=_T0 + _DAY, created_by=u1.id, created_at=_T0)
    note = Notification(message="hi", start_time=_T0, end_time=_T0 + _DAY, created_by=u1.id, created_at=_T0)
    db.add_all([b, code, event, note])
    db.flush()
    for u in (u1, u2):
        db.add(FinalsPrediction(bracket_id=b.id, user_id=u.id, sf1_pick=100, sf2_pick=200,
                                final_pick=100, saved_at=_T0))
    db.add(CodeRedemption(code_id=code.id, user_id=u2.id, redeemed_at=_T0))
    db.add(TokenGrantClaim(event_id=event.id, user_id=u2.id, claimed_at=_T0))
    db.add(NotificationDismissal(notification_id=note.id, user_id=u2.id, dismissed_at=_T0))
    db.commit()


_NEW_CLEARED = ("finals_predictions", "finals_brackets", "code_redemptions", "promo_codes",
                "token_grant_claims", "token_grant_events", "notification_dismissals",
                "notifications")
_EXPECTED_COUNTS = {"finals_predictions": 2, "finals_brackets": 1, "code_redemptions": 1,
                    "promo_codes": 1, "token_grant_claims": 1, "token_grant_events": 1,
                    "notification_dismissals": 1, "notifications": 1}


# --- Node harness ----------------------------------------------------------

def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


_DOM_STUBS = r"""
const __els = {};
function __mk(id) {
  const cls = new Set();
  return {id, value: "", checked: false, disabled: false, textContent: "", innerHTML: "", hidden: false, style: {}, cls,
          classList: {add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c)}};
}
const document = {getElementById: id => __els[id] || (__els[id] = __mk(id))};
const API = "";
const ADMIN_CONFIRM_PHRASES = {season_end: "END SEASON", season_reset: "RESET SEASON", season_summary: "SAVE SUMMARY",
                               season_archive_remove: "REMOVE ARCHIVE"};
const __calls = {fetch: [], adminFetch: [], status: {}, typed: []};
function setStatus(id, msg, ok) { __calls.status[id] = msg; document.getElementById(id).textContent = msg; }
function accoladeValueText(kind, v) { return `${v} MVPs`; }
let __typedReply = undefined;
function typedConfirm(action, text) {
  __calls.typed.push({action, text});
  return Promise.resolve(__typedReply === undefined ? ADMIN_CONFIRM_PHRASES[action] : __typedReply);
}
async function withBusy(btn, fn) { return fn(); }
let __fetchReply = {};
async function fetch(url) { __calls.fetch.push(url); return {ok: true, json: async () => __fetchReply}; }
let __adminReply = {};
async function adminFetch(url, opts) {
  __calls.adminFetch.push({url, method: opts && opts.method, body: opts && opts.body ? JSON.parse(opts.body) : null});
  return {ok: true, json: async () => __adminReply};
}
function confirm() { __calls.confirm = true; return true; }
function loadAdminWeeks() {}
function loadLeagues() {}
function loadBackups() {}
function loadSeasonAccolades() {}
"""


def _season_harness(body):
    js = _fe("app-admin-season.js")
    escape = _fn_source(_fe("app-globals.js"), "_escHtml")
    return _run_node(_DOM_STUBS + escape + "\n" + js + """
loadSeasonArchives = async () => { __calls.reloaded = true; };
(async () => {
  let out = null;
""" + body + """
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
""")


# --- Markup ----------------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
         "track", "wbr"}


class _Ancestry(HTMLParser):
    """For every element with an id: the classes of each open ancestor element."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.found = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        if a.get("id"):
            self.found[a["id"]] = {"tag": tag, "classes": classes, "attrs": a,
                                   "ancestors": [c for _, c, _ in self.stack]}
        if tag not in _VOID:
            self.stack.append((tag, classes, a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _ancestry():
    p = _Ancestry()
    p.feed(_fe("index.html"))
    return p.found


def _inside(found, el_id, cls):
    return any(cls in c for c in found[el_id]["ancestors"])


def _css_rule(css, selector):
    start = css.index(selector + " {")
    return css[start:css.index("}", start)]


def _media_block(css, query):
    start = css.index(f"@media {query} {{")
    depth, i = 0, css.index("{", start)
    while True:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start:i]
        i += 1


# --- Check script ----------------------------------------------------------

def _dummy(col, i):
    if isinstance(col.type, Boolean):
        return False
    if isinstance(col.type, Integer):
        return 1000 + i
    if isinstance(col.type, Float):
        return 1.0
    return f"x{i}"


_COUNTER = iter(range(1, 10**6))


def _insert(conn, name, **values):
    table = Base.metadata.tables[name]
    i = next(_COUNTER)
    row = {c.name: _dummy(c, i) for c in table.columns
           if not c.primary_key and not c.nullable and c.default is None and c.server_default is None}
    row.update(values)
    conn.execute(table.insert().values(**row))


def _copy(tmp_path, archives=(), accolades_rows=(), summaries=(), matches=0):
    """A backup-like SQLite FILE with the app's schema and the given rows."""
    path = tmp_path / "copy.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for label, at, users in archives:
            for u in range(users):
                _insert(conn, "season_archive", season_label=label, user_id=u + 1, username=f"u{u}",
                        points=1.0, rank=u + 1, archived_at=at)
        for row in accolades_rows:
            _insert(conn, "season_accolades", **{"source": "season_end", **row})
        for label in summaries:
            _insert(conn, "season_player_stats", season_label=label, player_id=1, games=3)
        for m in range(matches):
            _insert(conn, "matches", match_id=5000 + m)
    engine.dispose()
    return path


_CLEAN_ACCOLADES = (
    {"season_label": "Season 16", "kind": "champion", "division": "div1", "team_name": "Blues",
     "player_account_id": 3},
    {"season_label": "Season 16", "kind": "champion", "division": "div2", "team_name": "Greens",
     "player_account_id": 4},
    {"season_label": "Season 16", "kind": "most_points", "player_account_id": 1, "value": 53.0},
    {"season_label": "Season 15", "kind": "most_points", "player_account_id": 1, "value": 40.0},
)


def _clean_copy(tmp_path):
    return _copy(tmp_path, archives=[("Season 16", 1_700_000_000, 2), ("Season 15", 1_690_000_000, 1)],
                 accolades_rows=_CLEAN_ACCOLADES, summaries=["Season 16", "Season 15"], matches=1)


def _run_script(*args):
    env = {**os.environ, "BACKGROUND_TASKS_ENABLED": "false"}
    env.pop("DATABASE_URL", None)
    return subprocess.run([sys.executable, _SCRIPT, *map(str, args)], cwd=_ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def _load_script():
    spec = importlib.util.spec_from_file_location("season_end_check_257", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Story 1: Archiving a Season Twice Is Refused
# ---------------------------------------------------------------------------

class TestArchiveTwiceRefused:

    def test_normalise_label_trims_collapses_spaces_and_casefolds(self):
        """accolades.normalise_label(" Season  16 ") == normalise_label("season 16") == "season 16"; None and "" give ""."""
        assert accolades.normalise_label(" Season  16 ") == accolades.normalise_label("season 16") == "season 16"
        assert accolades.normalise_label("SEASON\t16") == "season 16"
        assert accolades.normalise_label(None) == "" and accolades.normalise_label("") == ""

    def test_archived_match_returns_existing_label_date_and_users(self, db):
        """accolades.archived_match(db, "season  16") returns the archived "Season 16" with its newest archived_at and user count; an unarchived label returns None."""
        _archived_season(db)
        newest = db.query(SeasonArchive.archived_at).order_by(SeasonArchive.archived_at.desc()).first()[0]
        users = db.query(SeasonArchive).count()
        assert users == 2
        assert accolades.archived_match(db, "season  16") == {"label": "Season 16", "archived_at": newest,
                                                               "users": users}
        assert accolades.archived_match(db, "Season 17") is None
        assert accolades.archived_match(db, "  ") is None

    def _refused(self, db, label):
        _archived_season(db)
        client = _admin_client(db)
        before = _snapshot(db, _ARCHIVE_TABLES)
        resp = _post_end(client, label)
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        day = time.strftime("%Y-%m-%d", time.gmtime(db.query(SeasonArchive).first().archived_at))
        assert detail == f"Season 16 is already archived (archived {day}, 2 users)"
        assert _snapshot(db, _ARCHIVE_TABLES) == before

    def test_end_season_lowercase_variant_of_archived_label_409_writes_nothing(self, db):
        """After "Season 16" is archived, POST /admin/season/end with "season 16" answers 409 naming "Season 16" ("Season 16 is already archived (archived <date>, N users)"); season_archive, season_accolades, season_player_stats, season_team_results and audit_logs are unchanged."""
        self._refused(db, "season 16")

    def test_end_season_double_space_variant_of_archived_label_409_writes_nothing(self, db):
        """After "Season 16" is archived, End Season with "Season  16" answers 409 naming "Season 16", and no rows are added to any table."""
        _archived_season(db)
        client = _admin_client(db)
        before = {name: _count(db, name) for name in Base.metadata.tables}
        resp = _post_end(client, "Season  16")
        assert resp.status_code == 409 and resp.json()["detail"].startswith("Season 16 is already archived")
        assert {name: _count(db, name) for name in Base.metadata.tables} == before

    def test_end_season_exact_repeat_still_409(self, db):
        """End Season with exactly "Season 16" a second time still answers 409, and no rows are added."""
        self._refused(db, "Season 16")

    def test_end_season_different_label_not_refused(self, db):
        """With "Season 16" archived, End Season with "Season 17" is not refused by the near-match check (it archives normally)."""
        _archived_season(db)
        resp = _post_end(_admin_client(db), "Season 17")
        assert resp.status_code == 200, resp.text
        assert db.query(SeasonArchive).filter_by(season_label="Season 17").count() == resp.json()["archived_users"] > 0

    def test_accolades_preview_returns_archived_for_matching_label(self, db):
        """GET /admin/season/accolades-preview?season_label=season%2016 returns `archived: {label: "Season 16", archived_at, users}` when "Season 16" is archived."""
        _archived_season(db)
        data = _admin_client(db).get("/admin/season/accolades-preview", params={"season_label": "season 16"}).json()
        at = db.query(SeasonArchive).first().archived_at
        assert data["archived"] == {"label": "Season 16", "archived_at": at, "users": 2, "has_summary": True}

    def test_accolades_preview_archived_null_for_new_label(self, db):
        """accolades-preview for an unarchived label returns `archived: null`."""
        _archived_season(db)
        client = _admin_client(db)
        assert client.get("/admin/season/accolades-preview", params={"season_label": "Season 17"}).json()["archived"] is None

    def test_end_season_dialog_shows_archived_state_and_disables_button(self):
        """app-admin-season.js: when the preview's `archived` is set, the End Season dialog says the label is already archived, disables the End Season button, and points to Save season summary in the Reset dialog when that label has no summary."""
        out = _season_harness("""
  const el = id => document.getElementById(id);
  const base = {season_label: "Season 16", awards: {}, played_count: 0, teams: [], recorded: {}};
  __fetchReply = {...base, archived: {label: "Season <16>", archived_at: 1700000000, users: 3, has_summary: false}};
  await endSeason();
  const archived = {text: el("endSeasonArchived").textContent, hidden: el("endSeasonArchived").hidden,
                    disabled: el("endSeasonContinueBtn").disabled};
  __fetchReply = {...base, archived: {label: "Season 16", archived_at: 1700000000, users: 3, has_summary: true}};
  await endSeason();
  const withSummary = el("endSeasonArchived").textContent;
  __fetchReply = {...base, archived: null};
  await endSeason();
  out = {archived, withSummary, fresh: {text: el("endSeasonArchived").textContent, hidden: el("endSeasonArchived").hidden,
                                        disabled: el("endSeasonContinueBtn").disabled}};
""")
        a = out["archived"]
        assert a["text"].startswith("Season <16> is already archived (archived ") and "3 users" in a["text"]
        assert a["hidden"] is False and a["disabled"] is True
        assert "Save season summary" in a["text"] and "Reset Season dialog" in a["text"]
        assert "Save season summary" not in out["withSummary"] and "already archived" in out["withSummary"]
        assert out["fresh"] == {"text": "", "hidden": True, "disabled": False}
        # The note is set with textContent, never innerHTML.
        apply = _fn_source(_fe("app-admin-season.js"), "_applyEndSeasonArchived")
        assert "textContent" in apply and "innerHTML" not in apply
        assert "_applyEndSeasonArchived(data.archived)" in _fn_source(_fe("app-admin-season.js"), "endSeasonLabelChanged")


# ---------------------------------------------------------------------------
# Story 2: Remove a Season's Archived Standings
# ---------------------------------------------------------------------------

def _two_seasons(db):
    """Season 15 archived a day before Season 16 (same live data)."""
    _archived_season(db, "Season 15")
    db.query(SeasonArchive).update({SeasonArchive.archived_at: SeasonArchive.archived_at - _DAY})
    db.commit()
    _end(db, "Season 16", champions=_CHAMPS)


class TestRemoveArchive:

    def test_list_archives_returns_labels_newest_first(self, db):
        """GET /admin/season/archives (admin) returns [{season_label, archived_at, users, has_summary}], newest first."""
        _archived_season(db, "Season 15")
        db.query(SeasonArchive).update({SeasonArchive.archived_at: SeasonArchive.archived_at - _DAY})
        db.commit()
        _end(db, "Season 16", store_summary=False)
        rows = _admin_client(db).get("/admin/season/archives").json()
        assert [r["season_label"] for r in rows] == ["Season 16", "Season 15"]
        assert set(rows[0]) == {"season_label", "archived_at", "users", "has_summary"}
        assert rows[0]["archived_at"] > rows[1]["archived_at"]
        assert (rows[0]["users"], rows[0]["has_summary"]) == (2, False)
        assert (rows[1]["users"], rows[1]["has_summary"]) == (2, True)

    def test_list_archives_requires_admin(self, db):
        """GET /admin/season/archives as a non-admin user is refused (403), and without a session 401."""
        bob = _user(db, "bob")
        assert _client(db, login=bob).get("/admin/season/archives").status_code == 403
        assert _client(db).get("/admin/season/archives").status_code == 401

    def test_remove_archive_deletes_only_season_archive_rows(self, db, monkeypatch):
        """DELETE /admin/season/archive?season_label=Season 16 with re-auth and REMOVE ARCHIVE deletes that label's season_archive rows only; other labels' archives, season_accolades, season_player_stats, season_team_results and season backup files are unchanged; the response is {season_label, removed} and says what was kept."""
        from routers import admin_season
        _two_seasons(db)

        def _no_backup(*a, **k):
            raise AssertionError("removing an archive must not touch backups")
        monkeypatch.setattr(admin_season, "backup_sqlite_db", _no_backup)
        monkeypatch.setattr(admin_season, "rename_to_season_backup", _no_backup)
        client = _admin_client(db)
        kept = _snapshot(db, ("season_accolades", "season_player_stats", "season_team_results"))
        s15 = _snapshot(db, ("season_archive",))["season_archive"]
        s15 = [r for r in s15 if "Season 15" in r]
        resp = _remove(client)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert (data["season_label"], data["removed"]) == ("Season 16", 2)
        assert "Accolades" in data["kept"] and "summary" in data["kept"] and "backups" in data["kept"]
        assert db.query(SeasonArchive).filter_by(season_label="Season 16").count() == 0
        assert [r for r in _snapshot(db, ("season_archive",))["season_archive"]] == s15
        assert _snapshot(db, ("season_accolades", "season_player_stats", "season_team_results")) == kept

    def test_remove_archive_writes_audit_entry(self, db):
        """Removing an archive writes one admin_season_archive_removed audit entry whose detail contains "season_label=Season 16 users=N"."""
        _archived_season(db)
        assert _remove(_admin_client(db)).status_code == 200
        rows = db.query(AuditLog).filter_by(action="admin_season_archive_removed").all()
        assert len(rows) == 1 and "season_label=Season 16 users=2" in rows[0].detail
        assert rows[0].actor_username == "admin"

    def test_remove_archive_unknown_label_404(self, db):
        """DELETE /admin/season/archive for a label with no archive answers 404 and writes nothing."""
        _archived_season(db)
        client = _admin_client(db)
        before = {name: _count(db, name) for name in ("season_archive", "audit_logs")}
        assert _remove(client, "Season 99").status_code == 404
        assert {name: _count(db, name) for name in ("season_archive", "audit_logs")} == before

    def test_remove_archive_after_reset_409(self, db, monkeypatch):
        """After Reset Season (season_summary.has_live_data false), DELETE /admin/season/archive answers 409 and the archive rows stay."""
        _archived_season(db)
        _reset(db, monkeypatch)
        resp = _remove(_admin_client(db))
        assert resp.status_code == 409 and "reset" in resp.json()["detail"]
        assert db.query(SeasonArchive).filter_by(season_label="Season 16").count() == 2

    def test_remove_archive_with_newer_archive_409(self, db):
        """When an archive with a later archived_at exists (another label), removing the older one answers 409 and nothing is deleted."""
        _two_seasons(db)
        before = _snapshot(db, ("season_archive", "audit_logs"))
        resp = _remove(_admin_client(db), "Season 15")
        assert resp.status_code == 409 and "newer" in resp.json()["detail"]
        assert _snapshot(db, ("season_archive", "audit_logs")) == before

    def test_remove_archive_without_reauth_403(self, db):
        """Without a recent re-auth, DELETE /admin/season/archive answers 403 reauth_required and the rows stay."""
        _archived_season(db)
        resp = _remove(_admin_client(db, reauth=False))
        assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
        assert db.query(SeasonArchive).count() == 2

    def test_remove_archive_without_phrase_400(self, db):
        """Without the typed phrase REMOVE ARCHIVE (or with a wrong one), DELETE /admin/season/archive answers 400 confirmation_required and the rows stay."""
        _archived_season(db)
        client = _admin_client(db)
        for confirm in (None, "RESET SEASON", "REMOVE"):
            resp = _remove(client, confirm=confirm)
            assert resp.status_code == 400 and resp.json()["detail"] == "confirmation_required"
        assert db.query(SeasonArchive).count() == 2

    def test_remove_archive_requires_admin(self, db):
        """A non-admin user with a fresh re-auth and the phrase is refused (403)."""
        _archived_season(db)
        bob = db.query(User).filter_by(username="bob").one()
        assert _remove(_client(db, login=bob)).status_code == 403
        assert db.query(SeasonArchive).count() == 2

    def test_end_season_works_again_after_archive_removed(self, db):
        """After removing "Season 16"'s archive, End Season with "Season 16" succeeds and writes new season_archive rows; existing accolades get no duplicates."""
        _archived_season(db)
        client = _admin_client(db)
        accolades_before = _snapshot(db, ("season_accolades",))
        assert _remove(client).status_code == 200
        resp = client.post("/admin/season/end", json={"season_label": "Season 16", "champions": _CHAMPS,
                                                      "confirm": "END SEASON", "store_summary": False})
        assert resp.status_code == 200, resp.text
        assert db.query(SeasonArchive).filter_by(season_label="Season 16").count() == resp.json()["archived_users"] == 3
        assert resp.json()["accolades"] == 0
        assert _snapshot(db, ("season_accolades",)) == accolades_before

    def test_confirm_phrase_season_archive_remove_defined(self):
        """deps.CONFIRM_PHRASES["season_archive_remove"] == "REMOVE ARCHIVE", and app-admin.js knows the same phrase."""
        assert deps.CONFIRM_PHRASES["season_archive_remove"] == "REMOVE ARCHIVE"
        assert 'season_archive_remove: "REMOVE ARCHIVE",' in _fe("app-admin.js")

    def test_admin_season_lists_archives_with_in_page_remove_confirmation(self):
        """Admin > Season lists archived seasons (label, date, users) each with a "Remove archive…" button and an in-page confirmation that calls adminFetch DELETE /admin/season/archive; the archive-removal functions never call confirm()."""
        js = _fe("app-admin-season.js")
        load = _fn_source(js, "loadSeasonArchives")
        assert "fetch(`${API}/admin/season/archives`)" in load and "seasonArchiveRow" in load
        row = _fn_source(js, "seasonArchiveRow")
        assert '"Remove archive…"' in row and "removeSeasonArchive(s.season_label" in row
        assert "innerHTML" not in row
        assert "<th>Season</th><th>Archived</th><th>Users</th><th></th>" in _fe("index.html")
        out = _season_harness("""
  __adminReply = {season_label: "Season 16", removed: 4, kept: "Accolades, the season summary and season backups are unchanged"};
  await removeSeasonArchive("Season 16", 4, {});
  const first = {typed: __calls.typed.slice(), admin: __calls.adminFetch.slice(), status: __calls.status.seasonLifecycleStatus,
                 reloaded: !!__calls.reloaded};
  __typedReply = null;
  __calls.adminFetch.length = 0;
  await removeSeasonArchive("Season 16", 4, {});
  out = {first, cancelled: __calls.adminFetch.length, confirm: !!__calls.confirm};
""")
        first = out["first"]
        assert first["typed"][0]["action"] == "season_archive_remove" and "Season 16" in first["typed"][0]["text"]
        assert first["admin"] == [{"url": "/admin/season/archive?season_label=Season%2016", "method": "DELETE",
                                   "body": {"confirm": "REMOVE ARCHIVE"}}]
        assert first["status"].startswith('Removed the archive of "Season 16" (4 users).')
        assert first["reloaded"] is True
        assert out["cancelled"] == 0 and out["confirm"] is False
        for name in ("loadSeasonArchives", "seasonArchiveRow", "removeSeasonArchive"):
            assert "confirm(" not in _fn_source(js, name).replace("typedConfirm(", "")


# ---------------------------------------------------------------------------
# Story 3: Clear Season-Only Records at Reset
# ---------------------------------------------------------------------------

class TestResetClearsSeasonOnlyRecords:

    def test_new_tables_in_cleared_not_kept(self):
        """All eight tables (finals_predictions, finals_brackets, code_redemptions, promo_codes, token_grant_claims, token_grant_events, notification_dismissals, notifications) are in season_reset.CLEARED_TABLES and not in KEPT_TABLES."""
        for name in _NEW_CLEARED:
            assert name in season_reset.CLEARED_TABLES and name not in season_reset.KEPT_TABLES

    def test_new_cleared_tables_ordered_child_first(self):
        """In CLEARED_TABLES each child comes before its parent: finals_predictions before finals_brackets, code_redemptions before promo_codes, token_grant_claims before token_grant_events, notification_dismissals before notifications (and, generally, every FK child among cleared tables precedes its parent)."""
        order = season_reset.CLEARED_TABLES.index
        for child, parent in (("finals_predictions", "finals_brackets"), ("code_redemptions", "promo_codes"),
                              ("token_grant_claims", "token_grant_events"),
                              ("notification_dismissals", "notifications")):
            assert order(child) < order(parent)
        cleared = set(season_reset.CLEARED_TABLES)
        for name in _NEW_CLEARED:
            for fk in Base.metadata.tables[name].foreign_keys:
                parent = fk.column.table.name
                if parent in cleared and parent != name:
                    assert order(name) < order(parent), (name, parent)

    def test_table_groups_still_cover_every_table_exactly_once(self):
        """Every Base.metadata table is in exactly one of TABLE_GROUPS' cleared, updated and kept lists after the move."""
        groups = (season_reset.CLEARED_TABLES, season_reset.UPDATED_TABLES, season_reset.KEPT_TABLES)
        listed = [name for g in groups for name in g]
        assert len(listed) == len(set(listed))
        assert set(listed) == set(Base.metadata.tables)

    def test_reset_empties_the_eight_tables(self, db, monkeypatch):
        """With a bracket and predictions, a promo code and redemption, a token grant event and claim, and a notification and dismissal present (real FK links), after Reset all eight tables are empty."""
        _season_only_records(db)
        assert {name: _count(db, name) for name in _NEW_CLEARED} == _EXPECTED_COUNTS
        _reset(db, monkeypatch)
        assert {name: _count(db, name) for name in _NEW_CLEARED} == dict.fromkeys(_NEW_CLEARED, 0)

    def test_reset_counts_and_preview_list_the_eight_tables(self, db, monkeypatch):
        """GET /admin/season/reset-preview lists the eight tables under `delete` with their counts (not under `keep`), and the reset response's `counts` includes them with the same numbers."""
        _season_only_records(db)
        preview = _admin_client(db).get("/admin/season/reset-preview").json()
        assert {name: preview["delete"][name] for name in _NEW_CLEARED} == _EXPECTED_COUNTS
        assert not set(_NEW_CLEARED) & set(preview["keep"])
        counts = _reset(db, monkeypatch)["counts"]
        assert {name: counts[name] for name in _NEW_CLEARED} == _EXPECTED_COUNTS

    def test_reset_still_keeps_audit_accolades_archives_summaries_tags_accounts(self, db, monkeypatch):
        """Reset with the eight tables filled leaves audit_logs (earlier rows), season_accolades, season_archive, season_player_stats, season_team_results, tag_definitions, user_tags and user accounts unchanged."""
        _archived_season(db)
        _season_only_records(db)
        tag = TagDefinition(key="vip", label="VIP", created_at=_T0)
        db.add(tag)
        db.flush()
        db.add(UserTag(user_id=db.query(User).first().id, tag_id=tag.id, granted_at=_T0, source="admin"))
        db.commit()
        names = ("audit_logs", "season_accolades", "season_archive", "season_player_stats",
                 "season_team_results", "tag_definitions", "user_tags")
        before = _snapshot(db, names)
        users = [(u.id, u.username, u.email) for u in db.query(User).order_by(User.id)]
        _reset(db, monkeypatch)
        after = _snapshot(db, names)
        assert set(before["audit_logs"]) <= set(after["audit_logs"])
        assert len(after["audit_logs"]) == len(before["audit_logs"]) + 1
        assert all(after[n] == before[n] for n in names if n != "audit_logs")
        assert before["season_accolades"] and before["season_archive"] and before["season_player_stats"]
        assert [(u.id, u.username, u.email) for u in db.query(User).order_by(User.id)] == users

    def test_reset_failure_keeps_the_eight_tables(self, db, monkeypatch):
        """When the season backup fails, Reset aborts and the eight tables keep all their rows."""
        from routers import admin_season
        from routers.admin_season import SeasonResetBody, reset_season
        _season_only_records(db)

        def _fail(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(admin_season, "backup_sqlite_db", _fail)
        with pytest.raises(HTTPException) as exc:
            reset_season(SeasonResetBody(force=True), db=db, admin=dict(_ADMIN))
        assert exc.value.status_code == 500
        db.rollback()
        assert {name: _count(db, name) for name in _NEW_CLEARED} == _EXPECTED_COUNTS


# ---------------------------------------------------------------------------
# Story 4: Reset Dialog Fits the Screen
# ---------------------------------------------------------------------------

class TestResetDialogFitsScreen:

    def test_season_dialogs_capped_at_viewport_height(self):
        """style.css caps the season Reset and End Season dialogs at max-height: calc(100vh - 32px) (or equivalent) as a flex column."""
        css = _fe("style.css")
        rule = _css_rule(css, ".modal.season-dialog")
        assert "max-height: calc(100vh - 32px)" in rule
        assert "display: flex" in rule and "flex-direction: column" in rule
        found = _ancestry()
        for modal in ("seasonResetModal", "endSeasonModal"):
            title = "seasonResetTitle" if modal == "seasonResetModal" else "endSeasonTitle"
            dialog = [c for c in found[title]["ancestors"] if "season-dialog" in c]
            assert dialog and "modal" in dialog[0]
            assert any("modal-overlay" in c for c in found[title]["ancestors"])
            assert "modal-overlay" in found[modal]["classes"]

    def test_reset_dialog_body_scrolls_footer_outside(self):
        """index.html #seasonResetModal: the body is a scrolling element (overflow-y: auto) and the title, #seasonResetConfirmInput and the buttons are outside it."""
        assert "overflow-y: auto" in _css_rule(_fe("style.css"), ".season-dialog-body")
        found = _ancestry()
        for el in ("seasonResetDeleteList", "seasonResetKeepList", "seasonResetSummary", "seasonResetWarning"):
            assert _inside(found, el, "season-dialog-body"), el
        for el in ("seasonResetTitle", "seasonResetConfirmInput", "seasonResetModalStatus"):
            assert not _inside(found, el, "season-dialog-body"), el
        assert _inside(found, "seasonResetConfirmInput", "season-dialog-foot")
        html = _fe("index.html")
        modal = html[html.index('id="seasonResetModal"'):html.index("<!-- Typed confirmation")]
        foot = modal[modal.index('class="season-dialog-foot"'):]
        assert 'onclick="confirmSeasonReset()">Reset Season</button>' in foot
        assert 'onclick="closeSeasonResetConfirm()">Cancel</button>' in foot

    def test_end_season_dialog_shares_the_cap(self):
        """index.html #endSeasonModal uses the same capped-dialog class and scrolling body, with the confirmation input and buttons in the footer outside the scroll."""
        found = _ancestry()
        for el in ("endSeasonDialogLabel", "endSeasonAwards", "endSeasonChampsBlock"):
            assert _inside(found, el, "season-dialog-body"), el
        # End Season's typed phrase is asked by the shared typed-confirm dialog after
        # Continue; the footer holds the archived note, the buttons and the status.
        for el in ("endSeasonContinueBtn", "endSeasonArchived", "endSeasonDialogStatus"):
            assert _inside(found, el, "season-dialog-foot") and not _inside(found, el, "season-dialog-body"), el
        assert not _inside(found, "endSeasonTitle", "season-dialog-body")

    def test_preview_lists_return_totals(self):
        """seasonResetPreviewLists (node harness) returns totals for Deleted and Kept, e.g. "Deleted: 14 tables, 12 345 rows"."""
        out = _season_harness("""
  out = seasonResetPreviewLists({season_label: "Season 16", initial_tokens: 5,
    delete: {matches: 12000, player_match_stats: 345, weeks: 0, users_tokens_reset: 3, leagues_unmonitored: 2, demo_clock_override: 1},
    keep: {season_accolades: 40, audit_logs: 0}});
""")
        assert out["deletedTotal"] == "Deleted: 2 tables, 12 345 rows"
        assert out["keptTotal"] == "Kept: 2 tables, 43 rows"
        assert "Matches: 12000" in out["deleted"]

    def test_preview_lists_render_in_details_deleted_open_kept_closed(self):
        """The rendered preview puts each list in a <details>: Deleted has `open`, Kept has none; each <summary> shows the totals line."""
        found = _ancestry()
        assert found["seasonResetDeleteTotal"]["tag"] == "summary" and found["seasonResetKeepTotal"]["tag"] == "summary"
        html = _fe("index.html")
        modal = html[html.index('id="seasonResetModal"'):html.index("<!-- Typed confirmation")]

        class _Details(HTMLParser):
            def __init__(self):
                super().__init__()
                self.details, self.open = [], None

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "details":
                    self.open = "open" in a
                if tag in ("summary", "ul") and self.open is not None:
                    self.details.append((tag, a.get("id"), self.open))

            def handle_endtag(self, tag):
                if tag == "details":
                    self.open = None
        p = _Details()
        p.feed(modal)
        assert ("summary", "seasonResetDeleteTotal", True) in p.details
        assert ("ul", "seasonResetDeleteList", True) in p.details
        assert ("summary", "seasonResetKeepTotal", False) in p.details
        assert ("ul", "seasonResetKeepList", False) in p.details
        out = _season_harness("""
  const el = id => document.getElementById(id);
  __fetchReply = {season_label: "Season 16", initial_tokens: 5, delete: {matches: 2, users_tokens_reset: 1},
                  keep: {season_accolades: 4}, warning: null};
  await openSeasonResetConfirm();
  out = {del: el("seasonResetDeleteTotal").textContent, keep: el("seasonResetKeepTotal").textContent};
""")
        assert out == {"del": "Deleted: 1 table, 2 rows", "keep": "Kept: 2 tables, 5 rows"}

    def test_preview_lists_stack_at_phone_width(self):
        """style.css shows Deleted and Kept side by side on wide screens and stacks them under a narrow media query, with no fixed width that would scroll sideways at 360 px."""
        css = _fe("style.css")
        wide = _css_rule(css, ".season-reset-lists")
        assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in wide
        narrow = _media_block(css, "(max-width: 640px)")
        assert ".season-reset-lists { grid-template-columns: 1fr; }" in narrow
        width = _css_rule(css, ".season-reset-modal")
        assert "width: min(760px, calc(100vw - 32px))" in width and "max-width: none" in width
        assert "overflow-x: hidden" in _css_rule(css, ".season-dialog-body")

    def test_season_dialogs_never_use_confirm(self):
        """The Reset and End Season dialog functions in app-admin-season.js (openSeasonResetConfirm, confirmSeasonReset, endSeason, confirmEndSeason, the archive removal functions) never call confirm()."""
        js = _fe("app-admin-season.js")
        for name in ("openSeasonResetConfirm", "confirmSeasonReset", "endSeason", "confirmEndSeason",
                     "endSeasonLabelChanged", "_applyEndSeasonArchived", "loadSeasonArchives",
                     "seasonArchiveRow", "removeSeasonArchive", "saveSeasonSummary"):
            src = _fn_source(js, name).replace("typedConfirm(", "")
            assert "confirm(" not in src, name


# ---------------------------------------------------------------------------
# Story 5: End a Season Without Breaking the Data
# ---------------------------------------------------------------------------

class TestSeasonEndCheckScript:

    def test_check_script_opens_backup_read_only(self, tmp_path):
        """scripts/season_end_check.py opens the file with sqlite3 mode=ro (source check) and a run leaves the file's bytes and mtime unchanged."""
        src = _read("scripts", "season_end_check.py")
        assert "?mode=ro" in src and "uri=True" in src
        path = _clean_copy(tmp_path)
        old = time.time() - 3600
        os.utime(path, (old, old))
        stat, data = os.stat(path).st_mtime_ns, path.read_bytes()
        res = _run_script(path)
        assert res.returncode == 0, res.stdout + res.stderr
        assert os.stat(path).st_mtime_ns == stat and path.read_bytes() == data
        assert sorted(os.listdir(tmp_path)) == ["copy.db"]

    def test_check_script_reports_near_duplicate_labels(self, tmp_path):
        """On a copy with archives "Season 16" and "season  16", the script lists them as matching labels and exits 1."""
        path = _copy(tmp_path, archives=[("Season 16", 1_700_000_000, 2), ("season  16", 1_700_100_000, 2)],
                     summaries=["Season 16", "season  16"])
        res = _run_script(path)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "'Season 16', 'season  16'" in res.stdout
        assert "one season under different spellings" in res.stdout

    def test_check_script_reports_duplicate_champions(self, tmp_path):
        """On a copy with two champion teams for one label and division, the script reports it and exits 1."""
        rows = _CLEAN_ACCOLADES + ({"season_label": "Season 16", "kind": "champion", "division": "div1",
                                    "team_name": "Reds", "player_account_id": 9, "source": "admin"},)
        path = _copy(tmp_path, archives=[("Season 16", 1_700_000_000, 2)], accolades_rows=rows,
                     summaries=["Season 16", "Season 15"])
        res = _run_script(path)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "Season 16 div1: 2 champion teams (Blues, Reds)" in res.stdout

    def test_check_script_reports_season_end_and_admin_duplicate_award(self, tmp_path):
        """On a copy with a source=season_end and a source=admin row for the same player and award, the script reports the duplicate and exits 1."""
        rows = _CLEAN_ACCOLADES + ({"season_label": "Season 16", "kind": "most_points", "player_account_id": 1,
                                    "user_id": 7, "value": 53.0, "source": "admin"},)
        path = _copy(tmp_path, archives=[("Season 16", 1_700_000_000, 2)], accolades_rows=rows,
                     summaries=["Season 16", "Season 15"])
        res = _run_script(path)
        assert res.returncode == 1, res.stdout + res.stderr
        assert ("most_points for player 1 in Season 16 recorded by End Season (season_end) "
                "and by hand (admin)") in res.stdout

    def test_check_script_reports_missing_summary(self, tmp_path):
        """For an archived label with no season_player_stats rows, the script says it has no stored summary."""
        path = _copy(tmp_path, archives=[("Season 16", 1_700_000_000, 2)], matches=1)
        res = _run_script(path)
        assert "Season 16: no stored summary" in res.stdout
        # Still fixable while the live matches are there: a problem.
        assert res.returncode == 1 and "Save season summary" in res.stdout

    def test_check_script_prints_archives_counts_and_reset_groups(self, tmp_path):
        """On a clean copy the script prints the archived labels with dates and user counts, accolade counts per label/kind/source, and what Reset would delete and keep."""
        res = _run_script(_clean_copy(tmp_path))
        out = res.stdout
        assert "Season 16: archived 2023-11-14, 2 users" in out
        assert "Season 15: archived 2023-07-22, 1 users" in out
        assert "Season 16 / champion / season_end: 2" in out and "Season 16 / most_points / season_end: 1" in out
        deleted = out[out.index("Reset would delete:"):out.index("Reset would keep:")]
        kept = out[out.index("Reset would keep:"):]
        assert "  matches: 1" in deleted and "  finals_predictions: 0" in deleted
        assert "  season_archive: 3" in kept and "  season_accolades: 4" in kept

    def test_check_script_clean_copy_exits_0(self, tmp_path):
        """On a clean copy (one archive, one champion per division, no duplicates, summary stored) the script exits 0."""
        res = _run_script(_clean_copy(tmp_path))
        assert res.returncode == 0, res.stdout + res.stderr
        assert "No problems found." in res.stdout

    def test_check_script_label_option_limits_report(self, tmp_path):
        """--label "Season 16" limits the per-label report to that label (and its normalised matches)."""
        res = _run_script(_clean_copy(tmp_path), "--label", "season  16")
        out = res.stdout
        assert "Season 16: archived" in out and "Season 15: archived" not in out
        assert "Season 16 / champion / season_end: 2" in out and "Season 15 /" not in out
        assert res.returncode == 0

    def test_check_script_missing_file_fails_without_creating_it(self, tmp_path):
        """A path that doesn't exist makes the script exit non-zero and no file is created there."""
        path = tmp_path / "missing.db"
        res = _run_script(path)
        assert res.returncode != 0 and "No such file" in res.stderr
        assert not path.exists() and os.listdir(tmp_path) == []

    def test_check_script_normalise_label_matches_accolades(self):
        """The script's normalise_label gives the same result as accolades.normalise_label for a set of labels (spaces, tabs, case, None, "")."""
        script = _load_script()
        for label in ("Season 16", " season  16 ", "SEASON\t16", "S16", "Kausi 16 ", "ÄÖ  ß", None, ""):
            assert script.normalise_label(label) == accolades.normalise_label(label), label

    def test_season_lifecycle_doc_has_runbook(self):
        """markdown/features/reference/season-lifecycle.md has a "Season 16 → 17 runbook" section naming backup, season_end_check.py, Save season summary, Reset Season and Remove archive, with what to do when the check finds duplicates."""
        doc = _read("markdown", "features", "reference", "season-lifecycle.md")
        section = doc[doc.index("Season 16 → 17 runbook"):]
        for phrase in ("backup", "season_end_check.py", "Save season summary", "Reset Season",
                       "Remove archive", "duplicate"):
            assert phrase in section, phrase
