"""Tests for OpenDota Query Prioritization
(plan-issue-109-opendota-query-prioritization.md).

Resolves GitHub issue #109. Covers the three user stories in that plan:
  - Defer Low-Priority Enrichment While a Monitored Match Is Live
  - Poll Faster While a Monitored Match Is Live
  - Operator Visibility into Prioritization State

Since issue #161 live games come from Steam (`steam_live.get_live_league_games`), checked
by the separate `main._live_poll_loop` thread and stored in `live_matches`; OpenDota's
`GET /live` is no longer called. `_ingest_poll_loop` makes no live calls: it reads the
monitored leagues with a live match from `live_matches` (`main._live_league_ids`: not
ended, seen in the last 15 minutes).

`backend/main.py`'s `_auto_ingest`/`_ingest_poll_loop` check live-match state once per poll
cycle against the monitored league IDs: while any monitored league is live,
`run_enrichment()` is skipped for that cycle (ingestion itself is never paused) and the
loop selects the tighter `INGEST_LIVE_MATCH_POLL_INTERVAL` instead of the existing
`INGEST_LIVE_POLL_INTERVAL`/`INGEST_POLL_INTERVAL` tiers. A failure reading the live state
degrades to an empty live set rather than crash the loop, falling back to the normal
interval selection; a failed Steam request returns None and changes nothing.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import time

import pytest

# Registers every table (including live_matches) before the conftest db fixture runs.
import models  # noqa: F401


class _OneShotEvent:
    """Stand-in for main._stop_event: lets a background-loop function run exactly
    one iteration under test, then reports what timeout it waited with."""

    def __init__(self):
        self._flag = False
        self.wait_calls = []

    def is_set(self):
        return self._flag

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self._flag = True


# ===========================================================================
# Story: Defer Low-Priority Enrichment While a Monitored Match Is Live
# ===========================================================================

class TestDeferLowPriorityEnrichmentWhileMonitoredMatchLive:

    def test_auto_ingest_skips_enrichment_when_league_has_live_match(self, monkeypatch):
        """AC: while a monitored league has a live match (per live_matches),
        _auto_ingest() skips run_enrichment() for that cycle but still ingests new match
        data for the league — only enrichment is paused, never ingestion."""
        import main

        ingested = []
        monkeypatch.setattr(main, "ingest_league", lambda league_id: ingested.append(league_id))
        monkeypatch.setattr(main, "run_enrichment", lambda: pytest.fail("enrichment must be skipped for a live league"))

        main._auto_ingest([123], {123})

        assert ingested == [123]

    def test_get_live_league_games_returns_none_when_steam_call_fails(self, monkeypatch):
        """AC failure path (since #161 the live source is Steam): when the live request
        fails, steam_live.get_live_league_games() must not raise — it returns None, the
        stored live matches stay as they are and the enrichment gate is unaffected."""
        import requests
        import steam_live

        monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")

        def _fail(*args, **kwargs):
            raise requests.ConnectionError("simulated Steam failure")
        monkeypatch.setattr(steam_live.requests, "get", _fail)

        assert steam_live.get_live_league_games([123]) is None


# ===========================================================================
# Story: Poll Faster While a Monitored Match Is Live
# ===========================================================================

class TestPollFasterWhileMonitoredMatchLive:

    def test_ingest_poll_loop_selects_live_match_interval_when_league_live(self, db, monkeypatch):
        """AC: while a monitored league has a live match in progress (a fresh, unended
        live_matches row), _ingest_poll_loop() waits INGEST_LIVE_MATCH_POLL_INTERVAL instead
        of the existing active-week (INGEST_LIVE_POLL_INTERVAL) or default
        (INGEST_POLL_INTERVAL) interval."""
        import main
        from models import LiveMatch

        now = int(time.time())
        db.add(LiveMatch(match_id=1, league_id=123, players_json="[]",
                         first_seen_at=now - 120, last_seen_at=now - 30, ended_at=None))
        db.commit()
        monkeypatch.setattr(main, "SessionLocal", lambda: db)
        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [123])
        auto_ingest_calls = []
        monkeypatch.setattr(main, "_auto_ingest", lambda league_ids, live: auto_ingest_calls.append(live))
        monkeypatch.setattr(main, "_run_toornament_sync", lambda: None)
        monkeypatch.setattr(main, "_has_active_week", lambda: pytest.fail("active-week check should not be reached when a match is live"))

        fake_event = _OneShotEvent()
        monkeypatch.setattr(main, "_stop_event", fake_event)

        main._ingest_poll_loop()

        assert auto_ingest_calls == [{123}]
        assert fake_event.wait_calls == [main._INGEST_LIVE_MATCH_POLL_INTERVAL]

    def test_ingest_poll_loop_falls_back_to_normal_interval_selection_when_live_check_fails(self, monkeypatch):
        """AC failure path: when reading the live-match state raises inside a poll cycle,
        _ingest_poll_loop() does not crash — it treats no league as live (ingest and
        enrichment still run) and falls back to the active-week/default interval selection."""
        import main

        monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [123])

        def _raise_live_check(league_ids):
            raise RuntimeError("simulated live_matches read failure")
        monkeypatch.setattr(main, "_live_league_ids", _raise_live_check)
        monkeypatch.setattr(main, "_has_recently_ended_live_match", lambda league_ids: False)
        monkeypatch.setattr(main, "_has_active_week", lambda: False)

        auto_ingest_calls = []
        monkeypatch.setattr(main, "_auto_ingest", lambda league_ids, live: auto_ingest_calls.append((league_ids, live)))
        monkeypatch.setattr(main, "_run_toornament_sync", lambda: None)

        fake_event = _OneShotEvent()
        monkeypatch.setattr(main, "_stop_event", fake_event)

        main._ingest_poll_loop()  # must not raise

        assert auto_ingest_calls == [([123], set())]
        assert fake_event.wait_calls == [main._INGEST_POLL_INTERVAL]


# ===========================================================================
# Story: Operator Visibility into Prioritization State
# ===========================================================================

class TestOperatorVisibilityIntoPrioritizationState:

    def test_auto_ingest_logs_reason_when_enrichment_skipped_for_live_league(self, monkeypatch, caplog):
        """AC: a log line clearly states that enrichment was skipped for a cycle because a
        monitored league has a live match, naming the league so an operator mid-event can
        confirm the gate fired instead of guessing from ingest duration alone."""
        import main

        monkeypatch.setattr(main, "ingest_league", lambda league_id: None)
        monkeypatch.setattr(main, "run_enrichment", lambda: pytest.fail("enrichment must be skipped for a live league"))

        with caplog.at_level(logging.INFO, logger="main"):
            main._auto_ingest([123], {123})

        messages = [r.message for r in caplog.records]
        assert any("123" in m and "live match" in m and "skipping enrichment" in m for m in messages), messages

    def test_auto_ingest_logs_when_enrichment_resumes_after_no_league_is_live(self, monkeypatch, caplog):
        """AC failure/complementary path: once no monitored league has a live match, a log
        line confirms enrichment resumes on its normal cadence rather than the prior skip
        state persisting silently or ambiguously."""
        import main

        monkeypatch.setattr(main, "ingest_league", lambda league_id: None)
        enrich_calls = []
        monkeypatch.setattr(main, "run_enrichment", lambda: enrich_calls.append(True))

        with caplog.at_level(logging.INFO, logger="main"):
            main._auto_ingest([123], set())

        assert enrich_calls == [True]
        messages = [r.message for r in caplog.records]
        assert any("123" in m and "no live match" in m and "running enrichment" in m for m in messages), messages
