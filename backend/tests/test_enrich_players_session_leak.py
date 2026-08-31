"""Regression test: enrich.enrich_players() must close its DB session even when an exception
is raised partway through the function body — the whole body is wrapped in try/finally, not
just guarded at the normal-exit points. Without this, an exception during the query or the
per-player loop leaks the session, exactly like the sibling bug fixed earlier in
run_profile_enrichment() (see markdown/lessons-learned.md).

enrich_players() opens its own session via SessionLocal() rather than accepting a `db` param,
so SessionLocal is monkeypatched to return the in-memory test session (same technique used for
seed_admin_from_env() — see markdown/lessons-learned.md)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import enrich


class TestEnrichPlayersSessionLeak:
    def test_session_closed_normally_when_no_players_need_enrichment(self, db, monkeypatch):
        monkeypatch.setattr(enrich, "SessionLocal", lambda: db)
        close_calls = []
        monkeypatch.setattr(db, "close", lambda: close_calls.append(True))

        result = enrich.enrich_players()

        assert result == 0
        assert close_calls == [True]

    def test_session_closed_even_if_query_raises(self, db, monkeypatch):
        """The core regression case: an exception before any normal-exit `return` must still
        close the session, via the enclosing try/finally rather than an inline db.close()."""
        monkeypatch.setattr(enrich, "SessionLocal", lambda: db)
        close_calls = []
        monkeypatch.setattr(db, "close", lambda: close_calls.append(True))

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(db, "query", _raise)

        with pytest.raises(RuntimeError):
            enrich.enrich_players()

        assert close_calls == [True]
