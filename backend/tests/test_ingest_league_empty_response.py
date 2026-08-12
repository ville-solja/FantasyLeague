"""Regression tests: ingest_league() must not crash when OpenDota returns nothing
for a league with no matches yet (or a transient fetch failure), and any remaining
unhandled exception must still produce parseable JSON, not Starlette's plain-text
500 body (which broke the frontend's res.json() call — reported as
'Unexpected token \'I\', "Internal S"... is not valid JSON')."""

import asyncio
import json

import pytest

import ingest as ingest_module


class TestIngestLeagueHandlesEmptyOpenDotaResponses:
    def test_ingest_league_does_not_raise_when_no_matches_found(self, db, monkeypatch):
        """get_league_matches() returning None (nothing to ingest yet) must not crash."""
        monkeypatch.setattr(ingest_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(ingest_module, "get_league_info", lambda league_id: {"name": "New League"})
        monkeypatch.setattr(ingest_module, "get_league_matches", lambda league_id: None)
        monkeypatch.setattr(ingest_module, "ensure_dotabuff_league_logos", lambda: None)

        ingest_module.ingest_league(99999)  # must not raise

    def test_ingest_league_does_not_raise_when_league_info_missing(self, db, monkeypatch):
        """get_league_info() returning None (league not yet indexed by OpenDota) must not crash."""
        monkeypatch.setattr(ingest_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(ingest_module, "get_league_info", lambda league_id: None)
        monkeypatch.setattr(ingest_module, "get_league_matches", lambda league_id: [])
        monkeypatch.setattr(ingest_module, "ensure_dotabuff_league_logos", lambda: None)

        ingest_module.ingest_league(99999)  # must not raise

    def test_ingest_league_creates_league_row_with_unknown_name_when_info_missing(self, db, monkeypatch):
        from models import League

        monkeypatch.setattr(ingest_module, "SessionLocal", lambda: db)
        monkeypatch.setattr(ingest_module, "get_league_info", lambda league_id: None)
        monkeypatch.setattr(ingest_module, "get_league_matches", lambda league_id: None)
        monkeypatch.setattr(ingest_module, "ensure_dotabuff_league_logos", lambda: None)

        ingest_module.ingest_league(55555)

        league = db.query(League).filter_by(id=55555).first()
        assert league is not None
        assert league.name == "unknown"


class TestUnhandledExceptionHandlerReturnsJson:
    def test_unhandled_exception_handler_returns_parseable_json_500(self):
        import main

        class FakeURL:
            path = "/ingest/league/12345"

        class FakeRequest:
            method = "POST"
            url = FakeURL()

        response = asyncio.run(
            main._unhandled_exception_handler(FakeRequest(), TypeError("simulated crash"))
        )

        assert response.status_code == 500
        body = json.loads(response.body)
        assert body == {"detail": "Internal server error"}
