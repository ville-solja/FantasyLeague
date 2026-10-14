"""Tests for plan-issue-185-atomic-roster-and-token-operations.

Covers the five user stories in
markdown/plans/plan-issue-185-atomic-roster-and-token-operations.md:

1. Draws Never Overfill the Roster (`draw_card` / `draw_booster` in
   backend/routers/cards.py activate only via `card_utils._activate_card_atomic`;
   the Twitch panel's `twitch.draw` / `twitch.draw_team` call the same functions).
2. The Database Refuses Duplicate Active Players (migration
   `037_cards_active_player_unique` in backend/migrate.py: repair, then the partial
   unique index `ux_cards_owner_player_active`; the same index declared in models.py).
3. Token Balances Change Atomically (`database.credit_tokens(db, user_id, amount)`
   next to `spend_tokens`; all ORM credits replaced, including
   `soft_accounts.merge_soft_into` / `reverse_merge`).
4. Promo Codes Respect Their Use Cap Under Load (`redeem_code` in
   backend/routers/admin_users.py inserts with `INSERT ... SELECT ... WHERE`).
5. Website Actions Wait for Their Answer (frontend in-flight guards: a
   `withBusy(btn, fn)` helper in frontend/app-globals.js and a `_rosterBusy`
   flag in frontend/app-roster.js) -- static checks on the JS source.

--- Notes for the developer: concurrency-test mechanics (plan Step 6) ---
* Do NOT use the in-memory `db` fixture for races: one in-memory connection
  cannot show a race, and a plain `sqlite:///:memory:` engine gives each new
  connection its own private database.
* Use the `file_db_sessionmaker` fixture below: a file-based SQLite database in
  `tmp_path` with `PRAGMA journal_mode=WAL` (set on connect), `check_same_thread=False`
  and a generous `timeout` so writers queue on SQLite's write lock rather than
  failing with "database is locked". It is adapted from the fixture of the same name
  in tests/test_issue_125_roster_limit_race_fix.py (that one has no WAL and uses a
  ThreadPoolExecutor without a barrier).
* Use `_run_concurrently(fn, args_list)` below: N threads, each opening its OWN
  Session from the factory (Sessions are not thread-safe), all released at once by a
  `threading.Barrier`, calling the plain functions (`draw_card`, `draw_booster`,
  `activate_card`, `redeem_code`, `credit_tokens` + `spend_tokens`) with
  `current_user={"user_id": ...}`, as test_issue_125 does.
* Seed with a separate setup session, commit, close; verify with a fresh session.
* Run the concurrency tests several times locally; they must never flake.
* Migration tests: follow tests/test_migrate.py -- build a legacy-shaped engine
  (or create_all, then DROP INDEX ux_cards_owner_player_active to simulate a
  pre-037 database), seed rows with raw SQL, call `migrate.run_migrations(engine)`,
  then inspect with `PRAGMA index_list(cards)` / SELECTs. `run_migrations` is
  idempotent and must stay so (TestMigrationsIdempotent).
* Suite size: bump `test_issue_85_split_admin_router.py`'s pass/skip baseline by
  reading the real "N passed" from the failing run (see lessons-learned 2026-10-11).
* Helpers `_make_user`, `_make_player`, `_make_card` mirror test_issue_125. Draw
  tests also need a League / weights setup that `draw_card` accepts; copy the
  seeding used by the existing draw tests (grep `draw_card(` in backend/tests/).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import threading

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import models as _models  # noqa: F401 — registers all tables in Base.metadata
from database import Base
from models import Card, Player, User


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def file_db_sessionmaker(tmp_path):
    """A shared file-based SQLite database in WAL mode + sessionmaker, for tests
    that exercise a real race across threads. Each thread must open its own
    Session from this factory."""
    db_path = tmp_path / "race.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    yield SessionFactory
    engine.dispose()


def _run_concurrently(fn, args_list, timeout=60):
    """Run fn(*args) in one thread per entry of args_list, all released at once by
    a threading.Barrier. Returns a list of (result, exception) in input order."""
    barrier = threading.Barrier(len(args_list))
    results = [None] * len(args_list)

    def _worker(i, args):
        barrier.wait()
        try:
            results[i] = (fn(*args), None)
        except Exception as exc:  # noqa: BLE001 — collected for the test to assert on
            results[i] = (None, exc)

    threads = [threading.Thread(target=_worker, args=(i, a)) for i, a in enumerate(args_list)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    return results


def _make_user(db, tokens=10, username="tester", email="t@t.com"):
    u = User(username=username, email=email, password_hash="x", tokens=tokens)
    db.add(u)
    db.flush()
    return u


def _make_player(db, player_id=10, name="PlayerOne"):
    p = Player(id=player_id, name=name)
    db.add(p)
    db.flush()
    return p


def _make_card(db, owner_id, player_id, is_active=False, card_type="common", slot_index=None):
    c = Card(owner_id=owner_id, player_id=player_id, card_type=card_type,
             league_id=None, is_active=is_active, generation=1, slot_index=slot_index)
    db.add(c)
    db.flush()
    return c



# More helpers (issue #185 implementation)

import inspect
import json
import logging
import re
import shutil
import subprocess
import time

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _seed_players(db, n, start=1000):
    return [_make_player(db, player_id=start + i, name=f"P{start + i}") for i in range(n)]


def _seed_team(db, team_id, player_ids):
    """A team whose players have a match row, so draw_booster can pick them."""
    from models import PlayerMatchStats, Team
    db.add(Team(id=team_id, name=f"Team{team_id}"))
    for pid in player_ids:
        db.add(PlayerMatchStats(player_id=pid, match_id=9000 + team_id, team_id=team_id,
                                fantasy_points=1.0, kills=1))
    db.flush()


def _active_cards(session, user_id):
    return session.query(Card).filter(Card.owner_id == user_id, Card.is_active == True).all()  # noqa: E712


def _assert_roster_valid(session, user_id, limit):
    active = _active_cards(session, user_id)
    assert len(active) <= limit
    players = [c.player_id for c in active]
    assert len(players) == len(set(players)), "two active cards for one player"
    return active


def _soft_user(db, opaque, tokens):
    now = int(time.time())
    u = User(username=None, email=None, password_hash=None, tokens=tokens, account_type="twitch",
             twitch_user_id=opaque, created_at=now - 7 * 86400, last_seen_at=now)
    db.add(u)
    db.flush()
    return u


def _read(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _js_body(src, name):
    """Body of `[async] function name(...) { ... }` up to its closing brace at column 0."""
    m = re.search(r"(?:async )?function " + re.escape(name) + r"\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
    assert m, name
    return m.group(1)


def _legacy_037_engine(tmp_path):
    """A create_all database without ux_cards_owner_player_active: a pre-037 database."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX ux_cards_owner_player_active"))
    return engine


def _seed_raw(engine, sql_rows):
    with engine.begin() as conn:
        for sql, params in sql_rows:
            conn.execute(text(sql), params)


def _card_rows(engine):
    with engine.connect() as conn:
        return {r.id: (r.owner_id, r.player_id, bool(r.is_active), r.slot_index) for r in conn.execute(
            text("SELECT id, owner_id, player_id, is_active, slot_index FROM cards"))}


def _index_names(engine):
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(text("PRAGMA index_list(cards)"))}


def _seed_repair_case(engine):
    """User 1: 7 active cards, two of player 11 (slots 3 and 0) and two of player 12
    (slot NULL and slot 1), more than ROSTER_LIMIT=5 distinct after dedupe too.
    User 2: a valid roster. User 3: no active cards."""
    rows = [("INSERT INTO users (id, username, tokens, account_type, session_version) "
             "VALUES (:id, :u, 0, 'full', 0)",
             {"id": uid, "u": f"user{uid}"}) for uid in (1, 2, 3)]
    for pid in range(11, 20):
        rows.append(("INSERT INTO players (id, name, is_active) VALUES (:id, :n, 1)", {"id": pid, "n": f"P{pid}"}))
    cards = [
        # id, owner, player, active, slot
        (1, 1, 11, 1, 3),
        (2, 1, 11, 1, 0),     # same player, lower slot: kept, card 1 benched
        (3, 1, 12, 1, None),  # same player as 4 but no slot: benched
        (4, 1, 12, 1, 1),
        (5, 1, 13, 1, 2),
        (6, 1, 14, 1, 4),
        (7, 1, 15, 1, 5),
        (8, 1, 16, 1, None),  # sixth distinct active player: beyond the limit, benched
        (9, 1, 17, 0, None),
        (10, 2, 11, 1, 0),
        (11, 2, 12, 1, 1),
        (12, 2, 12, 0, None),
        (13, 3, 11, 0, None),
    ]
    for cid, owner, pid, active, slot in cards:
        rows.append(("INSERT INTO cards (id, owner_id, player_id, card_type, is_active, generation, "
                     "slot_index) VALUES (:id, :o, :p, 'common', :a, 1, :s)",
                     {"id": cid, "o": owner, "p": pid, "a": active, "s": slot}))
    _seed_raw(engine, rows)


# ---------------------------------------------------------------------------
# Story 1: Draws Never Overfill the Roster
# ---------------------------------------------------------------------------

class TestDrawsNeverOverfillTheRoster:

    def test_draw_card_activates_new_card_when_roster_has_room(self, db):
        """draw_card activates the new card via _activate_card_atomic when the roster has room and no duplicate player; response is_active is True."""
        from routers.cards import draw_card
        user = _make_user(db)
        _seed_players(db, 3)
        db.commit()
        data = draw_card(db, {"user_id": user.id})
        assert data["is_active"] is True
        assert db.get(Card, data["id"]).is_active is True
        assert data["tokens"] == 9

    def test_draw_card_benches_new_card_when_roster_full(self, db):
        """When _activate_card_atomic returns False (roster at ROSTER_LIMIT), the drawn card stays on the bench and the draw still succeeds."""
        from routers.cards import draw_card, ROSTER_LIMIT
        user = _make_user(db)
        players = _seed_players(db, ROSTER_LIMIT + 1)
        for i, p in enumerate(players[:ROSTER_LIMIT]):
            _make_card(db, user.id, p.id, is_active=True, slot_index=i)
        db.commit()
        data = draw_card(db, {"user_id": user.id})
        assert data["player_id"] == players[-1].id  # the one player not owned yet
        assert data["is_active"] is False
        assert db.get(Card, data["id"]).is_active is False
        assert len(_active_cards(db, user.id)) == ROSTER_LIMIT
        assert data["tokens"] == 9

    def test_draw_card_benches_new_card_when_player_already_active(self, db):
        """A drawn card whose player already has an active card in the roster stays on the bench (duplicate-player check in the same UPDATE)."""
        from routers.cards import draw_card
        user = _make_user(db)
        player = _make_player(db)
        _make_card(db, user.id, player.id, is_active=True, slot_index=0)
        db.commit()
        data = draw_card(db, {"user_id": user.id})  # only player: drawn again
        assert data["player_id"] == player.id
        assert data["is_active"] is False
        assert db.get(Card, data["id"]).is_active is False
        assert len(_active_cards(db, user.id)) == 1

    def test_draw_booster_activates_only_via_atomic_helper(self, db, monkeypatch):
        """draw_booster activates the new card only through _activate_card_atomic: active when there is room, benched when full or duplicate, draw still succeeds."""
        import routers.cards as cards
        calls = []
        real = cards._activate_card_atomic

        def spy(*args, **kwargs):
            result = real(*args, **kwargs)
            calls.append(result)
            return result

        monkeypatch.setattr(cards, "_activate_card_atomic", spy)
        user = _make_user(db, tokens=30)
        lone, p2, p3 = _seed_players(db, 3)
        _seed_team(db, 1, [lone.id])
        _seed_team(db, 2, [p2.id, p3.id])
        db.commit()

        first = cards.draw_booster(1, db, {"user_id": user.id})
        assert first["is_active"] is True and db.get(Card, first["id"]).is_active is True
        # Team 1's only player is owned and active: drawn again, benched as a duplicate.
        dup = cards.draw_booster(1, db, {"user_id": user.id})
        assert dup["player_id"] == lone.id
        assert dup["is_active"] is False and db.get(Card, dup["id"]).is_active is False
        assert calls == [True, False]

        # Fill the roster, then a booster draw from another team is benched.
        for i in range(cards.ROSTER_LIMIT - 1):
            _make_card(db, user.id, _make_player(db, 5000 + i, f"F{i}").id, is_active=True)
        db.commit()
        full = cards.draw_booster(2, db, {"user_id": user.id})
        assert full["is_active"] is False and db.get(Card, full["id"]).is_active is False
        assert calls[-1] is False
        assert full["tokens"] == 30 - 3 * 3

    def test_draw_card_response_is_active_matches_stored_value(self, db):
        """The draw response's is_active equals the card's stored is_active, for both the activated and the benched case."""
        from routers.cards import draw_card, ROSTER_LIMIT
        user = _make_user(db, tokens=ROSTER_LIMIT + 3)
        _seed_players(db, ROSTER_LIMIT + 3)
        db.commit()
        seen = set()
        for _ in range(ROSTER_LIMIT + 3):
            data = draw_card(db, {"user_id": user.id})
            db.expire_all()
            assert data["is_active"] is db.get(Card, data["id"]).is_active
            seen.add(data["is_active"])
        assert seen == {True, False}
        assert len(_active_cards(db, user.id)) == ROSTER_LIMIT

    def test_draw_card_no_longer_uses_count_then_assign(self):
        """Static: draw_card and draw_booster in routers/cards.py no longer assign `card.is_active = active_count < ROSTER_LIMIT`; they call _activate_card_atomic."""
        src = _read("backend/routers/cards.py")
        assert "active_count < ROSTER_LIMIT" not in src
        # The only remaining ORM assignment is deactivate_card's `card.is_active = False`.
        assert set(re.findall(r"card\.is_active\s*=(?!=)\s*(\S+)", src)) == {"False"}
        import routers.cards as cards
        for fn in (cards.draw_card, cards.draw_booster):
            body = inspect.getsource(fn)
            assert "_activate_new_card(db, card, user_id)" in body
            assert "active_count" not in body
        assert "_activate_card_atomic(" in inspect.getsource(cards._activate_new_card)

    def test_concurrent_draw_card_never_exceeds_roster_limit(self, file_db_sessionmaker):
        """Ten concurrent draws for a player with an empty roster leave exactly ROSTER_LIMIT active cards and no two active cards with the same player_id."""
        from routers.cards import draw_card, ROSTER_LIMIT
        Factory = file_db_sessionmaker
        setup = Factory()
        user = _make_user(setup, tokens=20)
        _seed_players(setup, 100)
        setup.commit()
        uid = user.id
        setup.close()

        def _draw():
            s = Factory()
            try:
                return draw_card(s, {"user_id": uid})
            finally:
                s.close()

        results = _run_concurrently(_draw, [()] * 10)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            active = _assert_roster_valid(verify, uid, ROSTER_LIMIT)
            assert len(active) == ROSTER_LIMIT
            assert verify.query(Card).filter(Card.owner_id == uid).count() == 10
            stored = {c.id: c.is_active for c in verify.query(Card).filter(Card.owner_id == uid)}
            assert all(stored[r["id"]] is r["is_active"] for r, _ in results)
            assert verify.get(User, uid).tokens == 10
        finally:
            verify.close()

    def test_concurrent_draw_booster_never_exceeds_roster_limit(self, file_db_sessionmaker):
        """Concurrent booster draws for one player never leave more than ROSTER_LIMIT active cards or duplicate active players."""
        from routers.cards import draw_booster, ROSTER_LIMIT
        Factory = file_db_sessionmaker
        setup = Factory()
        user = _make_user(setup, tokens=100)
        players = _seed_players(setup, 40)
        _seed_team(setup, 1, [p.id for p in players[:20]])
        _seed_team(setup, 2, [p.id for p in players[20:]])
        setup.commit()
        uid = user.id
        setup.close()

        def _draw(team_id):
            s = Factory()
            try:
                return draw_booster(team_id, s, {"user_id": uid})
            finally:
                s.close()

        results = _run_concurrently(_draw, [(1 + i % 2,) for i in range(10)])
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            active = _assert_roster_valid(verify, uid, ROSTER_LIMIT)
            assert len(active) == ROSTER_LIMIT
            assert verify.get(User, uid).tokens == 100 - 10 * 3
        finally:
            verify.close()

    def test_concurrent_draw_and_activate_never_exceed_roster_limit(self, file_db_sessionmaker):
        """A draw running concurrently with POST /roster/{card_id}/activate (activate_card) never leaves more than ROSTER_LIMIT active cards."""
        from routers.cards import activate_card, draw_card, ROSTER_LIMIT
        Factory = file_db_sessionmaker
        setup = Factory()
        user = _make_user(setup, tokens=20)
        players = _seed_players(setup, 100)
        bench_ids = [_make_card(setup, user.id, p.id).id for p in players[:ROSTER_LIMIT + 2]]
        setup.commit()
        uid = user.id
        setup.close()

        def _act(kind, card_id):
            s = Factory()
            try:
                if kind == "draw":
                    return draw_card(s, {"user_id": uid})
                try:
                    return activate_card(card_id, s, {"user_id": uid})
                except HTTPException as exc:
                    return exc.status_code
            finally:
                s.close()

        args = [("activate", cid) for cid in bench_ids] + [("draw", None)] * 8
        results = _run_concurrently(_act, args)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            active = _assert_roster_valid(verify, uid, ROSTER_LIMIT)
            assert len(active) == ROSTER_LIMIT
        finally:
            verify.close()

    def test_concurrent_swaps_onto_one_active_card_never_overfill(self, file_db_sessionmaker):
        """Several swaps that target the same active card (double drop, two tabs): exactly one
        happens. Before #185 the bench card was activated first and the outgoing card's
        deactivation was not checked, so every later swap added a card to a full roster."""
        from routers.cards import ROSTER_LIMIT, SwapRequest, swap_roster
        Factory = file_db_sessionmaker
        setup = Factory()
        user = _make_user(setup)
        players = _seed_players(setup, ROSTER_LIMIT + 6)
        active = [_make_card(setup, user.id, p.id, is_active=True, slot_index=i)
                  for i, p in enumerate(players[:ROSTER_LIMIT])]
        bench_ids = [_make_card(setup, user.id, p.id).id for p in players[ROSTER_LIMIT:]]
        setup.commit()
        uid, target = user.id, active[0].id
        setup.close()

        def _swap(bench_id):
            s = Factory()
            try:
                swap_roster(SwapRequest(bench_card_id=bench_id, active_card_id=target, slot_index=0),
                            {"user_id": uid}, s)
                return True
            except HTTPException as exc:
                # The outgoing card was benched by another swap: 404 like the route's own check.
                assert (exc.status_code, exc.detail) == (404, "Card not found")
                return False
            finally:
                s.close()

        results = _run_concurrently(_swap, [(b,) for b in bench_ids])
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        assert sum(1 for r, _ in results if r) == 1
        verify = Factory()
        try:
            assert len(_assert_roster_valid(verify, uid, ROSTER_LIMIT)) == ROSTER_LIMIT
            assert verify.get(Card, target).is_active is False
        finally:
            verify.close()

    def test_concurrent_twitch_panel_draws_never_exceed_roster_limit(self, file_db_sessionmaker):
        """The Twitch panel's draw and booster draw (twitch.draw / twitch.draw_team, which call draw_card / draw_booster) get the same roster-limit guarantee under concurrency."""
        import twitch
        from routers.cards import ROSTER_LIMIT
        Factory = file_db_sessionmaker
        setup = Factory()
        soft = _soft_user(setup, "Uracer", tokens=100)
        players = _seed_players(setup, 60)
        _seed_team(setup, 1, [p.id for p in players[:30]])
        setup.commit()
        uid = soft.id
        setup.close()
        payload = {"channel_id": "chan", "role": "viewer", "opaque_user_id": "Uracer"}

        def _draw(kind):
            s = Factory()
            try:
                if kind == "draw":
                    return twitch.draw(payload, s)
                return twitch.draw_team(1, payload, s)
            finally:
                s.close()

        results = _run_concurrently(_draw, [("draw",), ("team",)] * 5)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            active = _assert_roster_valid(verify, uid, ROSTER_LIMIT)
            assert len(active) == ROSTER_LIMIT
            assert verify.get(User, uid).tokens == 100 - 5 * 1 - 5 * 3
        finally:
            verify.close()


# ---------------------------------------------------------------------------
# Story 2: The Database Refuses Duplicate Active Players
# ---------------------------------------------------------------------------

class TestDatabaseRefusesDuplicateActivePlayers:

    def test_migration_037_repairs_over_limit_roster_and_duplicates(self, tmp_path, monkeypatch):
        """Migration 037 deactivates active duplicates of a player and active cards beyond ROSTER_LIMIT per owner, keeping the lowest slot_index, then the lowest id."""
        from migrate import run_migrations
        monkeypatch.setenv("ROSTER_LIMIT", "5")
        engine = _legacy_037_engine(tmp_path)
        _seed_repair_case(engine)
        run_migrations(engine)
        rows = _card_rows(engine)
        active_u1 = sorted(cid for cid, (owner, _, active, _) in rows.items() if owner == 1 and active)
        # Duplicates: card 2 (slot 0) beats card 1 (slot 3); card 4 (slot 1) beats card 3
        # (no slot). Then 6 distinct remain (2, 4, 5, 6, 7, 8): by slot 0,1,2,4,5 then NULL,
        # so card 8 goes.
        assert active_u1 == [2, 4, 5, 6, 7]
        for cid in (1, 3, 8):
            assert rows[cid][2] is False and rows[cid][3] is None
        assert rows[9][2] is False  # already benched, untouched
        engine.dispose()

    def test_migration_037_respects_roster_limit_env(self, tmp_path, monkeypatch):
        """ROSTER_LIMIT from the environment sets how many active cards the repair keeps."""
        from migrate import run_migrations
        monkeypatch.setenv("ROSTER_LIMIT", "3")
        engine = _legacy_037_engine(tmp_path)
        _seed_repair_case(engine)
        run_migrations(engine)
        rows = _card_rows(engine)
        assert sorted(cid for cid, r in rows.items() if r[0] == 1 and r[2]) == [2, 4, 5]
        engine.dispose()

    def test_migration_037_leaves_valid_rosters_untouched(self, tmp_path, monkeypatch):
        """Owners with at most ROSTER_LIMIT active cards and no duplicate active players are not changed by the repair."""
        from migrate import run_migrations
        monkeypatch.setenv("ROSTER_LIMIT", "5")
        engine = _legacy_037_engine(tmp_path)
        _seed_repair_case(engine)
        before = _card_rows(engine)
        run_migrations(engine)
        after = _card_rows(engine)
        for cid in (10, 11, 12, 13):
            assert after[cid] == before[cid]
        engine.dispose()

    def test_migration_037_logs_count_and_writes_audit_entry_per_affected_user(self, tmp_path, monkeypatch, caplog):
        """The repair logs how many cards it moved to the bench and writes one audit_logs entry per affected user (none for unaffected users)."""
        from migrate import run_migrations
        monkeypatch.setenv("ROSTER_LIMIT", "5")
        engine = _legacy_037_engine(tmp_path)
        _seed_repair_case(engine)
        caplog.set_level(logging.INFO, logger="migrate")
        run_migrations(engine)
        messages = [r.getMessage() for r in caplog.records if r.name == "migrate"]
        assert any("Migration 037: moved 3 card(s) of 1 user(s) to the bench" in m for m in messages)
        with engine.connect() as conn:
            audits = conn.execute(text(
                "SELECT actor_id, actor_username, action, detail FROM audit_logs "
                "WHERE action = 'roster_repair_benched'")).fetchall()
        assert len(audits) == 1
        actor_id, actor_username, _, detail = audits[0]
        assert actor_id is None and actor_username == "system"
        assert detail == "migration=037 user_id=1 card_ids=1,3,8"
        engine.dispose()

    def test_migration_037_creates_partial_unique_index(self, tmp_path):
        """After the repair, migration 037 creates ux_cards_owner_player_active ON cards(owner_id, player_id) WHERE is_active = 1; a second run is a no-op."""
        from migrate import run_migrations
        engine = _legacy_037_engine(tmp_path)
        _seed_repair_case(engine)
        assert "ux_cards_owner_player_active" not in _index_names(engine)
        run_migrations(engine)
        assert "ux_cards_owner_player_active" in _index_names(engine)
        with engine.connect() as conn:
            sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = "
                                    "'ux_cards_owner_player_active'")).scalar()
            assert conn.execute(text("SELECT 1 FROM schema_migrations WHERE id = "
                                     "'037_cards_active_player_unique'")).first() is not None
        assert "UNIQUE" in sql.upper() and "WHERE is_active = 1" in sql
        before = _card_rows(engine)
        run_migrations(engine)
        assert _card_rows(engine) == before
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM audit_logs WHERE action = "
                                     "'roster_repair_benched'")).scalar() == 1
        engine.dispose()

    def test_migration_037_does_not_change_locked_week_snapshots(self, tmp_path):
        """weekly_roster_entries rows of locked weeks are byte-for-byte unchanged by the 037 repair."""
        from migrate import run_migrations
        engine = _legacy_037_engine(tmp_path)
        _seed_repair_case(engine)
        rows = [("INSERT INTO weeks (id, label, start_time, end_time, is_locked) "
                 "VALUES (1, 'Week 1', 1700000000, 1700600000, 1)", {})]
        for i, cid in enumerate((1, 2, 3, 4, 5, 6, 7, 8)):
            rows.append(("INSERT INTO weekly_roster_entries (week_id, user_id, card_id, is_bench, "
                         "bench_order, subbed_in, subbed_out) VALUES (1, 1, :c, 0, :o, 0, 0)",
                         {"c": cid, "o": i}))
        _seed_raw(engine, rows)
        query = text("SELECT * FROM weekly_roster_entries ORDER BY id")
        with engine.connect() as conn:
            before = [tuple(r) for r in conn.execute(query)]
        run_migrations(engine)
        with engine.connect() as conn:
            after = [tuple(r) for r in conn.execute(query)]
        assert after == before and len(after) == 8
        engine.dispose()

    def test_models_declare_partial_unique_index_for_create_all(self, db):
        """Base.metadata.create_all creates ux_cards_owner_player_active (declared in models.py with sqlite_where), so new databases get it."""
        rows = db.execute(text("PRAGMA index_list(cards)")).fetchall()
        by_name = {r[1]: r for r in rows}
        assert "ux_cards_owner_player_active" in by_name
        assert by_name["ux_cards_owner_player_active"][2] == 1  # unique
        assert by_name["ux_cards_owner_player_active"][4] == 1  # partial
        cols = [r[2] for r in db.execute(text("PRAGMA index_info(ux_cards_owner_player_active)"))]
        assert cols == ["owner_id", "player_id"]

    def test_index_refuses_second_active_card_for_same_owner_and_player(self, db):
        """Inserting or updating a second active card for the same owner and player raises IntegrityError; a second benched card is allowed."""
        user = _make_user(db)
        other = _make_user(db, username="other", email="o@o.com")
        player = _make_player(db)
        _make_card(db, user.id, player.id, is_active=True)
        bench = _make_card(db, user.id, player.id, is_active=False)
        _make_card(db, user.id, player.id, is_active=False, card_type="rare")
        _make_card(db, other.id, player.id, is_active=True)  # another owner is fine
        db.commit()

        with pytest.raises(IntegrityError):
            _make_card(db, user.id, player.id, is_active=True, card_type="epic")
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE cards SET is_active = 1 WHERE id = :id"), {"id": bench.id})
        db.rollback()

    def test_activate_card_integrity_error_returns_409_not_500(self, db, monkeypatch):
        """If the write in activate_card hits the unique index, the route answers 409 'A card for this player is already active', never a 500."""
        import routers.cards as cards

        def boom(*_a, **_k):
            raise IntegrityError("UPDATE cards", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(cards, "_activate_card_atomic", boom)
        user = _make_user(db)
        card = _make_card(db, user.id, _make_player(db).id)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            cards.activate_card(card.id, db, {"user_id": user.id})
        assert exc.value.status_code == 409
        assert exc.value.detail == "A card for this player is already active"
        assert db.get(Card, card.id).is_active is False

    def test_swap_roster_integrity_error_returns_409_not_500(self, db, monkeypatch):
        """If the write in swap_roster hits the unique index, the route answers 409 'A card for this player is already active', never a 500."""
        import routers.cards as cards

        def boom(*_a, **_k):
            raise IntegrityError("UPDATE cards", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(cards, "_swap_roster_atomic", boom)
        user = _make_user(db)
        active = _make_card(db, user.id, _make_player(db, 1, "A").id, is_active=True, slot_index=0)
        bench = _make_card(db, user.id, _make_player(db, 2, "B").id)
        db.commit()
        body = cards.SwapRequest(bench_card_id=bench.id, active_card_id=active.id, slot_index=0)
        with pytest.raises(HTTPException) as exc:
            cards.swap_roster(body, {"user_id": user.id}, db)
        assert exc.value.status_code == 409
        assert exc.value.detail == "A card for this player is already active"
        assert db.get(Card, active.id).is_active is True
        assert db.get(Card, bench.id).is_active is False

    def test_swap_same_player_cards_works_with_index(self, db):
        """Swapping an active card for a benched card of the same player succeeds: the outgoing card is benched before the incoming one is activated."""
        from routers.cards import SwapRequest, swap_roster
        user = _make_user(db)
        player = _make_player(db)
        active = _make_card(db, user.id, player.id, is_active=True, slot_index=2)
        bench = _make_card(db, user.id, player.id, card_type="legendary")
        db.commit()
        swap_roster(SwapRequest(bench_card_id=bench.id, active_card_id=active.id, slot_index=2),
                    {"user_id": user.id}, db)
        db.expire_all()
        assert db.get(Card, bench.id).is_active is True and db.get(Card, bench.id).slot_index == 2
        assert db.get(Card, active.id).is_active is False


# ---------------------------------------------------------------------------
# Story 3: Token Balances Change Atomically
# ---------------------------------------------------------------------------

class TestTokenBalancesChangeAtomically:

    def test_credit_tokens_adds_amount_relatively(self, db):
        """credit_tokens(db, user_id, amount) runs UPDATE users SET tokens = COALESCE(tokens, 0) + :amount WHERE id = :uid; works when tokens is NULL."""
        from database import credit_tokens
        user = _make_user(db, tokens=4)
        empty = _make_user(db, tokens=None, username="empty", email="e@e.com")
        db.commit()
        credit_tokens(db, user.id, 3)
        credit_tokens(db, empty.id, 2)
        db.commit()
        db.refresh(user)
        db.refresh(empty)
        assert user.tokens == 7 and empty.tokens == 2
        src = inspect.getsource(credit_tokens)
        assert "UPDATE users SET tokens = COALESCE(tokens, 0) + :amt WHERE id = :uid" in src

    def test_credit_tokens_unknown_user_changes_nothing(self, db):
        """credit_tokens for a user id that does not exist changes no rows and does not raise."""
        from database import credit_tokens
        user = _make_user(db, tokens=4)
        db.commit()
        credit_tokens(db, 99999, 5)
        db.commit()
        assert db.execute(text("SELECT SUM(tokens) FROM users")).scalar() == 4
        assert db.query(User).count() == 1

    def test_claim_events_credits_via_credit_tokens(self, db, monkeypatch):
        """claim_events (routers/auth.py) credits through credit_tokens and returns the refreshed balance."""
        import routers.auth as auth_router
        from models import TokenGrantClaim, TokenGrantEvent
        calls = []
        real = auth_router.credit_tokens
        monkeypatch.setattr(auth_router, "credit_tokens",
                            lambda d, uid, amt: (calls.append((uid, amt)), real(d, uid, amt)))
        user = _make_user(db, tokens=2)
        now = int(time.time())
        db.add(TokenGrantEvent(amount=4, start_time=now - 60, end_time=now + 60))
        db.commit()
        claim = inspect.unwrap(auth_router.claim_events)
        out = claim(None, db, {"user_id": user.id})
        assert out == {"granted": 4, "tokens": 6}
        assert calls == [(user.id, 4)]
        assert db.query(TokenGrantClaim).count() == 1
        assert claim(None, db, {"user_id": user.id}) == {"granted": 0, "tokens": 6}

    def test_grant_tokens_and_redeem_credit_via_credit_tokens(self, db, monkeypatch):
        """Admin grant_tokens and promo redeem_code (routers/admin_users.py) credit through credit_tokens and return the refreshed balance."""
        import routers.admin_users as admin_users
        from models import PromoCode
        calls = []
        real = admin_users.credit_tokens
        monkeypatch.setattr(admin_users, "credit_tokens",
                            lambda d, uid, amt: (calls.append((uid, amt)), real(d, uid, amt)))
        admin = _make_user(db, tokens=0, username="admin", email="a@a.com")
        user = _make_user(db, tokens=1)
        db.add(PromoCode(code="FREE5", token_amount=5, created_by_id=admin.id))
        db.commit()
        out = admin_users.grant_tokens(admin_users.GrantTokensBody(target_user_id=user.id, amount=3),
                                       db, {"user_id": admin.id, "username": "admin"})
        assert out["tokens"] == 4
        out = admin_users.redeem_code(admin_users.RedeemCodeBody(code="free5"), db, {"user_id": user.id})
        assert out == {"tokens": 9, "granted": 5}
        assert calls == [(user.id, 3), (user.id, 5)]

    def test_mvp_drop_weekly_grant_and_removal_refund_use_relative_updates(self, db, monkeypatch):
        """MVP token drops (twitch.py), weekly lock grants (weeks.py, one UPDATE ... WHERE id IN (...)) and player-removal refunds (routers/admin_players.py) use credit_tokens or a relative bulk update."""
        import twitch
        import weeks
        import routers.admin_players as admin_players
        from models import Week

        # MVP drop: winners credited through credit_tokens.
        drop_calls = []
        real_twitch = twitch.credit_tokens
        monkeypatch.setattr(twitch, "credit_tokens",
                            lambda d, uid, amt: (drop_calls.append((uid, amt)), real_twitch(d, uid, amt)))
        winner = _soft_user(db, "Uwinner", tokens=2)
        db.commit()
        monkeypatch.setattr(twitch, "_active_pool", lambda _db, _ch: ["Uwinner"])
        monkeypatch.setattr(twitch, "_excluded_new_count", lambda _db, _ch: 0)
        monkeypatch.setattr(twitch, "_is_pool_spike", lambda _db, _ch, _n: False)
        names, pool, already = twitch._execute_token_drop(db, "chan", 777, {})
        db.commit()
        assert (pool, already, len(names)) == (1, False, 1)
        assert drop_calls == [(winner.id, 1)]
        db.refresh(winner)
        assert winner.tokens == 3

        # Weekly grant: one relative bulk UPDATE, no ORM balance writes.
        a = _make_user(db, tokens=None, username="wa", email="wa@x.com")
        b = _make_user(db, tokens=5, username="wb", email="wb@x.com")
        db.add(Week(label="W1", start_time=int(time.time()) - 60, end_time=int(time.time()) + 3600,
                    is_locked=False))
        db.commit()
        statements = []

        def _capture(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("UPDATE USERS"):
                statements.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            weeks.auto_lock_weeks(db)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        db.expire_all()
        assert db.get(User, a.id).tokens == 1 and db.get(User, b.id).tokens == 6
        assert len(statements) == 1
        assert re.search(r"tokens\s*=\s*\(?coalesce\(users\.tokens", statements[0], re.I)
        assert " IN (" in statements[0].upper()

        # Player-removal refund through credit_tokens.
        refund_calls = []
        real_admin = admin_players.credit_tokens
        monkeypatch.setattr(admin_players, "credit_tokens",
                            lambda d, uid, amt: (refund_calls.append((uid, amt)), real_admin(d, uid, amt)))
        player = _make_player(db, 4242, "Gone")
        _make_card(db, b.id, player.id, is_active=True)
        _make_card(db, b.id, player.id, card_type="rare")
        db.commit()
        admin_players.remove_players(admin_players.RemovePlayersBody(player_ids=[4242]), db,
                                     {"user_id": a.id, "username": "wa"})
        db.expire_all()
        assert refund_calls == [(b.id, 2)]
        assert db.get(User, b.id).tokens == 8

    def test_merge_soft_into_moves_balance_with_relative_updates(self, db):
        """merge_soft_into adds the soft account's tokens to the full account and zeroes the soft account with relative updates in one transaction, without reading then writing both rows."""
        import soft_accounts
        from models import TwitchMergeLog
        full = _make_user(db, tokens=5)
        soft = _soft_user(db, "Umerge", tokens=7)
        soft_id = soft.id
        db.commit()
        # A spend on the full account by another request after the ORM objects were
        # loaded: a read-then-write merge would overwrite it.
        db.execute(text("UPDATE users SET tokens = tokens - 2 WHERE id = :id"), {"id": full.id})
        result = soft_accounts.merge_soft_into(db, soft, full)
        db.commit()
        assert result["tokens"] == 7
        assert db.get(User, full.id).tokens == 5 - 2 + 7
        assert db.get(User, soft_id) is None
        assert db.query(TwitchMergeLog).one().tokens_moved == 7
        src = inspect.getsource(soft_accounts.merge_soft_into)
        assert ".tokens =" not in src and "tokens = COALESCE(tokens, 0) +" in src

    def test_reverse_merge_moves_balance_back_with_relative_updates(self, db):
        """reverse_merge returns the moved tokens with relative updates (never below 0, shortfall reported as before)."""
        import soft_accounts
        full = _make_user(db, tokens=5)
        soft = _soft_user(db, "Urev", tokens=7)
        db.commit()
        soft_accounts.merge_soft_into(db, soft, full)
        db.commit()
        log_id = soft_accounts.merge_soft_into.__globals__["TwitchMergeLog"]
        log = db.query(log_id).one()
        db.execute(text("UPDATE users SET tokens = 3 WHERE id = :id"), {"id": full.id})  # spent 9
        out = soft_accounts.reverse_merge(db, log)
        db.commit()
        assert out["tokens_returned"] == 7 and out["token_shortfall"] == 4
        assert db.get(User, full.id).tokens == 0
        assert db.get(User, out["soft_user_id"]).tokens == 7

        # Enough balance: all of it is taken back, no shortfall.
        full2 = _make_user(db, tokens=1, username="f2", email="f2@x.com")
        soft2 = _soft_user(db, "Urev2", tokens=4)
        db.commit()
        soft_accounts.merge_soft_into(db, soft2, full2)
        db.commit()
        log2 = db.query(log_id).filter(log_id.full_user_id == full2.id).one()
        out2 = soft_accounts.reverse_merge(db, log2)
        db.commit()
        assert out2["token_shortfall"] == 0 and db.get(User, full2.id).tokens == 1
        assert ".tokens =" not in inspect.getsource(soft_accounts.reverse_merge)

    def test_concurrent_credit_and_spend_balance_is_exact(self, file_db_sessionmaker):
        """A concurrent credit (credit_tokens / event claim) and spend (spend_tokens / draw) on one account end with balance = start + credit - spend."""
        from database import credit_tokens, spend_tokens
        from routers.cards import draw_card
        Factory = file_db_sessionmaker
        setup = Factory()
        user = _make_user(setup, tokens=10)
        _seed_players(setup, 50)
        setup.commit()
        uid = user.id
        setup.close()

        def _op(kind):
            s = Factory()
            try:
                if kind == "credit":
                    credit_tokens(s, uid, 3)
                elif kind == "spend":
                    assert spend_tokens(s, uid, 2)
                else:
                    draw_card(s, {"user_id": uid})
                    return
                s.commit()
            finally:
                s.close()

        args = [("credit",)] * 8 + [("spend",)] * 4 + [("draw",)] * 4
        results = _run_concurrently(_op, args)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            assert verify.get(User, uid).tokens == 10 + 8 * 3 - 4 * 2 - 4 * 1
        finally:
            verify.close()

    def test_concurrent_merge_and_spend_loses_no_tokens(self, file_db_sessionmaker):
        """A soft-account merge running concurrently with a spend on the full account ends with full = start_full + soft - spend and soft = 0."""
        import soft_accounts
        from database import spend_tokens
        Factory = file_db_sessionmaker
        setup = Factory()
        full = _make_user(setup, tokens=10)
        soft = _soft_user(setup, "Uconc", tokens=7)
        setup.commit()
        full_id, soft_id = full.id, soft.id
        setup.close()

        def _op(kind):
            s = Factory()
            try:
                if kind == "merge":
                    soft_accounts.merge_soft_into(s, s.get(User, soft_id), s.get(User, full_id))
                else:
                    assert spend_tokens(s, full_id, 1)
                s.commit()
            finally:
                s.close()

        results = _run_concurrently(_op, [("merge",)] + [("spend",)] * 5)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            assert verify.get(User, full_id).tokens == 10 + 7 - 5
            assert verify.get(User, soft_id) is None
        finally:
            verify.close()

    def test_no_orm_tokens_assignment_outside_database_py(self):
        """Static guard: no file under backend/ (outside database.py and tests/) assigns `.tokens =` or `.tokens +=`."""
        pattern = re.compile(r"\.tokens\s*(?:[+\-]?=)(?!=)")
        offenders = []
        for root, dirs, files in os.walk(BACKEND_DIR):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".venv", "venv")]
            for name in files:
                path = os.path.join(root, name)
                if not name.endswith(".py") or path == os.path.join(BACKEND_DIR, "database.py"):
                    continue
                with open(path, encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        if pattern.search(line):
                            offenders.append(f"{os.path.relpath(path, REPO_ROOT)}:{lineno}: {line.strip()}")
        assert offenders == []
        assert pattern.search("user.tokens = (user.tokens or 0) + 1")
        assert pattern.search("user.tokens += 1")
        assert not pattern.search("if user.tokens == 0:")


# ---------------------------------------------------------------------------
# Story 4: Promo Codes Respect Their Use Cap Under Load
# ---------------------------------------------------------------------------

def _promo(db, code="CAP", amount=5, max_redemptions=None):
    from models import PromoCode
    creator = _make_user(db, tokens=0, username=f"creator_{code}", email=f"{code}@c.com")
    promo = PromoCode(code=code, token_amount=amount, created_by_id=creator.id,
                      max_redemptions=max_redemptions)
    db.add(promo)
    db.flush()
    return promo


class TestPromoCodesRespectUseCapUnderLoad:

    def test_redeem_code_inserts_with_conditional_insert_and_credits(self, db):
        """redeem_code inserts the redemption with INSERT ... SELECT ... WHERE (count below max_redemptions) and credits tokens only when rowcount is 1."""
        import routers.admin_users as admin_users
        from models import CodeRedemption
        sql = str(admin_users._REDEEM_INSERT_SQL)
        assert re.search(r"INSERT INTO code_redemptions .*SELECT .*WHERE :max IS NULL\s+OR \(SELECT "
                         r"COUNT\(\*\) FROM code_redemptions WHERE code_id = :code_id\) < :max", sql, re.S)
        assert "_REDEEM_INSERT_SQL" in inspect.getsource(admin_users.redeem_code)
        promo = _promo(db, max_redemptions=2)
        user = _make_user(db, tokens=1)
        db.commit()
        out = admin_users.redeem_code(admin_users.RedeemCodeBody(code="cap"), db, {"user_id": user.id})
        assert out == {"tokens": 6, "granted": 5}
        assert db.query(CodeRedemption).filter_by(code_id=promo.id, user_id=user.id).count() == 1

    def test_redeem_code_unlimited_when_max_redemptions_null(self, db):
        """A code with max_redemptions NULL accepts redemptions from any number of users."""
        from routers.admin_users import RedeemCodeBody, redeem_code
        from models import CodeRedemption
        _promo(db, code="OPEN", amount=2)
        users = [_make_user(db, tokens=0, username=f"u{i}", email=f"u{i}@x.com") for i in range(12)]
        db.commit()
        for u in users:
            assert redeem_code(RedeemCodeBody(code="OPEN"), db, {"user_id": u.id})["tokens"] == 2
        assert db.query(CodeRedemption).count() == 12

    def test_redeem_code_at_cap_returns_404_and_credits_nothing(self, db):
        """Redeeming a code that has reached max_redemptions answers 404 INVALID_CODE_DETAIL and leaves the balance unchanged."""
        from routers.admin_users import INVALID_CODE_DETAIL, RedeemCodeBody, redeem_code
        from models import CodeRedemption
        _promo(db, code="ONE", max_redemptions=1)
        first = _make_user(db, tokens=0, username="first", email="f@x.com")
        late = _make_user(db, tokens=3, username="late", email="l@x.com")
        db.commit()
        redeem_code(RedeemCodeBody(code="ONE"), db, {"user_id": first.id})
        with pytest.raises(HTTPException) as exc:
            redeem_code(RedeemCodeBody(code="ONE"), db, {"user_id": late.id})
        assert exc.value.status_code == 404 and exc.value.detail == INVALID_CODE_DETAIL
        db.expire_all()
        assert db.get(User, late.id).tokens == 3
        assert db.query(CodeRedemption).count() == 1

    def test_redeem_code_twice_by_same_user_returns_409(self, db):
        """One user redeeming the same code twice still gets 409 'Code already redeemed' and is credited once."""
        from routers.admin_users import RedeemCodeBody, redeem_code
        _promo(db, code="TWICE", amount=4, max_redemptions=10)
        user = _make_user(db, tokens=0)
        db.commit()
        redeem_code(RedeemCodeBody(code="TWICE"), db, {"user_id": user.id})
        with pytest.raises(HTTPException) as exc:
            redeem_code(RedeemCodeBody(code="TWICE"), db, {"user_id": user.id})
        assert exc.value.status_code == 409 and exc.value.detail == "Code already redeemed"
        db.expire_all()
        assert db.get(User, user.id).tokens == 4

    def test_concurrent_same_user_redeems_credit_once(self, file_db_sessionmaker):
        """Concurrent redeems of one code by one user: exactly one credit, the rest 409 (the unique index answers)."""
        from routers.admin_users import RedeemCodeBody, redeem_code
        Factory = file_db_sessionmaker
        setup = Factory()
        _promo(setup, code="SAME", amount=3)
        user = _make_user(setup, tokens=0)
        setup.commit()
        uid = user.id
        setup.close()

        def _redeem():
            s = Factory()
            try:
                return redeem_code(RedeemCodeBody(code="SAME"), s, {"user_id": uid})
            except HTTPException as exc:
                return exc.status_code
            finally:
                s.close()

        results = [r for r, _ in _run_concurrently(_redeem, [()] * 6)]
        assert sum(1 for r in results if isinstance(r, dict)) == 1
        assert sorted(r for r in results if not isinstance(r, dict)) == [409] * 5
        verify = Factory()
        try:
            assert verify.get(User, uid).tokens == 3
        finally:
            verify.close()

    def test_concurrent_redemptions_stop_at_cap(self, file_db_sessionmaker):
        """Twenty concurrent redemptions of a code capped at 5, by different users, give exactly 5 redemptions and 5 credits; the rest get 404 INVALID_CODE_DETAIL."""
        from routers.admin_users import INVALID_CODE_DETAIL, RedeemCodeBody, redeem_code
        from models import CodeRedemption
        Factory = file_db_sessionmaker
        setup = Factory()
        _promo(setup, code="RUSH", amount=2, max_redemptions=5)
        uids = [_make_user(setup, tokens=0, username=f"r{i}", email=f"r{i}@x.com").id for i in range(20)]
        setup.commit()
        setup.close()

        def _redeem(uid):
            s = Factory()
            try:
                return redeem_code(RedeemCodeBody(code="RUSH"), s, {"user_id": uid})
            except HTTPException as exc:
                return (exc.status_code, exc.detail)
            finally:
                s.close()

        results = _run_concurrently(_redeem, [(u,) for u in uids])
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        ok = [r for r, _ in results if isinstance(r, dict)]
        refused = [r for r, _ in results if not isinstance(r, dict)]
        assert len(ok) == 5
        assert refused == [(404, INVALID_CODE_DETAIL)] * 15
        verify = Factory()
        try:
            assert verify.query(CodeRedemption).count() == 5
            balances = [verify.get(User, u).tokens for u in uids]
            assert sorted(balances) == [0] * 15 + [2] * 5
        finally:
            verify.close()


# ---------------------------------------------------------------------------
# Story 5: Website Actions Wait for Their Answer (frontend static checks)
# ---------------------------------------------------------------------------

class TestWebsiteActionsWaitForTheirAnswer:

    def test_with_busy_helper_defined_in_app_globals(self):
        """frontend/app-globals.js defines withBusy(btn, fn): returns early when btn is disabled, disables it, awaits fn, re-enables in finally."""
        body = _js_body(_read("frontend/app-globals.js"), "withBusy")
        assert re.search(r"if \(btn && btn\.disabled\) return", body)
        assert "btn.disabled = true" in body
        assert re.search(r"try\s*\{\s*return await fn\(\);\s*\}\s*finally\s*\{\s*if \(btn\) btn\.disabled = false;",
                         body)

    def test_card_actions_use_in_flight_guard(self):
        """Draw, booster draw and reroll confirm handlers (frontend/app-cards.js) run their request through withBusy."""
        js = _read("frontend/app-cards.js")
        html = _read("frontend/index.html")
        assert 'withBusy(btn, async () =>' in _js_body(js, "drawCard")
        assert 'withBusy(btn, () => _drawBoosterForTeam(' in _js_body(js, "drawBooster")
        assert 'withBusy(confirmBtn, async () =>' in _js_body(js, "confirmReroll")
        assert 'id="rerollConfirmBtn" onclick="confirmReroll()"' in html
        assert 'id="drawBtn"' in html and 'id="boosterDrawBtn"' in html
        # The reveal's repeat team draw has no button: a flag keeps it to one request.
        booster = _js_body(js, "_drawBoosterForTeam")
        assert booster.lstrip().startswith("if (_boosterDrawInFlight) return;")
        assert "_boosterDrawInFlight = false;" in booster.split("finally")[-1]

    def test_roster_actions_use_in_flight_guard(self):
        """Issue #186 replaced the per-action requests: a roster change (drop or
        Enter/Space toggle) edits the local layout, and the only roster request in
        frontend/app-roster.js is the autosave's PUT /roster, which runs one at a
        time (single flight)."""
        js = _read("frontend/app-roster.js")
        for route in ("/activate`", "/deactivate`", "/roster/swap`", "/roster/reorder`"):
            assert route not in js
        assert js.count("method: \"PUT\"") == 1
        run = _js_body(js, "_runRosterSave")
        assert run.index('if (_saveState === "saving" || !_saveDirty) return _saveFlight;') < run.index("fetch(")

    def test_roster_drag_and_drop_ignores_drops_while_busy(self):
        """Issue #186: drops are no longer ignored while a request runs (no
        _rosterBusy); a double request still can't happen, because saves never
        overlap: a move during a save marks the layout dirty and one follow-up save
        sends the newest layout after the running one resolves."""
        js = _read("frontend/app-roster.js")
        assert "_rosterBusy" not in js
        run = _js_body(js, "_runRosterSave")
        assert '_saveState = "saving";' in run
        assert "_saveFlight = null;" in run
        assert 'if (_saveState !== "error" && _saveDirty && !_saveTimer) _runRosterSave();' in run
        schedule = _js_body(js, "_scheduleRosterSave")
        assert "_saveDirty = true;" in schedule and "clearTimeout(_saveTimer);" in schedule

    def test_redeem_and_weekly_reveal_use_in_flight_guard(self):
        """The promo redeem button and the Weekly Report reveal button (frontend/app-weekly-summary.js) run their request through withBusy."""
        html = _read("frontend/index.html")
        assert 'id="redeemBtn" class="secondary" onclick="redeemCode()"' in html
        assert 'id="weeklySummaryRevealBtn" onclick="revealAllWeeklySummaries()"' in html
        redeem = _js_body(_read("frontend/app-roster.js"), "redeemCode")
        assert 'withBusy(document.getElementById("redeemBtn"), async () =>' in redeem
        assert redeem.index("withBusy(") < redeem.index("fetch(")
        reveal = _js_body(_read("frontend/app-weekly-summary.js"), "revealAllWeeklySummaries")
        assert "withBusy(document.getElementById('weeklySummaryRevealBtn'), async () =>" in reveal
        assert reveal.index("withBusy(") < reveal.index("fetch(")

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_failed_request_reenables_button_and_shows_error(self):
        """Node harness: withBusy re-enables the button when fn rejects and a second call while the first is pending does not invoke fn again."""
        src = _read("frontend/app-globals.js")
        m = re.search(r"async function withBusy\(btn, fn\) \{.*?\n\}", src, re.S)
        assert m
        harness = m.group(0) + r"""
(async () => {
  const out = {};
  const btn = { disabled: false };
  let calls = 0;
  let release;
  const pending = new Promise(r => { release = r; });
  const first = withBusy(btn, () => { calls += 1; return pending; });
  out.disabledDuring = btn.disabled;
  const second = await withBusy(btn, () => { calls += 1; return "again"; });
  out.secondResult = second === undefined ? null : second;
  release("done");
  out.firstResult = await first;
  out.callsAfterDouble = calls;
  out.enabledAfter = btn.disabled === false;

  let shown = null;
  try {
    await withBusy(btn, async () => { throw new Error("Network down"); });
  } catch (e) { shown = e.message; }
  out.errorShown = shown;
  out.enabledAfterError = btn.disabled === false;
  out.noButton = await withBusy(null, async () => "ran");
  console.log(JSON.stringify(out));
})();
"""
        result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout.strip().splitlines()[-1])
        assert out == {"disabledDuring": True, "secondResult": None, "firstResult": "done",
                       "callsAfterDouble": 1, "enabledAfter": True, "errorShown": "Network down",
                       "enabledAfterError": True, "noButton": "ran"}
        # The handlers catch the error and show it with setStatus / textContent.
        cards = _read("frontend/app-cards.js")
        assert 'setStatus("deckStatus", e.message, false)' in _js_body(cards, "drawCard")
        assert 'setStatus("redeemStatus", e.message, false)' in _js_body(_read("frontend/app-roster.js"), "redeemCode")


# ---------------------------------------------------------------------------
# Security review follow-ups (#185): races and session handling
# ---------------------------------------------------------------------------

class TestSecurityReviewFollowUps:

    def test_seed_weights_closes_session_when_commit_fails(self, monkeypatch):
        """seed_weights() closes its SessionLocal() session in finally, also when commit() raises."""
        import seed

        class _FailingSession:
            closed = False

            def get(self, *_a):
                return None

            def add(self, *_a):
                pass

            def commit(self):
                raise RuntimeError("database is locked")

            def close(self):
                _FailingSession.closed = True

        monkeypatch.setattr(seed, "SessionLocal", _FailingSession)
        monkeypatch.delenv("WEIGHTS_JSON", raising=False)
        with pytest.raises(RuntimeError):
            seed.seed_weights()
        assert _FailingSession.closed is True

    def test_claim_events_skips_event_already_claimed_mid_request(self, db):
        """With two active events, an event another request claimed first is skipped
        (no IntegrityError, no 500) and the other event is still credited once."""
        import routers.auth as auth_router
        from models import TokenGrantClaim, TokenGrantEvent
        user = _make_user(db, tokens=0)
        now = int(time.time())
        e1 = TokenGrantEvent(amount=2, start_time=now - 60, end_time=now + 60)
        e2 = TokenGrantEvent(amount=5, start_time=now - 60, end_time=now + 60)
        db.add_all([e1, e2])
        db.commit()
        # The "other request" claimed e1 (without crediting it here).
        db.add(TokenGrantClaim(event_id=e1.id, user_id=user.id, claimed_at=now))
        db.commit()
        claim = inspect.unwrap(auth_router.claim_events)
        assert claim(None, db, {"user_id": user.id}) == {"granted": 5, "tokens": 5}
        assert db.query(TokenGrantClaim).count() == 2
        assert claim(None, db, {"user_id": user.id}) == {"granted": 0, "tokens": 5}

    def test_concurrent_claims_credit_each_event_once(self, file_db_sessionmaker):
        """Eight simultaneous claim requests of one user with three active events: none
        fails, every event is credited exactly once."""
        import routers.auth as auth_router
        from models import TokenGrantClaim, TokenGrantEvent
        Factory = file_db_sessionmaker
        setup = Factory()
        user = _make_user(setup, tokens=1)
        now = int(time.time())
        setup.add_all([TokenGrantEvent(amount=a, start_time=now - 60, end_time=now + 60)
                       for a in (2, 3, 4)])
        setup.commit()
        uid = user.id
        setup.close()
        claim = inspect.unwrap(auth_router.claim_events)

        def _claim():
            s = Factory()
            try:
                return claim(None, s, {"user_id": uid})["granted"]
            finally:
                s.close()

        results = _run_concurrently(_claim, [()] * 8)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        assert sum(r for r, _ in results) == 9
        verify = Factory()
        try:
            assert verify.get(User, uid).tokens == 1 + 9
            assert verify.query(TokenGrantClaim).count() == 3
        finally:
            verify.close()

    def test_merge_aborts_when_soft_account_already_gone(self, db):
        """merge_soft_into raises SoftAccountGone and moves nothing when the soft row was
        deleted by another request after it was loaded."""
        import soft_accounts
        from models import TwitchMergeLog
        full = _make_user(db, tokens=5)
        soft = _soft_user(db, "Ugone", tokens=7)
        db.commit()
        db.execute(text("DELETE FROM users WHERE id = :id"), {"id": soft.id})
        with pytest.raises(soft_accounts.SoftAccountGone):
            soft_accounts.merge_soft_into(db, soft, full)
        db.rollback()
        assert db.execute(text("SELECT tokens FROM users WHERE id = :id"), {"id": full.id}).scalar() == 5
        assert db.query(TwitchMergeLog).count() == 0
        # Issue #187 replaced the single soft-balance subquery UPDATE with a lock-taking
        # UPDATE, reads under that lock, and one relative UPDATE of the website balance.
        src = inspect.getsource(soft_accounts.merge_soft_into)
        assert "SET tokens = COALESCE(tokens, 0) + :delta" in src
        assert src.index("raise SoftAccountGone") < src.index(":delta")

    def test_merge_confirm_answers_404_when_soft_account_gone(self, db, monkeypatch):
        """POST /twitch/merge/confirm turns SoftAccountGone into 404, not a 500."""
        import soft_accounts
        import twitch_oauth
        full = _make_user(db, tokens=5)
        soft = _soft_user(db, "Ugone2", tokens=7)
        full.pending_merge_user_id = soft.id
        db.commit()
        monkeypatch.setattr(twitch_oauth, "_pending_soft_account", lambda _db, _u: soft)

        def _gone(*_a, **_k):
            raise soft_accounts.SoftAccountGone("gone")

        monkeypatch.setattr(soft_accounts, "merge_soft_into", _gone)
        with pytest.raises(HTTPException) as exc:
            twitch_oauth.merge_confirm(db, {"user_id": full.id})
        assert exc.value.status_code == 404
        assert exc.value.detail == "That Twitch collection is gone; refresh the page"

    def test_concurrent_merges_of_one_soft_account_move_tokens_once(self, file_db_sessionmaker):
        """Two simultaneous merges of one soft account into one website account: one
        succeeds, the other raises SoftAccountGone; the balance moves once."""
        import soft_accounts
        Factory = file_db_sessionmaker
        setup = Factory()
        full = _make_user(setup, tokens=10)
        soft = _soft_user(setup, "Utwice", tokens=7)
        setup.commit()
        full_id, soft_id = full.id, soft.id
        setup.close()

        def _merge():
            s = Factory()
            try:
                soft_row, full_row = s.get(User, soft_id), s.get(User, full_id)
                try:
                    soft_accounts.merge_soft_into(s, soft_row, full_row)
                    s.commit()
                    return "merged"
                except soft_accounts.SoftAccountGone:
                    s.rollback()
                    return "gone"
            finally:
                s.close()

        results = _run_concurrently(_merge, [()] * 2)
        assert sorted(r for r, _ in results) == ["gone", "merged"], results
        verify = Factory()
        try:
            assert verify.get(User, full_id).tokens == 17
            assert verify.get(User, soft_id) is None
        finally:
            verify.close()

    def test_concurrent_removes_of_one_player_refund_once(self, file_db_sessionmaker):
        """Simultaneous POST /admin/players/remove for the same player refund each owner once."""
        import routers.admin_players as admin_players
        Factory = file_db_sessionmaker
        setup = Factory()
        admin = _make_user(setup, tokens=0, username="admin", email="a@a.com")
        owner = _make_user(setup, tokens=1, username="owner", email="o@o.com")
        player = _make_player(setup, 777, "Leaving")
        _make_card(setup, owner.id, player.id, is_active=True)
        _make_card(setup, owner.id, player.id, card_type="rare")
        setup.commit()
        admin_ctx = {"user_id": admin.id, "username": "admin"}
        owner_id = owner.id
        setup.close()

        def _remove():
            s = Factory()
            try:
                return admin_players.remove_players(
                    admin_players.RemovePlayersBody(player_ids=[777]), s, admin_ctx)
            finally:
                s.close()

        results = _run_concurrently(_remove, [()] * 4)
        assert all(exc is None for _, exc in results), [exc for _, exc in results if exc]
        verify = Factory()
        try:
            assert verify.get(User, owner_id).tokens == 1 + 2
            assert verify.execute(text("SELECT COUNT(*) FROM audit_logs WHERE action = "
                                       "'admin_player_refund_issued'")).scalar() == 1
            assert verify.get(Player, 777).is_active is False
        finally:
            verify.close()

    def test_token_grant_event_routes_moved_and_mounted(self):
        """The token-grant-event admin routes live in routers/admin_token_events.py, are
        mounted by main.py, and admin_users.py is within the 350-line budget."""
        from routers import admin_token_events
        names = {r.name for r in admin_token_events.router.routes}
        assert {"list_token_grant_events", "create_token_grant_event",
                "delete_token_grant_event"} <= names
        main_src = _read("backend/main.py")
        assert "from routers import admin_token_events as admin_token_events_router" in main_src
        assert "app.include_router(admin_token_events_router.router)" in main_src
        users_src = _read("backend/routers/admin_users.py")
        assert "token-grant-events" not in users_src
        assert users_src.count("\n") <= 350
