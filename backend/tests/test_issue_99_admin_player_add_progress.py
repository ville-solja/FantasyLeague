"""
Tests for the Admin Player Add Progress plan (GitHub issue #99).

Story: Live Progress for Bulk Player Add
Story: Endpoint Streams Per-ID Results
Story: Add Player Button Shows Pending State

These exercise the streaming bulk-add endpoint (`POST /admin/players/bulk`)
and the unchanged single-add endpoint (`POST /admin/players`) via
extracted/replicated helper functions, following the pattern used in
test_admin_player_pool.py (FastAPI is not importable in the local test
environment, so endpoint logic is tested via helpers rather than a live
TestClient).
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Player, AuditLog


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Helpers: replicate the business logic of the admin endpoints
# ---------------------------------------------------------------------------

def _bulk_add_players_stream(db, csv_str, admin_user_id=1, admin_username="admin"):
    """Replicates `_bulk_add_stream` in backend/routers/admin_players.py:
    a generator that yields one dict per input ID (the NDJSON line shape,
    pre-serialization) followed by a final summary dict, using mocked
    `requests.get` for OpenDota lookups. Each successful add is committed
    immediately (not batched to the end) so a caller that stops draining the
    generator partway (simulating a client disconnect) still keeps whatever
    was already added."""
    import requests as req
    raw_ids = [s.strip() for s in csv_str.split(",") if s.strip()]
    added, skipped = [], []
    total = len(raw_ids)
    for i, raw in enumerate(raw_ids, start=1):
        try:
            pid = int(raw)
        except ValueError:
            skipped.append({"id": raw, "reason": "not an integer"})
            yield {"id": raw, "status": "error", "reason": "not an integer",
                   "index": i, "total": total}
            continue
        if db.get(Player, pid):
            skipped.append({"id": pid, "reason": "already exists"})
            yield {"id": pid, "status": "skipped", "reason": "already exists",
                   "index": i, "total": total}
            continue
        resp = req.get(f"https://api.opendota.com/api/players/{pid}", timeout=10)
        if resp.status_code != 200 or not resp.json().get("profile"):
            skipped.append({"id": pid, "reason": "not found on OpenDota"})
            yield {"id": pid, "status": "error", "reason": "not found on OpenDota",
                   "index": i, "total": total}
            continue
        data = resp.json()["profile"]
        db.add(Player(
            id=pid,
            name=data.get("personaname", str(pid)),
            avatar_url=data.get("avatarfull", ""),
            is_active=True,
        ))
        db.commit()
        added.append(pid)
        yield {"id": pid, "status": "added", "index": i, "total": total}

    if added:
        db.add(AuditLog(
            timestamp=0,
            actor_id=admin_user_id,
            actor_username=admin_username,
            action="admin_player_bulk_added",
            detail=f"added={len(added)}",
        ))
        db.commit()
    yield {"done": True, "added": len(added), "skipped": skipped}


def _add_player(db, player_id, admin_user_id=1):
    """Replicates `add_player` in backend/routers/admin_players.py.
    Returns (dict, status_code)."""
    existing = db.get(Player, player_id)
    if existing and existing.is_active:
        return {"detail": "Player already exists in pool"}, 409
    import requests as req
    resp = req.get(f"https://api.opendota.com/api/players/{player_id}", timeout=10)
    if resp.status_code != 200 or not resp.json().get("profile"):
        return {"detail": "Player not found on OpenDota"}, 422
    data = resp.json()["profile"]
    p = Player(
        id=player_id,
        name=data.get("personaname", str(player_id)),
        avatar_url=data.get("avatarfull", ""),
        is_active=True,
    )
    db.add(p)
    db.add(AuditLog(
        timestamp=0,
        actor_id=admin_user_id,
        actor_username="admin",
        action="admin_player_added",
        detail=f"player_id={player_id}",
    ))
    db.commit()
    return {"id": p.id, "name": p.name}, 200


def _make_opendota_mock(player_id, personaname="Test Player"):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "profile": {
            "personaname": personaname,
            "avatarfull": "https://example.com/avatar.jpg",
        }
    }
    return mock_resp


def _make_opendota_not_found_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {}  # no "profile" key
    return mock_resp


class TestAdminPlayerAddProgress:

    # -----------------------------------------------------------------------
    # Story: Live Progress for Bulk Player Add
    # -----------------------------------------------------------------------

    def test_bulk_add_stream_yields_events_in_order_with_running_counter(self, db):
        """Bulk add stream yields one progress event per submitted ID in
        submission order, each carrying an incrementing index and a constant
        total, driving the 'X of N processed' counter as the panel updates
        incrementally rather than all at once."""
        def mock_get(url, timeout=10):
            for pid, name in ((2001, "Alpha"), (2002, "Beta"), (2003, "Gamma")):
                if str(pid) in url:
                    return _make_opendota_mock(pid, name)
            return _make_opendota_not_found_mock()

        csv = "2001,2002,2003"
        with patch("requests.get", side_effect=mock_get):
            events = list(_bulk_add_players_stream(db, csv))

        per_id_events = [e for e in events if "done" not in e]
        summary = events[-1]

        assert len(per_id_events) == 3
        # submission order preserved
        assert [e["id"] for e in per_id_events] == [2001, 2002, 2003]
        # incrementing index, constant total, driving the running counter
        assert [e["index"] for e in per_id_events] == [1, 2, 3]
        assert all(e["total"] == 3 for e in per_id_events)
        assert all(e["status"] == "added" for e in per_id_events)

        assert summary == {"done": True, "added": 3, "skipped": []}

    def test_bulk_add_stream_continues_processing_after_opendota_failure(self, db):
        """When OpenDota throttles or errors on one ID mid-batch, that ID's
        event reports a failed status with the error reason shown, and the
        stream continues yielding events for the remaining IDs instead of
        aborting the batch."""
        def mock_get(url, timeout=10):
            if "3002" in url:
                return _make_opendota_not_found_mock()  # simulates throttle/error
            for pid, name in ((3001, "First"), (3003, "Third")):
                if str(pid) in url:
                    return _make_opendota_mock(pid, name)
            return _make_opendota_not_found_mock()

        csv = "3001,3002,3003"
        with patch("requests.get", side_effect=mock_get):
            events = list(_bulk_add_players_stream(db, csv))

        per_id_events = [e for e in events if "done" not in e]
        assert len(per_id_events) == 3  # all three IDs still processed

        failed = next(e for e in per_id_events if e["id"] == 3002)
        assert failed["status"] == "error"
        assert failed["reason"] == "not found on OpenDota"

        # processing continued past the failure
        assert per_id_events[0]["id"] == 3001 and per_id_events[0]["status"] == "added"
        assert per_id_events[2]["id"] == 3003 and per_id_events[2]["status"] == "added"

        summary = events[-1]
        assert summary["added"] == 2
        assert 3002 in [s["id"] for s in summary["skipped"]]

    def test_bulk_add_stream_commits_each_added_player_immediately(self, db):
        """If the client disconnects mid-batch (e.g. the admin closes the
        browser tab), Starlette stops draining the generator after whatever
        ID was in flight finishes — it never reaches the end of the loop.
        Because each successful add is committed immediately rather than
        batched to a single commit at the end, players already reported as
        'added' before the disconnect stay persisted even though the
        generator is abandoned before its final commit."""
        def mock_get(url, timeout=10):
            for pid, name in ((7001, "First"), (7002, "Second"), (7003, "Third")):
                if str(pid) in url:
                    return _make_opendota_mock(pid, name)
            return _make_opendota_not_found_mock()

        csv = "7001,7002,7003"
        with patch("requests.get", side_effect=mock_get):
            gen = _bulk_add_players_stream(db, csv)
            next(gen)  # 7001 added + committed
            next(gen)  # 7002 added + committed
            # Simulate an abandoned stream: the generator is never drained to
            # completion, so its final commit (and the audit log write) is
            # never reached — matching what happens on a real disconnect.

        assert db.get(Player, 7001) is not None
        assert db.get(Player, 7002) is not None
        assert db.get(Player, 7003) is None  # never processed

        # the batch-level audit event requires the generator to finish
        audit_rows = db.query(AuditLog).filter(
            AuditLog.action == "admin_player_bulk_added"
        ).all()
        assert len(audit_rows) == 0

    # -----------------------------------------------------------------------
    # Story: Endpoint Streams Per-ID Results
    # -----------------------------------------------------------------------

    def test_bulk_add_players_stream_shape_matches_ndjson_contract_and_final_summary(self, db):
        """POST /admin/players/bulk streams one newline-delimited JSON line
        per input ID (id, status of added/skipped/error, and a reason for any
        non-added outcome) followed by a final summary line preserving the
        pre-existing {"added": N, "skipped": [...]} shape, with
        admin_player_bulk_added recorded exactly once per batch."""
        # 4001 will be pre-existing (skipped), 4002 valid (added)
        db.add(Player(id=4001, name="Existing", avatar_url="", is_active=True))
        db.commit()

        def mock_get(url, timeout=10):
            if "4002" in url:
                return _make_opendota_mock(4002, "New Player")
            return _make_opendota_not_found_mock()

        csv = "4001,4002"
        with patch("requests.get", side_effect=mock_get):
            events = list(_bulk_add_players_stream(db, csv))

        per_id_events = [e for e in events if "done" not in e]
        assert len(per_id_events) == 2

        skipped_evt = next(e for e in per_id_events if e["id"] == 4001)
        assert skipped_evt["status"] == "skipped"
        assert skipped_evt["reason"] == "already exists"

        added_evt = next(e for e in per_id_events if e["id"] == 4002)
        assert added_evt["status"] == "added"
        assert "reason" not in added_evt

        summary = events[-1]
        assert summary["done"] is True
        assert summary["added"] == 1
        assert summary["skipped"] == [{"id": 4001, "reason": "already exists"}]

        # audit event recorded exactly once per batch, not once per ID
        audit_rows = db.query(AuditLog).filter(
            AuditLog.action == "admin_player_bulk_added"
        ).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].detail == "added=1"

    def test_bulk_add_players_stream_invalid_integer_reported_as_error_line(self, db):
        """A non-integer entry in the bulk-add CSV is streamed as an
        error-status line with reason 'not an integer' rather than raising,
        is excluded from the added count, and does not stop the rest of the
        batch from processing (existing invalid-integer handling unchanged)."""
        def mock_get(url, timeout=10):
            if "5002" in url:
                return _make_opendota_mock(5002, "Valid Player")
            return _make_opendota_not_found_mock()

        csv = "notanint,5002"
        with patch("requests.get", side_effect=mock_get):
            events = list(_bulk_add_players_stream(db, csv))

        per_id_events = [e for e in events if "done" not in e]
        assert len(per_id_events) == 2  # both entries processed, no exception raised

        invalid_evt = per_id_events[0]
        assert invalid_evt["id"] == "notanint"
        assert invalid_evt["status"] == "error"
        assert invalid_evt["reason"] == "not an integer"

        # rest of the batch still processed after the invalid entry
        valid_evt = per_id_events[1]
        assert valid_evt["id"] == 5002
        assert valid_evt["status"] == "added"

        summary = events[-1]
        assert summary["added"] == 1
        assert "notanint" in [s["id"] for s in summary["skipped"]]

    # -----------------------------------------------------------------------
    # Story: Add Player Button Shows Pending State
    # -----------------------------------------------------------------------

    def test_add_player_response_contract_unchanged_for_pending_state_ui(self, db):
        """POST /admin/players with a valid new OpenDota ID still returns the
        existing 200 {id, name} contract, unaffected by the bulk-add
        streaming change, so the frontend's pending-state button toggle can
        rely on the response resolving exactly as before."""
        mock_resp = _make_opendota_mock(6001, "Pending Player")

        with patch("requests.get", return_value=mock_resp):
            result, status = _add_player(db, player_id=6001)

        assert status == 200
        assert set(result.keys()) == {"id", "name"}
        assert result["id"] == 6001
        assert result["name"] == "Pending Player"

        persisted = db.get(Player, 6001)
        assert persisted is not None
        assert persisted.is_active is True

    def test_add_player_error_response_contract_unchanged_for_pending_state_ui(self, db):
        """POST /admin/players with an OpenDota ID that fails validation
        still returns the existing 422 error/detail shape unchanged, so the
        frontend can safely re-enable the Confirm/Close controls after an
        error without a new response shape to handle."""
        mock_resp = _make_opendota_not_found_mock()

        with patch("requests.get", return_value=mock_resp):
            result, status = _add_player(db, player_id=6002)

        assert status == 422
        assert set(result.keys()) == {"detail"}
        assert result["detail"] == "Player not found on OpenDota"

        count = db.query(Player).filter(Player.id == 6002).count()
        assert count == 0
