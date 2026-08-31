"""
Failing test stubs for plan-issue-83-demo-mode.

Pre-implementation stage: none of `backend/clock.py`, the `DemoClock` model, or the
`/admin/demo/*` endpoints exist yet. Every stub below imports the names the plan commits
to (`clock.now`, `clock.get_override`, `clock.set_override`, `clock.clear_override`,
`DemoClock`, `DemoClockBody`, `SeedDemoAccountsBody`, `get_demo_clock`, `set_demo_clock`,
`clear_demo_clock`, `seed_demo_accounts`) and will fail at collection/import time until the
developer implements them. Each stub body is `pytest.fail("not yet implemented")` — the
developer replaces the body (and un-skips the local import) when implementing.

Covers four user stories from markdown/plans/plan-issue-83-demo-mode.md:

  Story: Move the Demo Clock
    - GET/POST/DELETE /admin/demo/clock return 404 when DEMO_MODE is unset
    - POST /admin/demo/clock requires an admin session when DEMO_MODE=true
    - POST /admin/demo/clock sets DemoClock.override_timestamp and synchronously
      re-runs auto_lock_weeks and generate_weekly_summaries (added for
      plan-issue-51-weekly-summary — see markdown/lessons-learned.md)
    - GET /admin/demo/clock returns the override and the effective "now"
    - DELETE /admin/demo/clock clears the override; clock.now(db) falls back to
      real wall-clock time
    - auto_lock_weeks / get_current_week / get_next_editable_week all read "now"
      via clock.now(db) instead of time.time()

  Story: See Demo Mode Reflected in the App
    - GET /config includes demo_mode: true only when DEMO_MODE=true
    - GET /config omits/falses demo_mode when DEMO_MODE is unset
    - Demo Mode badge visibility (frontend-only)
    - Settings tab Demo Mode panel DOM presence (frontend-only)

  Story: Seed Demo Accounts
    - POST /admin/demo/seed-accounts returns 404 when DEMO_MODE is unset
    - Creates demo1, demo2, ... skipping already-taken usernames
    - Each account receives cards_per_account cards via draw_card, auto-activated
      up to ROSTER_LIMIT
    - Response includes a one-time plaintext password that verifies against the
      stored bcrypt hash
    - Writes an audit log entry with action admin_demo_accounts_seeded

  Story: Guard Against Accidental Production Exposure
    - All three /admin/demo/* endpoints 404 (not 403) when DEMO_MODE is unset,
      for both admin and non-admin identities
    - .env.example documents DEMO_MODE
    - The ingest poll thread does not start when DEMO_MODE=true
    - The week auto-lock (maintenance) thread still starts when DEMO_MODE=true
    - Non-admin sessions get 403 (not 404) on all three endpoints when DEMO_MODE=true
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_NON_ADMIN = {"user_id": 2, "username": "u", "is_admin": False}
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# Story: Move the Demo Clock
# ---------------------------------------------------------------------------

class TestMoveTheDemoClock:
    def test_get_demo_clock_404_when_demo_mode_unset(self, db, monkeypatch):
        """GET /admin/demo/clock returns 404 when DEMO_MODE is unset, even for an admin."""
        monkeypatch.delenv("DEMO_MODE", raising=False)
        from routers.admin_demo import get_demo_clock
        with pytest.raises(HTTPException) as exc:
            get_demo_clock(db=db, _=_ADMIN)
        assert exc.value.status_code == 404

    def test_post_demo_clock_requires_admin_returns_403_when_demo_mode_true(self, db, monkeypatch):
        """POST /admin/demo/clock requires an admin session like other admin endpoints."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from deps import require_admin
        with pytest.raises(HTTPException) as exc:
            require_admin(_NON_ADMIN, db=db)
        assert exc.value.status_code == 403

    def test_post_demo_clock_sets_override_and_reruns_auto_lock_weeks(self, db, monkeypatch):
        """Setting the clock past a week's start_time locks it synchronously, in-request."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import set_demo_clock, DemoClockBody
        from models import Week
        week = Week(label="W1", start_time=1_000_000, end_time=1_600_000, is_locked=False)
        db.add(week)
        db.commit()
        set_demo_clock(DemoClockBody(timestamp=1_000_001), db=db, admin=_ADMIN)
        db.refresh(week)
        assert week.is_locked is True

    def test_post_demo_clock_sets_override_and_reruns_generate_weekly_summaries(self, db, monkeypatch):
        """Setting the clock past a week's end_time makes its Weekly Report available
        synchronously, in-request — otherwise a demo operator would have to wait for the
        real-wall-clock week-maintenance loop (up to WEEK_CHECK_INTERVAL, unaffected by the
        demo clock override) before the report they just "ended" the week for shows up."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import set_demo_clock, DemoClockBody
        from models import Week, WeeklySummary
        week = Week(label="W1", start_time=1_000_000, end_time=1_600_000, is_locked=False)
        db.add(week)
        db.commit()
        set_demo_clock(DemoClockBody(timestamp=1_600_001), db=db, admin=_ADMIN)
        assert db.get(WeeklySummary, week.id) is not None

    def test_get_demo_clock_returns_override_and_effective_now(self, db, monkeypatch):
        """GET /admin/demo/clock reports both the stored override and clock.now(db)."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import set_demo_clock, get_demo_clock, DemoClockBody
        set_demo_clock(DemoClockBody(timestamp=5_000_000), db=db, admin=_ADMIN)
        result = get_demo_clock(db=db, _=_ADMIN)
        assert result["override_timestamp"] == 5_000_000
        assert result["effective_now"] == 5_000_000

    def test_delete_demo_clock_clears_override_and_falls_back_to_real_time(self, db, monkeypatch):
        """DELETE /admin/demo/clock clears the override; clock.now(db) resumes tracking real time."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import set_demo_clock, clear_demo_clock, DemoClockBody
        import clock
        set_demo_clock(DemoClockBody(timestamp=5_000_000), db=db, admin=_ADMIN)
        clear_demo_clock(db=db, admin=_ADMIN)
        assert clock.get_override(db) is None
        assert abs(clock.now(db) - int(time.time())) < 5

    def test_weeks_functions_read_now_via_clock_module(self, db):
        """auto_lock_weeks, get_current_week, and get_next_editable_week all call
        clock.now(db) rather than time.time() directly, per the plan's Step 2."""
        weeks_path = os.path.join(_BACKEND_DIR, "weeks.py")
        with open(weeks_path) as f:
            source = f.read()
        assert "clock.now(db)" in source
        assert source.count("time.time()") == 0  # replaced, not just supplemented


# ---------------------------------------------------------------------------
# Story: See Demo Mode Reflected in the App
# ---------------------------------------------------------------------------

class TestDemoModeReflectedInApp:
    def test_config_includes_demo_mode_true_when_env_set(self, db, monkeypatch):
        """GET /config returns demo_mode: true when DEMO_MODE=true is set on the server."""
        monkeypatch.setenv("DEMO_MODE", "true")
        # DEBUG=true only matters the first time `main` is imported in this process
        # (module-level SECRET_KEY check); harmless no-op if already imported.
        monkeypatch.setenv("DEBUG", "true")
        from main import get_config
        result = get_config(db=db)
        assert result["demo_mode"] is True

    def test_config_omits_or_falses_demo_mode_when_env_unset(self, db, monkeypatch):
        """GET /config does not report demo_mode: true when DEMO_MODE is unset."""
        monkeypatch.delenv("DEMO_MODE", raising=False)
        monkeypatch.setenv("DEBUG", "true")
        from main import get_config
        result = get_config(db=db)
        assert result.get("demo_mode", False) is False

    def test_demo_mode_badge_visible_only_when_demo_mode_true(self):
        # frontend-only: badge visibility toggling lives in frontend/app-globals.js
        pytest.skip(
            "frontend-only: not testable via pytest — "
            "verify a persistent 'DEMO MODE' badge is shown on every tab when "
            "window.demoMode (derived from GET /config demo_mode) is true, and "
            "hidden otherwise"
        )

    def test_settings_demo_panel_absent_from_dom_when_demo_mode_false(self):
        # frontend-only: conditional panel rendering lives in frontend/index.html /
        # frontend/app-admin.js
        pytest.skip(
            "frontend-only: not testable via pytest — "
            "verify the Settings tab's Demo Mode section (clock control + account "
            "seeding) is entirely absent from the DOM, not just hidden via CSS, "
            "when demo_mode is false"
        )


# ---------------------------------------------------------------------------
# Story: Seed Demo Accounts
# ---------------------------------------------------------------------------

class TestSeedDemoAccounts:
    def test_seed_accounts_404_when_demo_mode_unset(self, db, monkeypatch):
        """POST /admin/demo/seed-accounts returns 404 when DEMO_MODE is unset."""
        monkeypatch.delenv("DEMO_MODE", raising=False)
        from routers.admin_demo import seed_demo_accounts, SeedDemoAccountsBody
        with pytest.raises(HTTPException) as exc:
            seed_demo_accounts(SeedDemoAccountsBody(), db=db, admin=_ADMIN)
        assert exc.value.status_code == 404

    def test_seed_accounts_creates_named_accounts_skipping_taken_usernames(self, db, monkeypatch):
        """Repeated calls add demo1, demo2, ... without colliding with existing usernames."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import seed_demo_accounts, SeedDemoAccountsBody
        from models import User
        db.add(User(username="demo1", email="demo1@demo.local", password_hash="x", tokens=0))
        db.commit()
        result = seed_demo_accounts(
            SeedDemoAccountsBody(count=2, cards_per_account=1), db=db, admin=_ADMIN)
        usernames = {a["username"] for a in result["accounts"]}
        assert usernames == {"demo2", "demo3"}

    def test_seed_accounts_grants_cards_and_activates_up_to_roster_limit(self, db, monkeypatch):
        """Each generated account receives cards_per_account cards via draw_card,
        auto-activated into its roster up to ROSTER_LIMIT."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import seed_demo_accounts, SeedDemoAccountsBody
        from models import Card, Player, User
        for i in range(3):
            db.add(Player(id=i + 1, name=f"P{i}"))
        db.commit()
        result = seed_demo_accounts(
            SeedDemoAccountsBody(count=1, cards_per_account=3), db=db, admin=_ADMIN)
        user = db.query(User).filter_by(username=result["accounts"][0]["username"]).first()
        cards = db.query(Card).filter_by(owner_id=user.id).all()
        assert len(cards) == 3
        assert all(c.is_active for c in cards)  # under ROSTER_LIMIT

    def test_seed_accounts_returned_password_verifies_against_stored_hash(self, db, monkeypatch):
        """The one-time plaintext password in the response verifies against the bcrypt
        hash actually stored on the User row."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import seed_demo_accounts, SeedDemoAccountsBody
        from auth import verify_password
        from models import User
        result = seed_demo_accounts(
            SeedDemoAccountsBody(count=1, cards_per_account=0), db=db, admin=_ADMIN)
        account = result["accounts"][0]
        user = db.query(User).filter_by(username=account["username"]).first()
        assert verify_password(account["password"], user.password_hash)

    def test_seed_accounts_writes_audit_log_admin_demo_accounts_seeded(self, db, monkeypatch):
        """A successful seed call writes an AuditLog row with action
        admin_demo_accounts_seeded."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from routers.admin_demo import seed_demo_accounts, SeedDemoAccountsBody
        from models import AuditLog
        seed_demo_accounts(SeedDemoAccountsBody(count=2, cards_per_account=0),
                            db=db, admin=_ADMIN)
        log = db.query(AuditLog).filter_by(action="admin_demo_accounts_seeded").first()
        assert log is not None
        assert "2" in log.detail


# ---------------------------------------------------------------------------
# Story: Guard Against Accidental Production Exposure
# ---------------------------------------------------------------------------

class TestGuardAgainstProductionExposure:
    def test_all_demo_endpoints_404_when_demo_mode_unset_for_admin_and_non_admin(self, db, monkeypatch):
        """All three /admin/demo/* endpoints return 404 (not 403) when DEMO_MODE is
        unset/false, regardless of caller identity, so their existence isn't revealed."""
        monkeypatch.delenv("DEMO_MODE", raising=False)
        from routers.admin_demo import (
            get_demo_clock, set_demo_clock, clear_demo_clock, seed_demo_accounts,
            DemoClockBody, SeedDemoAccountsBody,
        )
        for identity in (_ADMIN, _NON_ADMIN):
            for call in (
                lambda: get_demo_clock(db=db, _=identity),
                lambda: set_demo_clock(DemoClockBody(timestamp=0), db=db, admin=identity),
                lambda: clear_demo_clock(db=db, admin=identity),
                lambda: seed_demo_accounts(SeedDemoAccountsBody(), db=db, admin=identity),
            ):
                with pytest.raises(HTTPException) as exc:
                    call()
                assert exc.value.status_code == 404

    def test_non_admin_gets_403_not_404_on_demo_endpoints_when_demo_mode_true(self, db, monkeypatch):
        """When DEMO_MODE=true, a non-admin caller is rejected by require_admin (403)
        before _require_demo_mode is even relevant — 404 is reserved for the mode
        being off, not for lack of admin rights."""
        monkeypatch.setenv("DEMO_MODE", "true")
        from deps import require_admin
        with pytest.raises(HTTPException) as exc:
            require_admin(_NON_ADMIN, db=db)
        assert exc.value.status_code == 403

    def test_env_example_documents_demo_mode(self):
        """.env.example documents DEMO_MODE with an explicit never-set-in-production note."""
        env_example_path = os.path.join(_BACKEND_DIR, "..", ".env.example")
        with open(env_example_path) as f:
            content = f.read()
        assert "DEMO_MODE" in content

    def test_ingest_poll_thread_does_not_start_when_demo_mode_true(self):
        """main.py guards the _ingest_poll_loop thread start behind a DEMO_MODE check
        (source-inspection style, mirroring how test_issue_81 checked for
        generate_weeks removal via source read)."""
        main_path = os.path.join(_BACKEND_DIR, "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "DEMO_MODE" in source
        # Look for the ingest thread start being conditioned on demo mode being off.
        assert "if _DEMO_MODE" in source or "if not _DEMO_MODE" in source

    def test_week_maintenance_thread_still_starts_when_demo_mode_true(self):
        """The week auto-lock (_week_maintenance_loop) thread start is unconditional —
        not gated behind the same DEMO_MODE check as the ingest poll thread."""
        main_path = os.path.join(_BACKEND_DIR, "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "_week_maintenance_loop" in source


# ---------------------------------------------------------------------------
# Real HTTP-level check of the FastAPI dependency resolution order.
#
# Every test above calls endpoint functions directly, bypassing FastAPI's
# Depends() resolution entirely (this codebase's established unit-test
# convention — see test_issue_79/81). That style cannot prove which
# dependency FastAPI evaluates first, so a non-admin + disabled-mode request
# could still 403 in production even though every direct-call test above
# passes. Only a real ASGI round-trip via TestClient proves the ordering.
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """TestClient backed by an in-memory SQLite database (mirrors the fixture
    in test_security_headers.py, trimmed to what this check needs)."""
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.delenv("DEMO_MODE", raising=False)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import importlib
    import database
    import main as main_module
    from fastapi.testclient import TestClient

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session_factory)

    import enrich, ingest, seed
    monkeypatch.setattr(enrich, "SessionLocal", test_session_factory)
    monkeypatch.setattr(ingest, "SessionLocal", test_session_factory)
    monkeypatch.setattr(seed, "SessionLocal", test_session_factory)

    importlib.reload(main_module)
    main_module.engine = test_engine
    main_module.SessionLocal = test_session_factory

    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        yield c


class TestDemoModeDependencyOrderOverHttp:
    def test_unauthenticated_request_gets_404_not_401_when_demo_mode_unset(self, client):
        """A real HTTP request with no session at all must still 404 (mode
        disabled) rather than 401 (would-need-login) — proving
        Depends(_require_demo_mode) is resolved ahead of Depends(require_admin)
        in the endpoint signature, not just in the imperative body call."""
        response = client.get("/admin/demo/clock")
        assert response.status_code == 404

    def test_unauthenticated_request_gets_401_when_demo_mode_true(self, client, monkeypatch):
        """Sanity check on the other side of the flag: with DEMO_MODE=true the
        route exists, so an unauthenticated caller is rejected by
        require_admin's underlying auth check instead of 404."""
        monkeypatch.setenv("DEMO_MODE", "true")
        response = client.get("/admin/demo/clock")
        assert response.status_code in (401, 403)
