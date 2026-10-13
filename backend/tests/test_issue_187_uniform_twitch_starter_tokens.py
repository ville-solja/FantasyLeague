"""Tests for plan-issue-187-uniform-twitch-starter-tokens.

Covers the four user stories in
markdown/plans/plan-issue-187-uniform-twitch-starter-tokens.md:

1. Connecting Twitch Gives the Twitch Starter Once (`twitch_oauth.connect_account`
   credits `TWITCH_CONNECT_BONUS_TOKENS` via `credit_tokens` on "connected" and
   returns `connected_bonus`; grant recorded in `twitch_starter_grants`).
2. The Panel Path Isn't Doubled (`soft_accounts.py` records a `join` grant; a
   "merge_ready" connect grants nothing).
3. No Farming by Reconnecting (grant row survives disconnect / reverse_merge;
   the unique `twitch_id_hash` decides concurrent callbacks).
4. Existing Players Are Treated the Same (data migration
   `038_twitch_starter_grants_backfill` in backend/migrate.py, idempotent).

--- Notes for the developer ---
* `record_starter_grant(db, twitch_id, user_id, source) -> bool` should use
  `INSERT ... ON CONFLICT (twitch_id_hash) DO NOTHING` and act only when
  `rowcount == 1` (see lessons-learned 2026-10-12).
* Concurrency test: reuse the `file_db_sessionmaker` / `_run_concurrently`
  pattern (WAL file-based SQLite + `threading.Barrier`) from
  tests/test_issue_185_atomic_roster_and_token_operations.py. Run it against the
  old code first to confirm it fails (lessons-learned 2026-10-11).
* Migration tests: follow tests/test_migrate.py -- build an engine, seed rows,
  call `migrate.run_migrations(engine)` twice.
* Suite size: bump `test_issue_85_split_admin_router.py`'s baseline from the
  real "N passed" count of the failing run.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models as _models  # noqa: F401 — registers all tables in Base.metadata
from database import Base


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


TWITCH_ID = "123456789"


@pytest.fixture(autouse=True)
def _default_bonus_env(monkeypatch):
    monkeypatch.delenv("TWITCH_CONNECT_BONUS_TOKENS", raising=False)
    monkeypatch.delenv("INITIAL_TOKENS", raising=False)


def _web_user(db, username="web", tokens=5):
    from models import User
    u = User(username=username, email=f"{username}@example.com", password_hash="x",
             tokens=tokens, account_type="full")
    db.add(u)
    db.flush()
    return u


def _soft_user(db, opaque="Uopaque1", real_id=TWITCH_ID, tokens=5):
    from models import User
    u = User(username=None, email=None, password_hash=None, tokens=tokens,
             twitch_user_id=opaque, twitch_account_id=real_id, account_type="twitch")
    db.add(u)
    db.flush()
    return u


def _h(twitch_id):
    import soft_accounts
    return soft_accounts.starter_grant_hash(twitch_id)


def _grants(db, twitch_id=TWITCH_ID):
    from models import TwitchStarterGrant
    return db.query(TwitchStarterGrant).filter(
        TwitchStarterGrant.twitch_id_hash == _h(twitch_id)).all()


def _audits(db, action="twitch_starter_bonus"):
    from models import AuditLog
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def _tokens(db, user):
    db.refresh(user)
    return user.tokens


def _disconnect(db, user):
    import twitch_oauth
    return twitch_oauth.disconnect(db, {"user_id": user.id})


def _file_engine(tmp_path, name="race.db"):
    from sqlalchemy import event
    engine = create_engine(f"sqlite:///{tmp_path / name}",
                           connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def _migrated_engine(tmp_path, seed):
    """A file database with the current schema, seeded by seed(session), then migrated."""
    import migrate
    engine = _file_engine(tmp_path, "migrate.db")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed(s)
        s.commit()
    migrate.run_migrations(engine)
    return engine


# ---------------------------------------------------------------------------
# Story 1: Connecting Twitch Gives the Twitch Starter Once
# ---------------------------------------------------------------------------

class TestConnectingTwitchGivesStarterOnce:

    def test_connect_account_without_soft_account_credits_bonus(self, db):
        """When Connect Twitch stores a Twitch id and no soft account holds it ("connected"), the website account is credited TWITCH_CONNECT_BONUS_TOKENS (default INITIAL_TOKENS, 5) with credit_tokens."""
        import twitch_oauth
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, TWITCH_ID) == "connected_bonus"
        assert _tokens(db, user) == 10
        assert user.twitch_account_id == TWITCH_ID

    def test_connect_account_bonus_uses_credit_tokens(self, db, monkeypatch):
        """The connect bonus is credited through database.credit_tokens (#185), not an ORM balance assignment."""
        import twitch_oauth
        calls = []
        real = twitch_oauth.credit_tokens

        def _spy(d, uid, n):
            calls.append((uid, n))
            return real(d, uid, n)

        monkeypatch.setattr(twitch_oauth, "credit_tokens", _spy)
        user = _web_user(db)
        twitch_oauth.connect_account(db, user, TWITCH_ID)
        assert calls == [(user.id, 5)]
        assert _tokens(db, user) == 10

    def test_connect_account_records_connect_grant_row(self, db):
        """The grant is recorded per Twitch account in twitch_starter_grants (twitch_id_hash unique, user_id, source='connect', amount, granted_at)."""
        import twitch_oauth
        user = _web_user(db)
        twitch_oauth.connect_account(db, user, TWITCH_ID)
        rows = _grants(db)
        assert len(rows) == 1
        assert rows[0].user_id == user.id
        assert rows[0].source == "connect" and rows[0].amount == 5
        assert isinstance(rows[0].granted_at, int) and rows[0].granted_at > 0

    def test_twitch_starter_grant_twitch_id_hash_is_unique(self, db):
        """twitch_starter_grants.twitch_id_hash is unique and not null; a second row for the same Twitch account is refused."""
        from sqlalchemy.exc import IntegrityError
        from models import TwitchStarterGrant
        col = TwitchStarterGrant.__table__.c.twitch_id_hash
        assert col.unique and not col.nullable
        db.add(TwitchStarterGrant(twitch_id_hash=_h(TWITCH_ID), user_id=1, source="join", granted_at=1))
        db.commit()
        db.add(TwitchStarterGrant(twitch_id_hash=_h(TWITCH_ID), user_id=2, source="connect", granted_at=2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(TwitchStarterGrant(twitch_id_hash=None, user_id=3, source="join", granted_at=3))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_record_starter_grant_returns_false_when_row_exists(self, db):
        """record_starter_grant returns True when it adds a row and False when the Twitch id already has one (ON CONFLICT DO NOTHING)."""
        import soft_accounts
        assert soft_accounts.record_starter_grant(db, TWITCH_ID, 1, "join") is True
        assert soft_accounts.record_starter_grant(db, TWITCH_ID, 2, "connect") is False
        rows = _grants(db)
        assert len(rows) == 1 and rows[0].user_id == 1 and rows[0].source == "join"

    def test_connect_account_existing_grant_row_gets_no_bonus(self, db):
        """A Twitch id that already has a twitch_starter_grants row gets no bonus on connect."""
        import soft_accounts
        import twitch_oauth
        soft_accounts.record_starter_grant(db, TWITCH_ID, 999, "join")
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, TWITCH_ID) == "connected"
        assert _tokens(db, user) == 5
        assert _audits(db) == []

    def test_connect_account_returns_connected_bonus_message_key(self, db):
        """connect_account returns the connected_bonus message key when a bonus was granted, and "connected" otherwise."""
        import twitch_oauth
        first = _web_user(db, "first")
        assert twitch_oauth.connect_account(db, first, TWITCH_ID) == "connected_bonus"
        # Same id again on the same account: plain "connected", nothing credited.
        assert twitch_oauth.connect_account(db, first, TWITCH_ID) == "connected"
        assert _tokens(db, first) == 10
        _disconnect(db, first)
        second = _web_user(db, "second")
        assert twitch_oauth.connect_account(db, second, TWITCH_ID) == "connected"

    def test_profile_handle_twitch_return_maps_connected_bonus(self):
        """Profile shows "Twitch connected. You received N Twitch starter tokens." for connected_bonus (frontend/app-profile.js _TWITCH_RETURN_MESSAGES), with N from /config twitch_connect_bonus_tokens."""
        with open(os.path.join(FRONTEND_DIR, "app-profile.js"), encoding="utf-8") as f:
            profile = f.read()
        with open(os.path.join(FRONTEND_DIR, "app-globals.js"), encoding="utf-8") as f:
            globals_js = f.read()
        start = profile.index("const _TWITCH_RETURN_MESSAGES")
        block = profile[start:profile.index("};", start)]
        assert "connected_bonus:" in block
        assert ("Twitch connected. You received ${_twitchConnectBonusTokens} "
                "Twitch starter tokens.") in block
        # The plain key keeps its message.
        assert 'connected:        ["Twitch connected.", true]' in block
        # handleTwitchReturn renders message functions.
        handler = profile[profile.index("function handleTwitchReturn"):]
        handler = handler[:handler.index("\n}\n")]
        assert 'typeof msg[0] === "function"' in handler
        # N comes from /config.
        assert "cfg.twitch_connect_bonus_tokens" in globals_js
        assert "let _twitchConnectBonusTokens" in globals_js

    def test_config_exposes_twitch_connect_bonus_tokens(self, db, monkeypatch):
        """GET /config includes twitch_connect_bonus_tokens so the Profile message can name the amount."""
        monkeypatch.setenv("DEBUG", "true")
        from main import get_config
        assert get_config(db=db)["twitch_connect_bonus_tokens"] == 5
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "7")
        assert get_config(db=db)["twitch_connect_bonus_tokens"] == 7
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")
        assert get_config(db=db)["twitch_connect_bonus_tokens"] == 0
        monkeypatch.delenv("TWITCH_CONNECT_BONUS_TOKENS")
        monkeypatch.setenv("INITIAL_TOKENS", "3")
        assert get_config(db=db)["twitch_connect_bonus_tokens"] == 3

    def test_connect_account_bonus_zero_grants_nothing(self, db, monkeypatch):
        """TWITCH_CONNECT_BONUS_TOKENS=0 turns the bonus off; nothing is credited and no grant row is recorded."""
        import twitch_oauth
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, TWITCH_ID) == "connected"
        assert _tokens(db, user) == 5
        assert _grants(db) == []
        assert _audits(db) == []
        assert user.twitch_account_id == TWITCH_ID

    def test_connect_account_writes_audit_entry_without_twitch_id(self, db):
        """An audit entry twitch_starter_bonus names the user and amount, never the Twitch id."""
        import twitch_oauth
        user = _web_user(db)
        twitch_oauth.connect_account(db, user, TWITCH_ID)
        entries = _audits(db)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.actor_id == user.id
        assert f"user_id={user.id}" in entry.detail
        assert "amount=5" in entry.detail
        assert TWITCH_ID not in (entry.detail or "")
        assert TWITCH_ID not in (entry.actor_username or "")

    def test_env_example_documents_twitch_connect_bonus_tokens(self):
        """.env.example documents TWITCH_CONNECT_BONUS_TOKENS."""
        with open(os.path.join(REPO_ROOT, ".env.example"), encoding="utf-8") as f:
            text_ = f.read()
        assert "TWITCH_CONNECT_BONUS_TOKENS=" in text_
        idx = text_.index("TWITCH_CONNECT_BONUS_TOKENS=")
        assert "#" in text_[max(0, idx - 400):idx]


# ---------------------------------------------------------------------------
# Story 2: The Panel Path Isn't Doubled
# ---------------------------------------------------------------------------

class TestPanelPathIsNotDoubled:

    def test_join_with_identity_share_records_join_grant(self, db):
        """When a soft account with an identity share is created by Join, a twitch_starter_grants row with source='join' is recorded for its Twitch id."""
        import soft_accounts
        user, created = soft_accounts.get_or_create_soft_account(db, "Ujoin1", TWITCH_ID)
        assert created
        rows = _grants(db)
        assert len(rows) == 1
        assert rows[0].source == "join" and rows[0].user_id == user.id

    def test_soft_account_records_join_grant_when_twitch_id_becomes_known(self, db):
        """A soft account without an identity share gets a source='join' row when its Twitch id becomes known."""
        import soft_accounts
        user, created = soft_accounts.get_or_create_soft_account(db, "Ujoin2", None)
        assert created and _grants(db) == []
        again, created_again = soft_accounts.get_or_create_soft_account(db, "Ujoin2", TWITCH_ID)
        assert not created_again and again.id == user.id
        rows = _grants(db)
        assert len(rows) == 1
        assert rows[0].source == "join" and rows[0].user_id == user.id

    def test_join_without_twitch_id_records_no_grant(self, db):
        """A soft account created without an identity share records no grant row until its Twitch id is known."""
        import soft_accounts
        from models import TwitchStarterGrant
        user, created = soft_accounts.get_or_create_soft_account(db, "Ujoin3", None)
        assert created and user.twitch_account_id is None
        assert db.query(TwitchStarterGrant).count() == 0
        # A website account that gets the id through the panel (link code) records nothing.
        web = _web_user(db)
        soft_accounts.record_twitch_account_id(db, web, "555")
        db.commit()
        assert db.query(TwitchStarterGrant).count() == 0

    def test_connect_account_merge_ready_grants_no_bonus(self, db):
        """Connecting a Twitch id that a soft account holds ("merge_ready") grants no bonus; the soft account's tokens, including its starter, arrive with the merge."""
        import soft_accounts
        import twitch_oauth
        soft, _ = soft_accounts.get_or_create_soft_account(db, "Umerge1", TWITCH_ID)
        web = _web_user(db)
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "merge_ready"
        assert _tokens(db, web) == 5
        assert _audits(db) == []
        assert [g.source for g in _grants(db)] == ["join"]
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result["tokens"] == 5
        assert _tokens(db, web) == 10

    def test_merge_declined_still_grants_no_bonus(self, db):
        """If the merge never happens (declined, or the account's one merge already used), still no bonus: the starter stays with the panel collection."""
        import soft_accounts
        import twitch_oauth
        soft_accounts.get_or_create_soft_account(db, "Umerge2", TWITCH_ID)
        web = _web_user(db)
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "merge_ready"
        # Never merged: disconnect and connect again, still no bonus.
        _disconnect(db, web)
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "connected"
        assert _tokens(db, web) == 5
        # An account whose one merge is used connects another panel player's id: no bonus.
        used = _web_user(db, "used")
        used.merged_soft_account_at = 1
        db.commit()
        soft_accounts.get_or_create_soft_account(db, "Umerge3", "777")
        assert twitch_oauth.connect_account(db, used, "777") == "merge_ready"
        assert _tokens(db, used) == 5
        assert _audits(db) == []

    def test_totals_equal_for_connect_path_and_join_then_merge_path(self, db):
        """Website account plus Connect Twitch ends at INITIAL_TOKENS + bonus; website account plus Join then merge ends at INITIAL_TOKENS + soft starter; equal at the defaults."""
        import soft_accounts
        import twitch_oauth
        # Path 1: website account, Connect Twitch.
        a = _web_user(db, "patha")
        twitch_oauth.connect_account(db, a, "1001")
        # Path 2: Join in the panel, then connect and merge.
        soft_accounts.get_or_create_soft_account(db, "Upathb", "1002")
        b = _web_user(db, "pathb")
        assert twitch_oauth.connect_account(db, b, "1002") == "merge_ready"
        twitch_oauth.merge_confirm(db, {"user_id": b.id})
        assert _tokens(db, a) == _tokens(db, b) == 10


# ---------------------------------------------------------------------------
# Story 3: No Farming by Reconnecting
# ---------------------------------------------------------------------------

class TestNoFarmingByReconnecting:

    def test_disconnect_then_reconnect_same_account_no_second_bonus(self, db):
        """Disconnect, then Connect the same Twitch account to the same website account: no second bonus (the grant row stays after disconnect)."""
        import twitch_oauth
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, TWITCH_ID) == "connected_bonus"
        _disconnect(db, user)
        assert len(_grants(db)) == 1
        assert twitch_oauth.connect_account(db, user, TWITCH_ID) == "connected"
        assert _tokens(db, user) == 10
        assert len(_audits(db)) == 1

    def test_connect_same_twitch_id_to_another_account_no_bonus(self, db):
        """Connecting the same Twitch account to another website account after disconnect grants no bonus."""
        import twitch_oauth
        first = _web_user(db, "first")
        twitch_oauth.connect_account(db, first, TWITCH_ID)
        _disconnect(db, first)
        second = _web_user(db, "second")
        assert twitch_oauth.connect_account(db, second, TWITCH_ID) == "connected"
        assert _tokens(db, second) == 5
        assert _tokens(db, first) == 10

    def test_concurrent_connect_callbacks_grant_once(self, tmp_path):
        """Two simultaneous connect callbacks for one Twitch id grant once; the twitch_id_hash unique constraint decides and the loser credits nothing."""
        import threading
        from sqlalchemy.orm import sessionmaker
        import twitch_oauth
        from models import AuditLog, TwitchStarterGrant, User

        engine = _file_engine(tmp_path)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as s:
            uid = _web_user(s).id
            s.commit()

        n = 4
        barrier = threading.Barrier(n)
        results = [None] * n

        def _worker(i):
            with factory() as s:
                user = s.get(User, uid)  # read before the race, as the callback does
                barrier.wait()
                try:
                    results[i] = twitch_oauth.connect_account(s, user, TWITCH_ID)
                except Exception as exc:  # noqa: BLE001
                    results[i] = exc

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)

        assert sorted(results) == ["connected"] * (n - 1) + ["connected_bonus"], results
        with factory() as s:
            assert s.get(User, uid).tokens == 10
            assert s.query(TwitchStarterGrant).count() == 1
            assert s.query(AuditLog).filter(AuditLog.action == "twitch_starter_bonus").count() == 1
        engine.dispose()

    def test_reverse_merge_leaves_grant_row(self, db):
        """A merge reversal (reverse_merge) leaves the grant row, so the Twitch id can't earn the starter again."""
        import soft_accounts
        import twitch_oauth
        from models import TwitchMergeLog
        soft_accounts.get_or_create_soft_account(db, "Urev1", TWITCH_ID)
        web = _web_user(db)
        twitch_oauth.connect_account(db, web, TWITCH_ID)
        twitch_oauth.merge_confirm(db, {"user_id": web.id})
        log = db.query(TwitchMergeLog).one()
        soft_accounts.reverse_merge(db, log)
        db.commit()
        rows = _grants(db)
        assert len(rows) == 1 and rows[0].source == "join"
        # The restored soft account holds the id again; connecting is merge_ready, no bonus.
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "merge_ready"
        assert _audits(db) == []
        # Even with the soft account gone, the id never earns the starter again.
        soft = soft_accounts.find_by_opaque_id(db, "Urev1")
        _disconnect(db, web)
        soft_accounts.delete_soft_account(db, soft)
        db.commit()
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "connected"
        assert len(_grants(db)) == 1


# ---------------------------------------------------------------------------
# Story 4: Existing Players Are Treated the Same
# ---------------------------------------------------------------------------

class TestExistingPlayersTreatedTheSame:

    def test_migration_038_records_join_rows_for_soft_accounts(self, tmp_path):
        """Migration 038 records source='join' rows for existing soft accounts with a Twitch id."""
        from models import TwitchStarterGrant, User

        def seed(s):
            _soft_user(s, "Usoft1", "2001")
            _soft_user(s, "Usoft2", None)

        engine = _migrated_engine(tmp_path, seed)
        with Session(engine) as s:
            rows = s.query(TwitchStarterGrant).all()
            assert [(r.twitch_id_hash, r.source) for r in rows] == [(_h("2001"), "join")]
            soft = s.query(User).filter(User.twitch_user_id == "Usoft1").one()
            assert rows[0].user_id == soft.id and soft.tokens == 5
        engine.dispose()

    def test_migration_038_records_join_rows_for_merged_website_accounts(self, tmp_path):
        """Migration 038 records source='join' rows for website accounts that merged a soft account (merged_soft_account_at set), and credits them nothing."""
        import json
        from models import TwitchMergeLog, TwitchStarterGrant, User

        def seed(s):
            merged = _web_user(s, "merged")
            merged.twitch_account_id = "3001"
            merged.merged_soft_account_at = 100
            pending = _web_user(s, "pending")
            pending.twitch_account_id = "3002"
            pending.pending_merge_user_id = 999
            # Merged, then disconnected: the id is only in the undo log.
            gone = _web_user(s, "gone")
            gone.merged_soft_account_at = 100
            s.flush()
            s.add(TwitchMergeLog(full_user_id=gone.id, merged_at=100,
                                 soft_snapshot=json.dumps({"twitch_account_id": "3003"}),
                                 card_ids="[]", tokens_moved=5, roster_entries="[]"))

        engine = _migrated_engine(tmp_path, seed)
        with Session(engine) as s:
            rows = {r.twitch_id_hash: r.source for r in s.query(TwitchStarterGrant).all()}
            assert rows == {_h("3001"): "join", _h("3002"): "join", _h("3003"): "join"}
            for name in ("merged", "pending", "gone"):
                assert s.query(User).filter(User.username == name).one().tokens == 5
        engine.dispose()

    def test_migration_038_credits_connected_unmerged_accounts_once(self, tmp_path):
        """Migration 038 credits the bonus once, with a 'connect' row, to each website account with a twitch_account_id, no grant row for that id, and no merge."""
        from models import TwitchStarterGrant, User

        def seed(s):
            a = _web_user(s, "conn_a")
            a.twitch_account_id = "4001"
            b = _web_user(s, "conn_b", tokens=2)
            b.twitch_account_id = "4002"
            _web_user(s, "plain")

        engine = _migrated_engine(tmp_path, seed)
        with Session(engine) as s:
            by_name = {u.username: u for u in s.query(User).all()}
            assert by_name["conn_a"].tokens == 10
            assert by_name["conn_b"].tokens == 7
            assert by_name["plain"].tokens == 5
            rows = {r.twitch_id_hash: (r.source, r.user_id, r.amount)
                    for r in s.query(TwitchStarterGrant).all()}
            assert rows == {_h("4001"): ("connect", by_name["conn_a"].id, 5),
                            _h("4002"): ("connect", by_name["conn_b"].id, 5)}
        engine.dispose()

    def test_migration_038_skips_accounts_with_existing_grant_row(self, tmp_path):
        """Migration 038 credits nothing to a connected website account whose Twitch id already has a grant row."""
        from models import TwitchStarterGrant, User

        def seed(s):
            u = _web_user(s, "already")
            u.twitch_account_id = "5001"
            s.add(TwitchStarterGrant(twitch_id_hash=_h("5001"), user_id=None, source="join", granted_at=1))

        engine = _migrated_engine(tmp_path, seed)
        with Session(engine) as s:
            assert s.query(User).filter(User.username == "already").one().tokens == 5
            assert s.query(TwitchStarterGrant).count() == 1
        engine.dispose()

    def test_migration_038_logs_count_and_writes_audit_entry_per_user(self, tmp_path, caplog):
        """Migration 038 logs the credited count and writes one twitch_starter_bonus audit entry per credited user, with migration=038 in detail."""
        import logging
        from models import AuditLog, User

        def seed(s):
            for i, tid in enumerate(("6001", "6002")):
                u = _web_user(s, f"log{i}")
                u.twitch_account_id = tid

        with caplog.at_level(logging.INFO, logger="migrate"):
            engine = _migrated_engine(tmp_path, seed)
        assert any("Migration 038" in r.getMessage() and "to 2 account(s)" in r.getMessage()
                   for r in caplog.records)
        with Session(engine) as s:
            ids = {u.id for u in s.query(User).filter(User.username.like("log%")).all()}
            entries = s.query(AuditLog).filter(AuditLog.action == "twitch_starter_bonus").all()
            assert len(entries) == 2
            for e in entries:
                assert "migration=038" in e.detail and "amount=5" in e.detail
                assert "6001" not in e.detail and "6002" not in e.detail
            assert {int(e.detail.split("user_id=")[1].split()[0]) for e in entries} == ids
        engine.dispose()

    def test_migration_038_second_run_credits_nothing(self, tmp_path):
        """A second run of migration 038 credits nothing and writes no further audit entries."""
        import migrate
        from models import AuditLog, User

        def seed(s):
            u = _web_user(s, "twice")
            u.twitch_account_id = "7001"

        engine = _migrated_engine(tmp_path, seed)
        migrate.run_migrations(engine)
        # Even run directly again (registry bypassed), the grant rows stop a second credit.
        with engine.connect() as conn:
            migrate._m038_twitch_starter_grants_backfill(conn)
        with Session(engine) as s:
            assert s.query(User).filter(User.username == "twice").one().tokens == 10
            assert s.query(AuditLog).filter(AuditLog.action == "twitch_starter_bonus").count() == 1
        engine.dispose()


# ---------------------------------------------------------------------------
# Stage 3 review follow-ups: one Twitch starter per website account (High),
# merge after a connect bonus (Medium 1), hashed Twitch ids (Medium 2)
# ---------------------------------------------------------------------------

class TestOneTwitchStarterPerWebsiteAccount:

    def test_second_twitch_account_on_same_website_account_gets_no_bonus(self, db):
        """Connect Twitch A (+bonus), disconnect, connect Twitch B: no bonus and no grant row for B, so B can still earn it on another website account."""
        import twitch_oauth
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, "8001") == "connected_bonus"
        _disconnect(db, user)
        assert twitch_oauth.connect_account(db, user, "8002") == "connected"
        assert _tokens(db, user) == 10
        assert _grants(db, "8002") == []
        _disconnect(db, user)
        other = _web_user(db, "other")
        assert twitch_oauth.connect_account(db, other, "8002") == "connected_bonus"
        assert _tokens(db, other) == 10
        assert len(_audits(db)) == 2

    def test_merged_website_account_connecting_new_id_gets_no_bonus(self, db):
        """A website account that merged a soft account already got a Twitch starter: connecting a new Twitch id pays no bonus and records no row."""
        import soft_accounts
        import twitch_oauth
        soft_accounts.get_or_create_soft_account(db, "Umerged", "8101")
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, "8101") == "merge_ready"
        twitch_oauth.merge_confirm(db, {"user_id": user.id})
        assert _tokens(db, user) == 10
        _disconnect(db, user)
        assert twitch_oauth.connect_account(db, user, "8102") == "connected"
        assert _tokens(db, user) == 10
        assert _grants(db, "8102") == []

    def test_migration_038_credits_at_most_once_per_website_account(self, tmp_path):
        """Migration 038 credits nothing to a website account that already has a 'connect' row (for another Twitch id)."""
        import soft_accounts
        from models import TwitchStarterGrant, User

        def seed(s):
            u = _web_user(s, "had_bonus")
            u.twitch_account_id = "8201"
            s.flush()
            s.add(TwitchStarterGrant(twitch_id_hash=soft_accounts.starter_grant_hash("8200"),
                                     user_id=u.id, source="connect", amount=5, granted_at=1))

        engine = _migrated_engine(tmp_path, seed)
        with Session(engine) as s:
            assert s.query(User).filter(User.username == "had_bonus").one().tokens == 5
            assert s.query(TwitchStarterGrant).count() == 1
        engine.dispose()


class TestMergeAfterConnectBonus:

    def _bonus_then_pending(self, db, soft_tokens=5):
        """Soft account joins without the identity share, the owner connects on the
        website (bonus), then the soft account shares its identity (pending merge)."""
        import soft_accounts
        import twitch
        import twitch_oauth
        soft, _ = soft_accounts.get_or_create_soft_account(db, "Ulate", None)
        soft.tokens = soft_tokens
        db.commit()
        web = _web_user(db)
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "connected_bonus"
        twitch._record_identity_share(db, soft, {"user_id": TWITCH_ID})
        db.commit()
        db.refresh(web)
        assert web.pending_merge_user_id == soft.id
        return soft, web

    def test_merge_leaves_starter_behind_after_connect_bonus(self, db):
        """A website account that got the connect bonus gets the soft account's tokens minus that bonus at the merge; the deduction is in the result, the audit and the pending prompt."""
        import twitch_oauth
        from models import AuditLog
        _, web = self._bonus_then_pending(db)
        pending = twitch_oauth.connection_status(db, web)["pending_merge"]
        assert pending["tokens"] == 0 and pending["starter_deducted"] == 5
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result["tokens"] == 0 and result["starter_deducted"] == 5
        assert _tokens(db, web) == 10
        entry = db.query(AuditLog).filter(AuditLog.action == "twitch_account_merged").one()
        assert "starter_deducted=5" in entry.detail and "tokens=0" in entry.detail

    def test_merge_deduction_keeps_extra_tokens_and_reversal_restores_all(self, db):
        """Soft tokens above the starter still move; the deduction never goes below 0; a reversal gives the soft account its whole balance back."""
        import soft_accounts
        import twitch_oauth
        from models import TwitchMergeLog
        _, web = self._bonus_then_pending(db, soft_tokens=7)
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result["tokens"] == 2 and result["starter_deducted"] == 5
        assert _tokens(db, web) == 12
        log = db.query(TwitchMergeLog).one()
        out = soft_accounts.reverse_merge(db, log)
        db.commit()
        assert _tokens(db, web) == 10
        from models import User
        assert db.get(User, out["soft_user_id"]).tokens == 7

    def test_merge_deduction_takes_shortfall_from_website_balance(self, db):
        """Soft tokens below the bonus: the rest of the bonus comes from the website account's balance in the same merge."""
        import twitch_oauth
        _, web = self._bonus_then_pending(db, soft_tokens=2)
        pending = twitch_oauth.connection_status(db, web)["pending_merge"]
        assert pending == {"cards": 0, "tokens": 0, "starter_deducted": 5, "balance_change": -3}
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result["tokens"] == 0 and result["starter_deducted"] == 5 and result["from_website"] == 3
        assert _tokens(db, web) == 7

    def test_merge_without_connect_bonus_moves_everything(self, db):
        """Without a connect bonus nothing is deducted (the plain panel path)."""
        import soft_accounts
        import twitch_oauth
        soft_accounts.get_or_create_soft_account(db, "Uplain", TWITCH_ID)
        web = _web_user(db)
        twitch_oauth.connect_account(db, web, TWITCH_ID)
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result["tokens"] == 5 and result["starter_deducted"] == 0

    def test_profile_shows_starter_deducted_note(self):
        """Profile names tokens that stay behind in the merge prompt and the merge message."""
        with open(os.path.join(FRONTEND_DIR, "app-profile.js"), encoding="utf-8") as f:
            js = f.read()
        assert "function _starterDeductedNote" in js
        assert "_starterDeductedNote(pending.starter_deducted)" in js
        assert "_starterDeductedNote(data.starter_deducted)" in js


class TestHashedTwitchIds:

    def test_grant_rows_keep_no_raw_twitch_id(self, db):
        """twitch_starter_grants keeps an HMAC-SHA256 hex of the Twitch id, never the id."""
        import soft_accounts
        import twitch_oauth
        from models import TwitchStarterGrant
        soft_accounts.get_or_create_soft_account(db, "Uhash", "9001")
        twitch_oauth.connect_account(db, _web_user(db), TWITCH_ID)
        rows = db.query(TwitchStarterGrant).all()
        assert len(rows) == 2
        for r in rows:
            assert len(r.twitch_id_hash) == 64 and int(r.twitch_id_hash, 16) >= 0
            for value in (r.twitch_id_hash, r.source, str(r.user_id), str(r.amount)):
                assert "9001" not in value and TWITCH_ID not in value
        assert "twitch_account_id" not in TwitchStarterGrant.__table__.c

    def test_hash_is_keyed_with_secret_key(self, monkeypatch):
        """The hash depends on SECRET_KEY (rotating it resets the check) and is stable for one key."""
        import hashlib
        import soft_accounts
        monkeypatch.setenv("SECRET_KEY", "a" * 40)
        first = soft_accounts.starter_grant_hash(TWITCH_ID)
        assert first == soft_accounts.starter_grant_hash(TWITCH_ID)
        assert first != hashlib.sha256(TWITCH_ID.encode()).hexdigest()
        monkeypatch.setenv("SECRET_KEY", "b" * 40)
        assert soft_accounts.starter_grant_hash(TWITCH_ID) != first

    def test_privacy_page_mentions_hashed_record(self):
        """privacy.html says a one-way hashed record of the Twitch account is kept after Disconnect or Leave."""
        with open(os.path.join(FRONTEND_DIR, "privacy.html"), encoding="utf-8") as f:
            html = f.read()
        assert "one-way hashed record" in html
        assert "starter tokens" in html


class TestProfileBonusFallback:

    def test_connected_bonus_message_falls_back_without_amount(self):
        """When the configured amount isn't a positive integer, Profile says "You received your Twitch starter tokens." instead of 0."""
        with open(os.path.join(FRONTEND_DIR, "app-profile.js"), encoding="utf-8") as f:
            js = f.read()
        start = js.index("const _TWITCH_RETURN_MESSAGES")
        block = js[start:js.index("};", start)]
        assert "_twitchConnectBonusTokens > 0" in block
        assert "Twitch connected. You received your Twitch starter tokens." in block


class TestSpentSoftStarter:
    """Security re-check (Medium): the bonus is taken back in full even when the soft
    account's starter was spent before the merge."""

    def _spent_then_pending(self, db, soft_tokens=0):
        return TestMergeAfterConnectBonus()._bonus_then_pending(db, soft_tokens=soft_tokens)

    def test_spent_soft_starter_takes_bonus_from_website_balance(self, db):
        """Soft starter spent (0 tokens): the merge takes the whole bonus from the website account; prompt and audit say so."""
        import twitch_oauth
        from models import AuditLog
        _, web = self._spent_then_pending(db)
        pending = twitch_oauth.connection_status(db, web)["pending_merge"]
        assert pending["tokens"] == 0 and pending["balance_change"] == -5
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result == {"merged": True, "cards": 0, "tokens": 0, "starter_deducted": 5, "from_website": 5}
        assert _tokens(db, web) == 5
        entry = db.query(AuditLog).filter(AuditLog.action == "twitch_account_merged").one()
        assert "starter_deducted=5" in entry.detail and "from_website=5" in entry.detail

    def test_website_balance_never_negative(self, db):
        """A website balance below the shortfall goes to 0, never negative; starter_deducted is what was actually taken."""
        import twitch_oauth
        from models import User
        _, web = self._spent_then_pending(db)
        db.query(User).filter(User.id == web.id).update({"tokens": 2})
        db.commit()
        assert twitch_oauth.connection_status(db, web)["pending_merge"]["balance_change"] == -2
        result = twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert result["starter_deducted"] == 2 and result["from_website"] == 2
        assert _tokens(db, web) == 0

    @pytest.mark.parametrize("soft_tokens", [0, 2, 7])
    def test_reverse_restores_both_sides_exactly(self, db, soft_tokens):
        """reverse_merge gives the website account back what the merge took from it and the soft account its gross balance; the audit names both parts."""
        import soft_accounts
        import twitch_oauth
        from models import AuditLog, TwitchMergeLog, User
        _, web = self._spent_then_pending(db, soft_tokens=soft_tokens)
        before = _tokens(db, web)
        twitch_oauth.merge_confirm(db, {"user_id": web.id})
        out = soft_accounts.reverse_merge(db, db.query(TwitchMergeLog).one())
        db.commit()
        assert _tokens(db, web) == before
        assert db.get(User, out["soft_user_id"]).tokens == soft_tokens
        from_soft = min(soft_tokens, 5)
        assert out["starter_restored"] == from_soft
        assert out["from_website_restored"] == 5 - from_soft
        entry = db.query(AuditLog).filter(AuditLog.action == "twitch_merge_reversed").one()
        assert f"starter_restored={from_soft}" in entry.detail
        assert f"from_website={5 - from_soft}" in entry.detail

    @pytest.mark.parametrize("soft_tokens", [0, 2, 7])
    def test_merge_reverse_merge_stays_balanced(self, db, soft_tokens):
        """Merge, reverse, connect again and merge again: the second merge ends where the first did."""
        import soft_accounts
        import twitch_oauth
        from models import TwitchMergeLog
        _, web = self._spent_then_pending(db, soft_tokens=soft_tokens)
        twitch_oauth.merge_confirm(db, {"user_id": web.id})
        after_first = _tokens(db, web)
        soft_accounts.reverse_merge(db, db.query(TwitchMergeLog).one())
        db.commit()
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "merge_ready"
        twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert _tokens(db, web) == after_first
        assert len(_audits(db)) == 1  # the bonus itself was paid once

    def test_profile_explains_negative_balance_change(self):
        """Profile says the merge removes N tokens from the balance when balance_change is negative, and names from_website after the merge."""
        with open(os.path.join(FRONTEND_DIR, "app-profile.js"), encoding="utf-8") as f:
            js = f.read()
        assert "function _mergePromptNote" in js and "function _mergeResultNote" in js
        assert "Adding it removes ${-change} tokens from your balance" in js
        assert "pending.balance_change" in js and "data.from_website" in js
        assert "_mergePromptNote(pending)" in js and "_mergeResultNote(data)" in js


class TestOneConnectRowPerWebsiteAccount:
    """Security re-check (Low 1): a partial unique index makes the once-per-website-account
    check race-safe."""

    def test_index_on_connect_user(self, db):
        """ux_twitch_starter_grants_connect_user: a second 'connect' row for one user is ignored; 'join' rows aren't limited."""
        import soft_accounts
        assert soft_accounts.record_starter_grant(db, "A1", 1, "connect", 5) is True
        assert soft_accounts.record_starter_grant(db, "A2", 1, "connect", 5) is False
        assert soft_accounts.record_starter_grant(db, "A3", 1, "join") is True
        assert soft_accounts.record_starter_grant(db, "A4", 1, "join") is True
        assert _grants(db, "A2") == []

    def test_migration_038_create_path_creates_index(self):
        """The migration's create-table path creates the partial unique index too."""
        import migrate
        from sqlalchemy import text as sql
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, tokens INTEGER, "
                             "account_type TEXT, twitch_account_id TEXT, merged_soft_account_at INTEGER, "
                             "pending_merge_user_id INTEGER)"))
            conn.commit()
            migrate._m038_twitch_starter_grants_backfill(conn)
            names = {r[1] for r in conn.execute(sql("PRAGMA index_list(twitch_starter_grants)")).fetchall()}
        assert "ux_twitch_starter_grants_connect_user" in names

    def test_concurrent_connects_of_two_ids_to_one_account_credit_once(self, tmp_path):
        """Two Twitch ids connecting to one website account at the same time: one bonus, one 'connect' row."""
        import threading
        from sqlalchemy.orm import sessionmaker
        import twitch_oauth
        from models import AuditLog, TwitchStarterGrant, User

        engine = _file_engine(tmp_path, "race2.db")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as s:
            uid = _web_user(s).id
            s.commit()
        ids = ["7701", "7702"]
        barrier = threading.Barrier(len(ids))
        results = [None] * len(ids)

        def _worker(i):
            with factory() as s:
                user = s.get(User, uid)
                barrier.wait()
                try:
                    results[i] = twitch_oauth.connect_account(s, user, ids[i])
                except Exception as exc:  # noqa: BLE001
                    results[i] = exc

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(len(ids))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert results.count("connected_bonus") == 1, results
        with factory() as s:
            assert s.get(User, uid).tokens == 10
            assert s.query(TwitchStarterGrant).filter(TwitchStarterGrant.source == "connect").count() == 1
            assert s.query(AuditLog).filter(AuditLog.action == "twitch_starter_bonus").count() == 1
        engine.dispose()

    def test_index_refuses_second_connect_row_when_check_is_bypassed(self, db, monkeypatch):
        """With the SELECT check bypassed (as in a race), the index alone stops a second bonus for the account."""
        import soft_accounts
        import twitch_oauth
        user = _web_user(db)
        assert twitch_oauth.connect_account(db, user, "7801") == "connected_bonus"
        _disconnect(db, user)
        monkeypatch.setattr(soft_accounts, "has_received_twitch_starter", lambda d, u: False)
        assert twitch_oauth.connect_account(db, user, "7802") == "connected"
        assert _tokens(db, user) == 10
        assert _grants(db, "7802") == []


class TestPrivacyMergeRecordWording:

    def test_privacy_mentions_30_day_merge_record_and_hashed_record(self):
        """privacy.html: after a merge the merge record (with the Twitch id) is kept up to 30 days; a one-way hashed record is kept so starter tokens aren't granted twice."""
        import re
        with open(os.path.join(FRONTEND_DIR, "privacy.html"), encoding="utf-8") as f:
            html = re.sub(r"\s+", " ", f.read())
        assert "one-way hashed record" in html
        assert "30 days" in html
        assert "kept only a one-way hashed record" not in html and "we keep only a one-way" not in html


class TestMergeReadsUnderLock:
    """Final round (Low): the bonus read and the pending-merge re-check run under the
    write lock taken by the merge's first UPDATE."""

    def test_bonus_read_and_pending_check_follow_the_lock_update(self):
        """In merge_soft_into, the no-op lock UPDATE comes before starter_bonus_received and the pending re-check."""
        import inspect
        import soft_accounts
        src = inspect.getsource(soft_accounts.merge_soft_into)
        lock = src.index('UPDATE users SET tokens = COALESCE(tokens, 0) WHERE id = :full')
        assert lock < src.index("starter_bonus_received(db, full.id)")
        assert lock < src.index("SELECT pending_merge_user_id, merged_soft_account_at")

    def test_merge_confirm_refuses_when_pending_changed_under_lock(self, db, monkeypatch):
        """If the pending merge changes after merge_confirm's check (a simultaneous disconnect), the locked re-check answers 404 and moves nothing."""
        import soft_accounts
        import twitch_oauth
        from fastapi import HTTPException
        from models import TwitchMergeLog
        soft, _ = soft_accounts.get_or_create_soft_account(db, "Urecheck", TWITCH_ID)
        web = _web_user(db)
        assert twitch_oauth.connect_account(db, web, TWITCH_ID) == "merge_ready"
        real = soft_accounts.merge_soft_into

        def _race(d, s, f, **kw):
            # Another request clears the pending merge between the check and the lock.
            d.execute(__import__("sqlalchemy").text(
                "UPDATE users SET pending_merge_user_id = NULL WHERE id = :id"), {"id": f.id})
            return real(d, s, f, **kw)

        monkeypatch.setattr(soft_accounts, "merge_soft_into", _race)
        with pytest.raises(HTTPException) as exc:
            twitch_oauth.merge_confirm(db, {"user_id": web.id})
        assert exc.value.status_code == 404
        assert db.query(TwitchMergeLog).count() == 0
        assert _tokens(db, web) == 5
        assert db.get(type(web), soft.id) is not None
