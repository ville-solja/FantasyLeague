"""
Tests for plan-issue-156-schedule-visuals.md (resolves GitHub issue #156).

The Schedule tab is rebuilt around "where are we now": a "Right now" strip (Live now,
Next up, Latest result), a week strip over a single-week view in time order with a
"Now" line, and a spoiler-free hide mode (ON by default) with per-series and per-week
reveals. Weeks revealed in the Weekly Report count as revealed on the Schedule.

Backend: `backend/schedule.py` gains `LIVE_FRESH_SECONDS = 15 * 60`,
`get_live_pairs(db, now)` and `get_fantasy_weeks(db)`. `GET /schedule` (and
`POST /schedule/refresh`) in `backend/routers/admin_ingest.py` return a shallow copy
of the cached `get_schedule(db)` dict decorated with `live` and `fantasy_weeks`, so
the cache entry itself is never changed.

Frontend: `frontend/app-players.js::loadSchedule` and new helpers (`seriesTime`,
`assignWeek`, `calendarWeeks`, `seriesKey`, `rowState`, ...), markup containers
`#scheduleNow`, `#scheduleWeeks`, `#scheduleContent` in `frontend/index.html`, and
styles in `frontend/style.css` (phone layout below 700 px).

Hide mode storage: `kc_schedule_hide` is "0" once the player turns hide mode off and
"1" when they turn it on; absent or unreadable counts as ON. `kc_schedule_revealed`
is a JSON array of series keys capped at 500. All storage access is inside try/catch.

  Story 1: See What's Happening Now at the Top of the Schedule  (TestRightNowStrip)
  Story 2: Browse the Season Week by Week in Time Order          (TestWeekByWeekTimeline)
  Story 3: Hide Results Until I Choose to See Them               (TestHideResults)
  Story 4: Results Already Seen in the Weekly Report Stay Revealed (TestWeeklyReportRevealLinkUp)
  Story 5: Played Results Read at a Glance                       (TestPlayedResultsAtAGlance)

Frontend behaviour is checked statically and, when `node` is available, by running
the real `loadSchedule` from app-players.js under Node against a fake DOM, fetch and
localStorage (`_run_schedule`), in Europe/Helsinki time. Without Node only the static
checks run (no skip, so the #85 suite-size tripwire stays exact).

Manual-only (see the plan's Verification section): visual layout at 390 px, live row
appearing without waiting for cache expiry in a real browser, blocked site storage in
a real browser.

Run with: cd backend && python3 -m pytest tests/test_issue_156_schedule_visuals.py -v
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401  (register every table before the db fixture runs)
import schedule
from models import LiveMatch, Week
from tests.test_issue_151_weekly_report_aesthetics import _css_blocks, _fn_body, _media_body, _read
from tests.test_issue_159_flicker_free_tab_switching import _node

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_APP_PLAYERS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-players.js")
_APP_GLOBALS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-globals.js")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
_STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")
_ADMIN_INGEST_PATH = os.path.join(os.path.dirname(__file__), "..", "routers", "admin_ingest.py")

_TZ = ZoneInfo("Europe/Helsinki")


def _ts(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=_TZ).timestamp())


def _iso(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi).isoformat()


def _js():
    return _read(_APP_PLAYERS_JS_PATH)


def _load_schedule():
    return _fn_body(_js(), "loadSchedule")


def _nested(body, name):
    """Source of a `const name = (...) => ...;` closure inside a function body,
    up to the next closure declared at the same indent."""
    m = re.search(r"\n(\s*)const " + re.escape(name) + r" = ", body)
    assert m, name
    end = re.search(r"\n" + m.group(1) + r"(?:const |function |let )", body[m.end():])
    return body[m.start():m.end() + (end.start() if end else len(body))]


def _index():
    return _read(_INDEX_HTML_PATH)


def _schedule_markup():
    html = _index()
    start = html.index('<div id="tab-schedule"')
    return html[start:html.index("<!-- TAB: HOW TO PLAY -->", start)]


def _css():
    return _read(_STYLE_CSS_PATH)


def _rule(css, selector):
    """Body of the first top-level rule whose selector list contains `selector`."""
    for sel, body in _css_blocks(css, re.escape(selector)):
        if selector in [x.strip() for x in sel.split(",")]:
            return body
    raise AssertionError(f"no CSS rule for {selector}")


@pytest.fixture(autouse=True)
def _reset_schedule_cache(monkeypatch):
    monkeypatch.setattr(schedule, "SCHEDULE_SHEET_URL", "")
    monkeypatch.setattr(schedule, "SCHEDULE_FIXTURES_URL", "")
    monkeypatch.setattr(schedule, "_hero_icon_cache", {})
    schedule.bust_cache()
    yield
    schedule.bust_cache()


# ---------------------------------------------------------------------------
# Node harness: runs the real loadSchedule against fake DOM / fetch / storage
# ---------------------------------------------------------------------------

_NOW = _ts(2026, 10, 7, 18, 0)  # Wednesday of week 2

_FANTASY_WEEKS = [
    {"week_id": 1, "label": "Week 1", "start_time": _ts(2026, 9, 28), "end_time": _ts(2026, 10, 5)},
    {"week_id": 2, "label": "Week 2", "start_time": _ts(2026, 10, 5), "end_time": _ts(2026, 10, 12)},
    {"week_id": 3, "label": "Week 3", "start_time": _ts(2026, 10, 12), "end_time": _ts(2026, 10, 19)},
]


def _game(mid, k1, k2, mvp=None, excluded=False):
    return {
        "match_id": mid, "duration": 1985, "team1_kills": k1, "team2_kills": k2,
        "team1_heroes": ["https://cdn.example/h1.png", None, None, None, None],
        "team2_heroes": [None, None, None, None, None],
        "mvp_player_id": 77 if mvp else None, "mvp_player_name": mvp,
        "excluded_from_scoring": excluded,
    }


def _scenario():
    a = {  # week 1, played 2-0
        "team1": "Alpha", "team1_id": 1, "team2": "Bravo", "team2_id": 2,
        "datetime_iso": _iso(2026, 9, 30, 19), "time": "19:00", "match_status": "past",
        "stream_url": "https://twitch.tv/vod", "stream_label": None,
        "series_result": {"team1_wins": 2, "team2_wins": 0, "game_count": 2,
                          "start_time": _ts(2026, 9, 30, 19, 5), "match_ids": [102, 101],
                          "games": [_game(101, 30, 10, mvp="StarGuy"), _game(102, 25, 12)]},
    }
    b = {  # week 2 (Monday), played 1-2, one game not scored
        "team1": "Charlie", "team1_id": 3, "team2": "Delta", "team2_id": 4,
        "datetime_iso": _iso(2026, 10, 5, 19), "time": "19:00", "match_status": "past",
        "stream_url": None, "stream_label": None,
        "series_result": {"team1_wins": 1, "team2_wins": 2, "game_count": 3,
                          "start_time": _ts(2026, 10, 5, 19, 10), "match_ids": [201, 202, 203],
                          "games": [_game(201, 11, 22, mvp="KillerQueen"), _game(202, 9, 8, excluded=True),
                                    _game(203, 5, 40)]},
    }
    c = {  # week 2, live now (planned time passed, no result yet)
        "team1": "Alpha", "team1_id": 1, "team2": "Charlie", "team2_id": 3,
        "datetime_iso": _iso(2026, 10, 7, 17, 30), "time": "17:30", "match_status": "past",
        "stream_url": "https://twitch.tv/live", "stream_label": "Kanaliiga", "series_result": None,
    }
    d = {  # week 2, next up
        "team1": "Bravo", "team1_id": 2, "team2": "Delta", "team2_id": 4,
        "datetime_iso": _iso(2026, 10, 8, 19), "time": "19:00", "match_status": "upcoming",
        "stream_url": "https://twitch.tv/next", "stream_label": "Main", "series_result": None,
    }
    e = {  # week 2, Time TBD (feed fallback: Monday 00:00)
        "team1": "Echo", "team1_id": 5, "team2": "Foxtrot", "team2_id": 6,
        "datetime_iso": _iso(2026, 10, 5), "time": None, "match_status": "past",
        "scheduled": False, "stream_url": None, "stream_label": None, "series_result": None,
    }
    f = {  # week 3, upcoming
        "team1": "Charlie", "team1_id": 3, "team2": "Bravo", "team2_id": 2,
        "datetime_iso": _iso(2026, 10, 13, 19), "time": "19:00", "match_status": "upcoming",
        "stream_url": None, "stream_label": None, "series_result": None,
    }
    x = {  # DB-derived result before every fantasy week
        "team1": "Golf", "team1_id": 7, "team2": "Hotel", "team2_id": 8, "division": None,
        "datetime_iso": _iso(2026, 9, 20, 18), "match_status": "past",
        "series_result": {"team1_wins": 1, "team2_wins": 0, "game_count": 1,
                          "start_time": _ts(2026, 9, 20, 18), "match_ids": [50],
                          "games": [_game(50, 20, 3)]},
    }
    return {
        "weeks": [
            {"label": "Week 1", "div1": [a], "div2": []},
            {"label": "Week 2", "div1": [c, d], "div2": [b, e]},
            {"label": "Week 3", "div1": [], "div2": [f]},
        ],
        "extra_results": [x],
        "cached_at": "2026-10-07T17:00:00", "stale": False, "error": None, "source": "fixtures_json",
        "live": [{"team_ids": [1, 3], "started_at": _ts(2026, 10, 7, 17, 35)}],
        "fantasy_weeks": _FANTASY_WEEKS,
    }


_HARNESS = r"""
const NOW_MS = %(now)d * 1000;
Date.now = () => NOW_MS;
const DATA = %(data)s;
let SUMMARY = %(summary)s;
const STORAGE_MODE = %(storage)s;
const store = Object.assign({}, %(store)s);
const fetchLog = [];
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: "", textContent: "", className: "", style: {}, attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  return els[id];
}
globalThis.document = { getElementById: el, querySelectorAll: () => [] };
globalThis.localStorage = {
  getItem(k) { if (STORAGE_MODE === "blocked") throw new Error("blocked"); return k in store ? store[k] : null; },
  setItem(k, v) { if (STORAGE_MODE === "blocked") throw new Error("blocked"); store[k] = String(v); },
};
globalThis.fetch = async (url, opts) => {
  fetchLog.push([url, (opts && opts.method) || "GET"]);
  if (url === "/weekly-summary") {
    if (SUMMARY === "fail") throw new Error("down");
    return { ok: true, json: async () => SUMMARY };
  }
  if (url === "/schedule") return { ok: true, json: async () => JSON.parse(JSON.stringify(DATA)) };
  throw new Error("unexpected fetch " + url);
};
const API = "";
let activeUsername = %(username)s;
function setStatus(id, msg) { el(id).textContent = msg; }
%(globals)s
%(players)s
function snap() {
  return {
    content: el("scheduleContent").innerHTML,
    now: el("scheduleNow").innerHTML,
    nowDisplay: el("scheduleNow").style.display,
    weeks: el("scheduleWeeks").innerHTML,
    toggleLabel: el("scheduleHideToggle").textContent,
    togglePressed: el("scheduleHideToggle").attrs["aria-pressed"],
    status: el("scheduleStatus").textContent,
    store: Object.assign({}, store),
    fetches: fetchLog.slice(),
  };
}
const id = key => _schedKeyId(key);
(async () => {
  const out = {};
%(steps)s
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _globals_helpers():
    js = _read(_APP_GLOBALS_JS_PATH)
    decl = re.search(r"^const _lastHtml = new WeakMap\(\);$", js, re.M).group(0)
    parts = [decl] + [_fn_body(js, n) + "\n}\n" for n in ("renderIfChanged", "_escHtml", "_safeUrl", "playerLink", "teamLink")]
    return "\n".join(parts)


def _run_schedule(steps, data=None, summary=None, username=None, storage="ok", store=None):
    """Runs `steps` (JS inside an async function with `out`, `snap()`, `id(key)`,
    `loadSchedule` and the Schedule handlers in scope); returns `out`, or None
    when Node is not installed."""
    node = _node()
    if not node:
        return None
    script = _HARNESS % {
        "now": _NOW,
        "data": json.dumps(data if data is not None else _scenario()),
        "summary": json.dumps(summary if summary is not None else {"weeks": []}),
        "storage": json.dumps(storage),
        "store": json.dumps(store or {}),
        "username": json.dumps(username),
        "globals": _globals_helpers(),
        "players": _js(),
        "steps": steps,
    }
    env = dict(os.environ, TZ="Europe/Helsinki")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, env=env)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout)


def _row(html, team1, team2):
    """Markup of the series row naming team1 then team2, plus its folded games (if any)."""
    rows = re.split(r'(?=<div class="series-row)|(?=<div class="schedule-day")|(?=<div class="schedule-now-line")', html)
    for r in rows:
        if r.startswith('<div class="series-row') and team1 in r and team2 in r and r.index(team1) < r.index(team2):
            return r
    raise AssertionError(f"no row {team1} vs {team2}")


def _now_card(html, kind):
    m = re.search(r'<div class="now-card ' + kind + r'">(.*?)(?=<div class="now-card |\Z)', html, re.S)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def _live(db, match_id, radiant, dire, first, last, ended=None):
    db.add(LiveMatch(match_id=match_id, league_id=1, radiant_team_id=radiant, dire_team_id=dire,
                     players_json="[]", first_seen_at=first, last_seen_at=last, ended_at=ended))
    db.commit()


def _schedule_get(db):
    from routers.admin_ingest import schedule_endpoint
    return schedule_endpoint(db=db)


# ---------------------------------------------------------------------------
# Story 1: See What's Happening Now at the Top of the Schedule
# ---------------------------------------------------------------------------

class TestRightNowStrip:

    def test_get_live_pairs_returns_fresh_unended_live_match(self, db):
        """Live state comes from live_matches rows with ended_at empty and last_seen_at within LIVE_FRESH_SECONDS (15 min); each entry has `team_ids` and `started_at` (= first_seen_at)."""
        assert schedule.LIVE_FRESH_SECONDS == 15 * 60
        now = 1_800_000_000
        _live(db, 1, 10, 20, first=now - 1200, last=now - 60)
        _live(db, 2, 30, 40, first=now - 3000, last=now - schedule.LIVE_FRESH_SECONDS)  # boundary: still fresh
        pairs = schedule.get_live_pairs(db, now)
        assert {"team_ids": [10, 20], "started_at": now - 1200} in pairs
        assert {"team_ids": [30, 40], "started_at": now - 3000} in pairs
        assert len(pairs) == 2

    def test_get_live_pairs_team_ids_sorted_either_side(self, db):
        """A LiveMatch with radiant/dire in either order yields the same sorted `team_ids` pair, so a series matches regardless of side."""
        now = 1_800_000_000
        _live(db, 1, 99, 5, first=now - 100, last=now - 10)
        _live(db, 2, 5, 99, first=now - 100, last=now - 10)
        assert [p["team_ids"] for p in schedule.get_live_pairs(db, now)] == [[5, 99], [5, 99]]

    def test_get_live_pairs_excludes_ended_match(self, db):
        """Failure path: a LiveMatch with `ended_at` set is not listed."""
        now = 1_800_000_000
        _live(db, 1, 10, 20, first=now - 600, last=now - 30, ended=now - 20)
        assert schedule.get_live_pairs(db, now) == []

    def test_get_live_pairs_excludes_stale_match(self, db):
        """Failure path: a LiveMatch last seen more than 15 minutes ago is not listed."""
        now = 1_800_000_000
        _live(db, 1, 10, 20, first=now - 7200, last=now - schedule.LIVE_FRESH_SECONDS - 1)
        assert schedule.get_live_pairs(db, now) == []

    def test_get_live_pairs_excludes_rows_without_both_team_ids(self, db):
        """Failure path: a LiveMatch with a null radiant_team_id or dire_team_id is not listed."""
        now = 1_800_000_000
        _live(db, 1, None, 20, first=now - 60, last=now - 10)
        _live(db, 2, 10, None, first=now - 60, last=now - 10)
        _live(db, 3, None, None, first=now - 60, last=now - 10)
        assert schedule.get_live_pairs(db, now) == []

    def test_schedule_endpoint_includes_live_and_fantasy_weeks(self, db):
        """GET /schedule returns `live` and `fantasy_weeks` alongside `weeks` and `extra_results`."""
        import time
        now = int(time.time())
        _live(db, 1, 20, 10, first=now - 300, last=now - 30)
        db.add(Week(label="Week 1", start_time=1_000, end_time=2_000))
        db.commit()
        data = _schedule_get(db)
        for key in ("weeks", "extra_results", "live", "fantasy_weeks"):
            assert key in data, key
        assert data["live"] == [{"team_ids": [10, 20], "started_at": now - 300}]
        assert [w["label"] for w in data["fantasy_weeks"]] == ["Week 1"]

    def test_schedule_endpoint_live_not_served_from_cache(self, db):
        """Live state reflects the DB at request time: a LiveMatch inserted after a cached GET /schedule appears in the next response without busting the cache."""
        import time
        first = _schedule_get(db)
        assert first["live"] == []
        cached = schedule._cache["data"]
        assert cached is not None
        now = int(time.time())
        _live(db, 1, 1, 2, first=now - 60, last=now - 5)
        second = _schedule_get(db)
        assert schedule._cache["data"] is cached  # same cache entry, not rebuilt
        assert second["live"] == [{"team_ids": [1, 2], "started_at": now - 60}]

    def test_schedule_endpoint_does_not_mutate_cached_dict(self, db):
        """After GET /schedule, `schedule._cache["data"]` has no `live` or `fantasy_weeks` key (the router decorates a shallow copy)."""
        data = _schedule_get(db)
        cached = schedule._cache["data"]
        assert data is not cached
        assert "live" not in cached and "fantasy_weeks" not in cached
        _schedule_get(db)
        assert "live" not in schedule._cache["data"] and "fantasy_weeks" not in schedule._cache["data"]

    def test_schedule_refresh_returns_same_shape(self, db):
        """POST /schedule/refresh returns the decorated shape too (`live` and `fantasy_weeks` present)."""
        from routers.admin_ingest import schedule_refresh
        data = schedule_refresh(db=db, admin={"user_id": 1, "username": "admin"})
        assert "live" in data and "fantasy_weeks" in data
        assert "weeks" in data and "extra_results" in data
        assert "live" not in schedule._cache["data"]

    def test_schedule_endpoint_still_public(self):
        """GET /schedule has no auth dependency (no require_admin / get_current_user); the response holds only team ids and timestamps in `live`."""
        from deps import get_current_user, require_admin
        from routers import admin_ingest
        route = next(r for r in admin_ingest.router.routes
                     if r.path == "/schedule" and "GET" in r.methods)

        def calls(dep):
            yield dep.call
            for d in dep.dependencies:
                yield from calls(d)

        all_calls = set(calls(route.dependant))
        assert require_admin not in all_calls and get_current_user not in all_calls
        import inspect
        src = inspect.getsource(schedule.get_live_pairs)
        assert '"team_ids"' in src and '"started_at"' in src
        assert "players_json" not in src and "radiant_name" not in src and "dire_name" not in src

    def test_index_html_has_schedule_now_container(self):
        """index.html Schedule tab has a `#scheduleNow` container for the Right now strip above the week strip and week panel."""
        markup = _schedule_markup()
        assert 'id="scheduleNow"' in markup
        assert markup.index('id="scheduleNow"') < markup.index('id="scheduleWeeks"') < markup.index('id="scheduleContent"')

    def test_right_now_strip_renders_live_next_latest_cards(self):
        """The Right now renderer builds up to three cards: "Live now" (teams, division, start time, "Watch live" link when stream_url is known), "Next up" (planned time, relative countdown "in ...", stream link) and "Latest result"."""
        body = _load_schedule()
        strip = _nested(body, "nowStripHtml")
        for text in ('"Live now"', '"Next up"', '"Latest result"', "Watch live", "_schedCountdown(t, now)", "Started "):
            assert text in strip, text
        assert "function _schedCountdown(t, now)" in _js()
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
  out.cd = [_schedCountdown(1000 + 30, 1000), _schedCountdown(1000 + 45 * 60, 1000),
            _schedCountdown(1000 + 80 * 60, 1000), _schedCountdown(1000 + 2 * 3600, 1000),
            _schedCountdown(1000 + 2 * 86400, 1000), _schedCountdown(1000 + 30 * 3600, 1000)];
""")
        if out is None:
            return
        now = out["s"]["now"]
        assert out["s"]["nowDisplay"] == ""
        live = _now_card(now, "live")
        assert "Live now" in live and "Alpha" in live and "Charlie" in live
        assert "Div 1" in live and "Started 17:35" in live
        assert 'href="https://twitch.tv/live"' in live and "Watch live" in live
        nxt = _now_card(now, "next")
        assert "Next up" in nxt and "Bravo" in nxt and "Delta" in nxt and "19:00" in nxt
        assert "in 1 day" in nxt  # 25 h ahead
        assert 'href="https://twitch.tv/next"' in nxt and "Main" in nxt
        assert "Latest result" in _now_card(now, "latest")
        assert out["cd"] == ["starting now", "in 45 min", "in 1 h 20 min", "in 2 h", "in 2 days", "in 1 day"]

    def test_right_now_strip_omits_empty_cards_and_hides_when_all_empty(self):
        """Failure path: a card with nothing to show is left out, and when all three are empty the strip is not shown (empty markup / hidden container)."""
        body = _load_schedule()
        assert 'nowEl.style.display = nowHtml ? "" : "none";' in body
        assert 'style="display:none;"' in _schedule_markup().split('id="scheduleNow"')[1].split(">")[0]
        data = _scenario()
        data["live"] = []
        for w in data["weeks"]:
            for div in ("div1", "div2"):
                w[div] = [s for s in w[div] if s["series_result"] is None and s.get("scheduled") is not False]
                for s in w[div]:
                    s["datetime_iso"] = _iso(2026, 9, 1, 12)  # all in the past, no result
                    s["match_status"] = "past"
        data["extra_results"] = []
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""", data=data)
        if out is None:
            return
        assert out["s"]["now"] == "" and out["s"]["nowDisplay"] == "none"
        # Only one card has something to show: no live, no next, a latest result.
        data2 = _scenario()
        data2["live"] = []
        out2 = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""", data=data2)
        assert _now_card(out2["s"]["now"], "live") is None
        assert _now_card(out2["s"]["now"], "next") is not None

    def test_next_up_skips_time_tbd_series(self):
        """Next up is the earliest upcoming series with a real time after now; "Time TBD" fixtures are never chosen."""
        strip = _nested(_load_schedule(), "nowStripHtml")
        assert 's.scheduled !== false && seriesTime(s) > now' in strip
        data = _scenario()
        # A TBD fixture placed in the future must still not be Next up.
        data["weeks"][1]["div2"][1]["datetime_iso"] = _iso(2026, 10, 7, 23)
        data["weeks"][1]["div2"][1]["match_status"] = "upcoming"
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""", data=data)
        if out is None:
            return
        nxt = _now_card(out["s"]["now"], "next")
        assert "Bravo" in nxt and "Echo" not in nxt

    def test_latest_result_card_respects_hide_mode(self):
        """While its series is hidden, the Latest result card shows "Result hidden" and a Reveal button and outputs no score or MVP markup."""
        assert "Result hidden" in _nested(_load_schedule(), "nowStripHtml")
        out = _run_schedule("""
  await loadSchedule();
  out.hidden = snap();
  toggleScheduleHide();
  out.shown = snap();
""")
        if out is None:
            return
        card = _now_card(out["hidden"]["now"], "latest")
        assert "Charlie" in card and "Delta" in card
        assert "Result hidden" in card and ">Reveal</button>" in card
        assert "series-score" not in card and "1–2" not in card
        assert "KillerQueen" not in card and "★" not in card and "Games" not in card
        shown = _now_card(out["shown"]["now"], "latest")
        assert "1–2" in shown and "Result hidden" not in shown and ">Games</button>" in shown


# ---------------------------------------------------------------------------
# Story 2: Browse the Season Week by Week in Time Order
# ---------------------------------------------------------------------------

class TestWeekByWeekTimeline:

    def test_get_fantasy_weeks_ordered_by_start_time(self, db):
        """get_fantasy_weeks(db) returns `{week_id, label, start_time, end_time}` for every Week row, ordered by start_time ascending even when inserted out of order."""
        db.add(Week(label="Week 3", start_time=3_000, end_time=4_000))
        db.add(Week(label="Week 1", start_time=1_000, end_time=2_000))
        db.add(Week(label="Week 2", start_time=2_000, end_time=3_000))
        db.commit()
        weeks = schedule.get_fantasy_weeks(db)
        assert [w["label"] for w in weeks] == ["Week 1", "Week 2", "Week 3"]
        assert set(weeks[0]) == {"week_id", "label", "start_time", "end_time"}
        assert weeks[0]["start_time"] == 1_000 and weeks[0]["end_time"] == 2_000
        assert isinstance(weeks[0]["week_id"], int)

    def test_get_fantasy_weeks_empty_when_no_weeks(self, db):
        """Failure path: with no Week rows, `fantasy_weeks` is an empty list (frontend then falls back to calendar weeks)."""
        assert schedule.get_fantasy_weeks(db) == []
        assert _schedule_get(db)["fantasy_weeks"] == []

    def test_index_html_has_week_strip_and_week_panel_containers(self):
        """index.html Schedule tab has `#scheduleWeeks` (week strip) and `#scheduleContent` (week panel)."""
        markup = _schedule_markup()
        assert 'id="scheduleWeeks"' in markup and 'id="scheduleContent"' in markup
        assert 'id="scheduleStale"' in markup and 'id="scheduleStatus"' in markup

    def test_week_chips_are_buttons_with_aria_current(self):
        """Week chips are `<button>` elements showing label and start date; the current week's chip has `aria-current="date"` and a "This week" marker; played and upcoming chips get distinct classes."""
        strip = _nested(_load_schedule(), "weekStripHtml")
        assert '<button type="button" class="schedule-week-chip' in strip
        assert 'aria-current="date"' in strip and "This week" in strip
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""")
        if out is None:
            return
        chips = re.findall(r'<button type="button" class="schedule-week-chip ([^"]*)"([^>]*)>(.*?)</button>', out["s"]["weeks"], re.S)
        assert len(chips) == 3
        (c1, a1, b1), (c2, a2, b2), (c3, a3, b3) = chips
        assert c1.startswith("played") and c3.startswith("upcoming") and c2.startswith("current")
        assert 'aria-current="date"' in a2 and "aria-current" not in a1 + a3
        assert "W2" in b2 and "5.10." in b2 and "This week" in b2
        assert "W1" in b1 and "28.9." in b1 and "This week" not in b1

    def test_week_navigation_arrows_and_this_week_button(self):
        """Previous/next arrows are `<button aria-label=...>` elements, chip clicks select a week, and a "This week" button returns to the current week; the selected week lives in a module variable so a quiet refresh keeps it."""
        js = _js()
        strip = _nested(_load_schedule(), "weekStripHtml")
        assert 'aria-label="Previous week"' in strip and 'aria-label="Next week"' in strip
        assert 'onclick="scheduleThisWeek()"' in strip and 'onclick="selectScheduleWeek(${i})"' in strip
        assert re.search(r"^let _schedWeekKey = null;", js, re.M)
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(0);
  out.w1 = snap();
  await loadSchedule();
  out.refreshed = snap();
  scheduleThisWeek();
  out.back = snap();
""")
        if out is None:
            return
        assert ">Week 1</h3>" in out["w1"]["content"]
        assert ">Week 1</h3>" in out["refreshed"]["content"]  # quiet refresh keeps the place
        assert ">Week 2</h3>" in out["back"]["content"]
        assert 'aria-label="Previous week" data-focus="week-prev" onclick="selectScheduleWeek(-1)" disabled' in out["w1"]["weeks"]

    def test_current_week_selection_rules(self):
        """The tab opens on the week containing now; between weeks on the next to start; after the season on the last week."""
        assert "function currentWeekIndex(weeks, now)" in _js()
        out = _run_schedule("""
  const W = [{start_time: 100, end_time: 200}, {start_time: 300, end_time: 400}, {start_time: 400, end_time: 500}];
  out.r = [currentWeekIndex(W, 150), currentWeekIndex(W, 250), currentWeekIndex(W, 50),
           currentWeekIndex(W, 400), currentWeekIndex(W, 999), currentWeekIndex([], 1)];
  await loadSchedule();
  out.s = snap();
""")
        if out is None:
            return
        assert out["r"] == [0, 1, 0, 2, 2, -1]
        assert ">Week 2</h3>" in out["s"]["content"]

    def test_series_time_uses_actual_start_when_played(self):
        """seriesTime(s) is `series_result.start_time` when played, else `Date.parse(datetime_iso)/1000`."""
        body = _fn_body(_js(), "seriesTime")
        assert "r.start_time" in body and "Date.parse(" in body
        out = _run_schedule("""
  out.r = [seriesTime({datetime_iso: "2026-10-05T19:00:00", series_result: {start_time: 123}}),
           seriesTime({datetime_iso: "2026-10-05T19:00:00", series_result: null}),
           seriesTime({datetime_iso: null})];
""")
        if out is None:
            return
        assert out["r"] == [123, _ts(2026, 10, 5, 19), None]

    def test_assign_week_places_every_series_in_exactly_one_week(self):
        """assignWeek places a series in the week where start_time <= t < end_time; feed fixtures, extra_results and "Time TBD" fixtures all land in exactly one week."""
        assert "w.start_time <= t && t < w.end_time" in _fn_body(_js(), "assignWeek")
        out = _run_schedule("""
  await loadSchedule();
  out.panels = [];
  for (let i = 0; i < 3; i++) { selectScheduleWeek(i); out.panels.push(snap().content); }
  const W = [{start_time: 100, end_time: 200}, {start_time: 200, end_time: 300}];
  const at = t => ({series_result: {start_time: t}});
  out.r = [assignWeek(at(100), W), assignWeek(at(199), W), assignWeek(at(200), W), assignWeek(at(150), [])];
""")
        if out is None:
            return
        assert out["r"] == [0, 0, 1, -1]
        teams = [("Alpha", "Bravo"), ("Charlie", "Delta"), ("Alpha", "Charlie"), ("Bravo", "Delta"),
                 ("Echo", "Foxtrot"), ("Charlie", "Bravo"), ("Golf", "Hotel")]
        for t1, t2 in teams:
            hits = 0
            for panel in out["panels"]:
                try:
                    _row(panel, t1, t2)
                    hits += 1
                except AssertionError:
                    pass
            assert hits == 1, (t1, t2)
        assert "Time TBD" in out["panels"][1]

    def test_assign_week_out_of_range_goes_to_nearest_earlier_or_first(self):
        """Failure path: a series outside every fantasy week goes to the last week starting before it, or to the first week when none is earlier, so no series disappears."""
        out = _run_schedule("""
  const W = [{start_time: 100, end_time: 200}, {start_time: 300, end_time: 400}];
  const at = t => ({series_result: {start_time: t}});
  out.r = [assignWeek(at(50), W), assignWeek(at(250), W), assignWeek(at(999), W)];
  await loadSchedule();
  selectScheduleWeek(0);
  out.w1 = snap().content;
""")
        if out is None:
            return
        assert out["r"] == [0, 0, 1]
        assert "Golf" in out["w1"]  # extra result before Week 1 lands in Week 1

    def test_calendar_weeks_fallback_monday_start(self):
        """With no fantasy weeks, calendarWeeks builds Monday-start weeks from the series' own dates, labelled by date."""
        assert "calendarWeeks(allSeries)" in _load_schedule()
        data = _scenario()
        data["fantasy_weeks"] = []
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
  out.cal = calendarWeeks([{series_result: {start_time: %d}}, {series_result: {start_time: %d}}]);
  out.panels = [];
  for (let i = 0; i < _schedWeeks.length; i++) { selectScheduleWeek(i); out.panels.push(snap().content); }
""" % (_ts(2026, 10, 7, 18), _ts(2026, 10, 13, 9)), data=data)
        if out is None:
            return
        assert [(w["start_time"], w["end_time"]) for w in out["cal"]] == [
            (_ts(2026, 10, 5), _ts(2026, 10, 12)), (_ts(2026, 10, 12), _ts(2026, 10, 19))]
        assert [w["label"] for w in out["cal"]] == ["5.10.–11.10.", "12.10.–18.10."]
        assert all(w["week_id"] is None for w in out["cal"])
        # Series span 14.9 .. 13.10: Monday 14.9 to Monday 12.10 = 5 calendar weeks.
        assert len(out["panels"]) == 5
        joined = "".join(out["panels"])
        for team in ("Golf", "Alpha", "Echo", "Charlie"):
            assert team in joined
        assert "14.9.–20.9." in out["s"]["weeks"]

    def test_week_series_grouped_by_day_sorted_ascending(self):
        """Within a week, series from both divisions are sorted by seriesTime ascending and grouped by day, labelled with an English weekday and Finnish day-month order ("Mon 5.10.2026")."""
        body = _load_schedule()
        assert "return _schedDayLabel(t, true);" in body
        assert ".sort((a, b) => seriesTime(a) - seriesTime(b))" in _nested(body, "weekPanelHtml")
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""")
        if out is None:
            return
        c = out["s"]["content"]
        days = re.findall(r'<div class="schedule-date-hd">([^<]*)</div>', c)
        assert days[0].startswith("Mon 5.10.2026") and days[1].startswith("Wed 7.10.2026") and days[2].startswith("Thu 8.10.2026")
        assert days[-1] == "Time TBD"
        assert c.index("Delta") < c.index("Alpha") < c.index(">Bravo") < c.index("Echo")

    def test_now_line_inserted_in_current_week(self):
        """In the current week, a "Now" marker labelled with the current day and time is inserted before the first series whose time is after now."""
        assert "nowLineHtml(now)" in _nested(_load_schedule(), "weekPanelHtml")
        out = _run_schedule("""
  await loadSchedule();
  out.cur = snap().content;
  selectScheduleWeek(2);
  out.other = snap().content;
""")
        if out is None:
            return
        cur = out["cur"]
        assert cur.count("schedule-now-line") == 1
        assert "Now · Wed 18:00" in cur
        line = cur.index("schedule-now-line")
        assert cur.index("Alpha") < line < cur.index("Thu 8.10.2026")  # live 17:30 before, 8.10 after
        assert "schedule-now-line" not in out["other"]

    def test_division_filter_and_empty_division_message(self):
        """Division chips (All, Div 1, Div 2) narrow the week's list; a division with no series that week shows "No matches for this division this week."."""
        panel = _nested(_load_schedule(), "weekPanelHtml")
        assert '["all", "All"], ["div1", "Div 1"], ["div2", "Div 2"]' in panel
        assert "No matches for this division this week." in panel
        out = _run_schedule("""
  await loadSchedule();
  setScheduleDivision("div1");
  out.div1 = snap().content;
  selectScheduleWeek(2);
  out.empty = snap().content;
  setScheduleDivision("all");
  out.all = snap().content;
""")
        if out is None:
            return
        assert "Bravo" in out["div1"] and "Delta</span>" in out["div1"] and "Echo" not in out["div1"]
        assert 'aria-pressed="true" data-focus="div-div1" onclick="setScheduleDivision(\'div1\')"' in out["div1"]
        assert "No matches for this division this week." in out["empty"]
        assert "Charlie" in out["all"]

    def test_phone_layout_media_query(self):
        """style.css has a `max-width: 700px` media block that stacks the now cards, makes the week strip scroll sideways (overflow-x), hides the arrows, uses a two-line series row grid and hides hero icons in game rows."""
        body = _media_body(_css(), "max-width: 700px")
        assert "grid-template-columns: 1fr" in _rule(body, ".schedule-now")
        assert "overflow-x: auto" in _rule(body, ".schedule-week-chips")
        assert "display: none" in _rule(body, ".schedule-week-arrow")
        row = _rule(body, ".series-row")
        assert '"meta meta links"' in row and '"t1 mid t2"' in row
        assert "display: none" in _rule(body, ".game-row-heroes")

    def test_touch_targets_at_least_44px(self):
        """The hide toggle, week chips and week arrow buttons have a min-height (or height) of at least 44px."""
        css = _css()
        for sel in (".schedule-hide-toggle", ".schedule-week-chip", ".schedule-week-arrow", ".schedule-this-week"):
            m = re.search(r"min-height:\s*(\d+)px", _rule(css, sel))
            assert m and int(m.group(1)) >= 44, sel
        phone = _media_body(css, "max-width: 700px")
        for sel in (".series-btn", ".schedule-div-chip", "button.now-card-btn", "a.now-card-link"):
            assert "min-height: 44px" in _rule(phone, sel), sel

    def test_load_schedule_keeps_stale_notice_loading_and_render_if_changed(self):
        """loadSchedule still renders through renderIfChanged, shows "Loading..." only on an empty container (first load) and keeps the stale notice."""
        body = _load_schedule()
        assert 'const firstLoad = content.innerHTML.trim() === "";' in body
        assert "if (firstLoad) renderIfChanged(content, \"<span class='schedule-empty'>Loading...</span>\");" in body
        assert body.count("Loading") == 1
        assert "renderIfChanged(content, weekPanelHtml(" in body
        assert "renderIfChanged(nowEl, nowHtml)" in body and "renderIfChanged(weeksEl, weekStripHtml(" in body
        assert not re.search(r"\.innerHTML\s*=(?!=)", body)
        assert "if (data.stale) {" in body and 'staleEl.style.display = "none";' in body
        data = _scenario()
        data["stale"] = True
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
  out.stale = document.getElementById("scheduleStale").textContent;
""", data=data)
        if out is None:
            return
        assert out["stale"].startswith("Cached data from")


# ---------------------------------------------------------------------------
# Story 3: Hide Results Until I Choose to See Them
# ---------------------------------------------------------------------------

class TestHideResults:

    def test_hide_toggle_markup_has_aria_pressed(self):
        """The Schedule header has a "Hide results" toggle button with `aria-pressed`. Its label stays "Hide results"; the pressed state (and its styling) carries on/off."""
        markup = _schedule_markup()
        assert re.search(r'<button type="button" id="scheduleHideToggle"[^>]*aria-pressed="true"[^>]*onclick="toggleScheduleHide\(\)">Hide results</button>', markup)
        body = _load_schedule()
        assert 'toggle.setAttribute("aria-pressed", hide ? "true" : "false");' in body
        assert "toggle.textContent" not in body
        out = _run_schedule("""
  await loadSchedule();
  out.on = snap();
  toggleScheduleHide();
  out.off = snap();
""")
        if out is None:
            return
        assert out["on"]["togglePressed"] == "true" and out["off"]["togglePressed"] == "false"
        assert out["on"]["toggleLabel"] == out["off"]["toggleLabel"]  # the label never changes

    def test_hide_mode_on_by_default(self):
        """Hide mode reads `kc_schedule_hide`; only the stored value "0" turns it off, so absent or unreadable storage counts as on."""
        body = _fn_body(_js(), "_schedHideOn")
        assert 'localStorage.getItem("kc_schedule_hide") !== "0"' in body
        assert "_schedHideMem = true;" in body.split("catch")[1]
        steps = """
  await loadSchedule();
  out.s = snap();
"""
        absent = _run_schedule(steps)
        if absent is None:
            return
        on = _run_schedule(steps, store={"kc_schedule_hide": "1"})
        off = _run_schedule(steps, store={"kc_schedule_hide": "0"})
        junk = _run_schedule(steps, store={"kc_schedule_hide": "nope"})
        blocked = _run_schedule(steps, storage="blocked")
        for out in (absent, on, junk, blocked):
            assert "1–2" not in out["s"]["content"] and "Played" in out["s"]["content"]
        assert "1–2" in off["s"]["content"]

    def test_hide_mode_choice_persisted(self):
        """Toggling writes `kc_schedule_hide` ("0" when turned off, "1" when turned on) so the choice survives visits and logins (not cleared on logout)."""
        body = _fn_body(_js(), "toggleScheduleHide")
        assert 'localStorage.setItem("kc_schedule_hide", _schedHideMem ? "1" : "0");' in body
        auth = _read(os.path.join(_FRONTEND_DIR, "app-auth.js"))
        assert "kc_schedule" not in auth and "localStorage.clear" not in auth
        out = _run_schedule("""
  await loadSchedule();
  toggleScheduleHide();
  out.a = snap().store;
  toggleScheduleHide();
  out.b = snap().store;
""")
        if out is None:
            return
        assert out["a"]["kc_schedule_hide"] == "0"
        assert out["b"]["kc_schedule_hide"] == "1"

    def test_storage_access_wrapped_in_try_catch(self):
        """Failure path: every localStorage read/write of `kc_schedule_hide` and `kc_schedule_revealed` is inside try/catch, so blocked storage still renders."""
        js = _js()
        uses = [m.start() for m in re.finditer(r"localStorage\.(?:getItem|setItem)\(\"kc_schedule_", js)]
        assert len(uses) == 5  # hide read/write, reveal read/write, unreveal write
        for pos in uses:
            before = js[:pos]
            assert before.rindex("try {") > before.rindex("\n}\n"), js[pos:pos + 60]
            assert "catch (_)" in js[pos:pos + 300]
        assert "localStorage" not in _load_schedule()
        out = _run_schedule("""
  await loadSchedule();
  out.a = snap();
  toggleScheduleHide();
  out.b = snap();
  toggleScheduleHide();
  revealScheduleSeries(id("201,202,203"));
  out.c = snap();
""", storage="blocked")
        if out is None:
            return
        assert "Played" in out["a"]["content"] and out["a"]["status"] == ""
        assert "1–2" in out["b"]["content"]  # works in memory, just not persisted
        assert "1–2" in out["c"]["content"]
        assert out["c"]["store"] == {}

    def test_series_key_stable(self):
        """seriesKey(s) is the sorted, joined `series_result.match_ids`, or `team1|team2|datetime_iso` for a series with no games."""
        body = _fn_body(_js(), "seriesKey")
        assert ".sort((a, b) => a - b).join(\",\")" in body
        out = _run_schedule("""
  out.r = [seriesKey({series_result: {match_ids: [30, 4, 200]}}),
           seriesKey({team1: "A", team2: "B", datetime_iso: "2026-10-05T19:00:00", series_result: null}),
           seriesKey({team1: "A", team2: "B", datetime_iso: "x", series_result: {match_ids: []}})];
""")
        if out is None:
            return
        assert out["r"] == ["4,30,200", "A|B|2026-10-05T19:00:00", "A|B|x"]

    def test_row_state_order_live_upcoming_hidden_shown(self):
        """rowState returns `live` for a matching live pair, else `upcoming` when match_status !== "past", else `noresult` when there is no series_result, else `hidden` when hide mode is on and neither the key nor its week is revealed, else `shown`."""
        body = _fn_body(_js(), "rowState")
        assert body.index('return "live"') < body.index('return "upcoming"') < body.index('return "hidden"') < body.index('return "shown"')
        assert 'if (s.match_status !== "past") return "upcoming";' in body
        assert 'if (!s.series_result) return "noresult";' in body
        out = _run_schedule("""
  const played = {team1_id: 1, team2_id: 2, match_status: "past", datetime_iso: "2026-10-05T19:00:00",
                  series_result: {start_time: 1000, match_ids: [9]}};
  const ctx = (o) => Object.assign({live: [], hide: true, revealed: new Set(), reportWeeks: new Set(), weekId: 4}, o);
  out.r = [
    rowState(played, ctx({live: [{team_ids: [1, 2], started_at: 1200}]})),
    rowState(played, ctx({live: [{team_ids: [1, 2], started_at: 1000 + 13 * 3600}]})),
    rowState(Object.assign({}, played, {match_status: "upcoming"}), ctx()),
    rowState(Object.assign({}, played, {series_result: null}), ctx()),
    rowState(played, ctx()),
    rowState(played, ctx({revealed: new Set(["9"])})),
    rowState(played, ctx({reportWeeks: new Set([4])})),
    rowState(played, ctx({hide: false})),
  ];
""")
        if out is None:
            return
        # A live game 13 h away from the series' time is an earlier/later meeting, not this one.
        assert out["r"] == ["live", "hidden", "upcoming", "noresult", "hidden", "shown", "shown", "shown"]

    def test_hidden_row_markup_has_no_score_or_game_rows(self):
        """A hidden row outputs both team names at equal weight, "Played" and a "Reveal" button, and its markup has no score, game count, `game-row`, kills, heroes, MVP or "Not scored" badge (not output at all, not hidden via CSS)."""
        hidden = _nested(_load_schedule(), "hiddenRow")
        assert "Played" in hidden and ">Reveal</button>" in hidden
        for leak in ("series-score", "game-row", "games", "team1_wins", "mvp", "Not scored", "win", "loss"):
            assert leak not in hidden, leak
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""")
        if out is None:
            return
        row = _row(out["s"]["content"], "Charlie", "Delta")
        assert '<span class="series-team">' in row and '<span class="series-team right">' in row
        assert "Played" in row and ">Reveal</button>" in row
        for leak in ("1–2", "series-score", "game-row", "3 games", "KillerQueen", "★", "Not scored",
                     "hero-icon", "win", "loss", "201", "203"):
            assert leak not in row, leak
        # Nothing about the hidden series' games anywhere on the page.
        page = out["s"]["content"] + out["s"]["now"] + out["s"]["weeks"]
        assert "KillerQueen" not in page and "game-row" not in page and "201,202,203" not in page

    def test_reveal_persists_series_key_capped_at_500(self):
        """Clicking Reveal adds the series key to `kc_schedule_revealed` (JSON array, capped at the 500 most recent) and re-renders the row as shown with games folded."""
        assert "const _SCHED_REVEALED_MAX = 500;" in _js()
        body = _fn_body(_js(), "_schedReveal")
        assert 'localStorage.setItem("kc_schedule_revealed", JSON.stringify([...set]));' in body
        assert "while (set.size > _SCHED_REVEALED_MAX)" in body
        old = json.dumps([f"old{i}" for i in range(500)])
        out = _run_schedule("""
  await loadSchedule();
  revealScheduleSeries(id("201,202,203"));
  out.s = snap();
  await loadSchedule();
  out.reload = snap();
""", store={"kc_schedule_revealed": old})
        if out is None:
            return
        stored = json.loads(out["s"]["store"]["kc_schedule_revealed"])
        assert len(stored) == 500 and stored[-1] == "201,202,203" and "old0" not in stored and stored[0] == "old1"
        row = _row(out["s"]["content"], "Charlie", "Delta")
        assert "1–2" in row and "3 games" in row and 'aria-expanded="false"' in row and "game-row" not in row
        assert "1–2" in _row(out["reload"]["content"], "Charlie", "Delta")

    def test_reveal_week_button_and_chip_marker(self):
        """A week with hidden results shows a "Reveal week" button in its header that reveals every played series in it, and its week chip carries a hidden-results marker."""
        assert 'onclick="revealScheduleWeek(${sel})">Reveal week</button>' in _nested(_load_schedule(), "weekPanelHtml")
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(0);
  out.before = snap();
  revealScheduleWeek(0);
  out.after = snap();
""")
        if out is None:
            return
        chips = out["before"]["weeks"].split('class="schedule-week-chip ')[1:]
        assert ["schedule-week-chip-marker" in c for c in chips] == [True, True, False]
        assert "Reveal week</button>" in out["before"]["content"]
        after = out["after"]["content"]
        assert "2–0" in after and "1–0" in after and "Reveal week" not in after and "Played" not in after
        assert set(json.loads(out["after"]["store"]["kc_schedule_revealed"])) == {"101,102", "50"}
        chips_after = out["after"]["weeks"].split('class="schedule-week-chip ')[1:]
        assert ["schedule-week-chip-marker" in c for c in chips_after] == [False, True, False]

    def test_turning_hide_off_shows_all_and_back_on_hides_only_unrevealed(self):
        """Turning hide mode off shows every result without clearing `kc_schedule_revealed`; turning it back on hides only series never revealed."""
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(0);
  revealScheduleSeries(id("101,102"));
  toggleScheduleHide();
  out.off = snap();
  toggleScheduleHide();
  out.on = snap();
""")
        if out is None:
            return
        assert "2–0" in out["off"]["content"] and "1–0" in out["off"]["content"]
        assert json.loads(out["off"]["store"]["kc_schedule_revealed"]) == ["101,102"]
        assert "2–0" in _row(out["on"]["content"], "Alpha", "Bravo")
        assert "Played" in _row(out["on"]["content"], "Golf", "Hotel")

    def test_upcoming_and_live_rows_unaffected_by_hide_mode(self):
        """Upcoming and live rows render the same in both modes (rowState returns live/upcoming before considering hide mode)."""
        out = _run_schedule("""
  await loadSchedule();
  out.on = snap();
  toggleScheduleHide();
  out.off = snap();
""")
        if out is None:
            return
        for t1, t2 in (("Alpha", "Charlie"), ("Bravo", "Delta"), ("Echo", "Foxtrot")):
            assert _row(out["on"]["content"], t1, t2) == _row(out["off"]["content"], t1, t2)
        live = _row(out["on"]["content"], "Alpha", "Charlie")
        assert '<span class="live-tag">Live</span>' in live and 'href="https://twitch.tv/live"' in live
        assert "vs" in _row(out["on"]["content"], "Bravo", "Delta")


# ---------------------------------------------------------------------------
# Story 4: Results Already Seen in the Weekly Report Stay Revealed
# ---------------------------------------------------------------------------

class TestWeeklyReportRevealLinkUp:

    def test_load_schedule_fetches_weekly_summary_when_logged_in(self):
        """When `activeUsername` is set, the Schedule load fetches GET /weekly-summary once and keeps a set of week_ids whose `revealed` flag is true."""
        body = _fn_body(_js(), "_schedFetchReportReveals")
        assert "if (!activeUsername) return new Set();" in body
        assert "fetch(`${API}/weekly-summary`)" in body
        assert ".filter(w => w.revealed).map(w => w.week_id)" in body
        assert _load_schedule().count("_schedFetchReportReveals()") == 1
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""", username="bob", summary={"weeks": [{"week_id": 1, "label": "Week 1", "revealed": True},
                                         {"week_id": 2, "label": "Week 2", "revealed": False}]})
        if out is None:
            return
        assert out["s"]["fetches"].count(["/weekly-summary", "GET"]) == 1

    def test_series_in_revealed_week_shown_in_hide_mode(self):
        """In hide mode, every series placed in a fantasy week revealed in the Weekly Report renders as shown without a click."""
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(0);
  out.w1 = snap();
  selectScheduleWeek(1);
  out.w2 = snap();
""", username="bob", summary={"weeks": [{"week_id": 1, "label": "Week 1", "revealed": True}]})
        if out is None:
            return
        assert "2–0" in out["w1"]["content"] and "1–0" in out["w1"]["content"]
        assert "Played" not in out["w1"]["content"]
        assert "Played" in _row(out["w2"]["content"], "Charlie", "Delta")
        assert out["w1"]["togglePressed"] == "true"

    def test_revealed_week_header_note_and_no_reveal_week_button(self):
        """A week revealed in the Weekly Report shows "Revealed in your Weekly Report" in its header and no "Reveal week" button."""
        assert "Revealed in your Weekly Report" in _nested(_load_schedule(), "weekPanelHtml")
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(0);
  out.w1 = snap();
""", username="bob", summary={"weeks": [{"week_id": 1, "label": "Week 1", "revealed": True}]})
        if out is None:
            return
        hd = out["w1"]["content"].split('<div class="schedule-day">')[0]
        assert "Revealed in your Weekly Report" in hd and "Reveal week" not in hd
        assert "schedule-week-chip-marker" not in out["w1"]["weeks"].split('class="schedule-week-chip ')[1]

    def test_schedule_reveal_does_not_write_weekly_report(self):
        """Revealing a series or week on the Schedule only touches localStorage; no request is made to any weekly-summary reveal endpoint."""
        js = _js()
        start = js.index("// Schedule tab (issue #156)")
        section = js[start:js.index("function showPlayerPreview(")]
        assert "weekly-summary/" not in section and "method:" not in section and "/reveal" not in section
        out = _run_schedule("""
  await loadSchedule();
  revealScheduleSeries(id("201,202,203"));
  revealScheduleWeek(0);
  out.s = snap();
""", username="bob", summary={"weeks": []})
        if out is None:
            return
        assert out["s"]["fetches"] == [["/weekly-summary", "GET"], ["/schedule", "GET"]]

    def test_weekly_summary_failure_or_logged_out_falls_back(self):
        """Failure path: when logged out (no fetch) or when GET /weekly-summary fails (caught and ignored), the Schedule still renders using browser-stored reveals."""
        steps = """
  await loadSchedule();
  out.s = snap();
"""
        logged_out = _run_schedule(steps, store={"kc_schedule_revealed": '["201,202,203"]'})
        if logged_out is None:
            return
        assert logged_out["s"]["fetches"] == [["/schedule", "GET"]]
        assert "1–2" in _row(logged_out["s"]["content"], "Charlie", "Delta")
        failed = _run_schedule(steps, username="bob", summary="fail",
                               store={"kc_schedule_revealed": '["201,202,203"]'})
        assert failed["s"]["status"] == ""
        assert "1–2" in _row(failed["s"]["content"], "Charlie", "Delta")


# ---------------------------------------------------------------------------
# Story 5: Played Results Read at a Glance
# ---------------------------------------------------------------------------

class TestPlayedResultsAtAGlance:

    def test_shown_row_score_display_type_and_winner_loser_styling(self):
        """A revealed series shows its score in the display font class, the winner's name bright and bold and the loser's name muted (distinct winner/loser classes in markup and CSS)."""
        css = _css()
        assert "font-family: var(--font-display)" in _rule(css, ".series-score")
        win = _rule(css, ".series-team.win")
        loss = _rule(css, ".series-team.loss")
        assert "color: var(--fg)" in win and "font-weight: var(--w-bold)" in win
        assert "color: var(--fg-muted)" in loss
        out = _run_schedule("""
  await loadSchedule();
  toggleScheduleHide();
  out.s = snap();
""")
        if out is None:
            return
        row = _row(out["s"]["content"], "Charlie", "Delta")
        assert re.search(r'<span class="series-team loss">.*Charlie', row)
        assert re.search(r'<span class="series-team right win">.*Delta', row)
        assert '<span class="series-score">1–2</span>' in row

    def test_games_folded_behind_button_with_aria_expanded(self):
        """Per-game rows are folded by default behind an "N games" button with `aria-expanded`; toggling uses an in-memory set of open series keys and re-renders through renderIfChanged."""
        js = _js()
        assert "const _schedOpenGames = new Set();" in js
        assert "_schedRerender()" in _fn_body(js, "toggleScheduleGames")
        out = _run_schedule("""
  await loadSchedule();
  toggleScheduleHide();
  out.folded = snap().content;
  toggleScheduleGames(id("201,202,203"));
  out.open = snap().content;
  toggleScheduleGames(id("201,202,203"));
  out.closed = snap().content;
""")
        if out is None:
            return
        assert 'aria-expanded="false"' in _row(out["folded"], "Charlie", "Delta") and "game-row" not in out["folded"]
        row = _row(out["open"], "Charlie", "Delta")
        assert 'aria-expanded="true"' in row and ">3 games</button>" in row and row.count('class="game-row"') == 3
        assert "game-row" not in out["closed"]

    def test_unfolded_game_row_contents(self):
        """An unfolded game row shows game number, each side's hero icons, kills score, MVP with a star, duration, OpenDota link and the "Not scored" badge where `excluded_from_scoring`."""
        out = _run_schedule("""
  await loadSchedule();
  toggleScheduleHide();
  toggleScheduleGames(id("201,202,203"));
  out.s = snap();
""")
        if out is None:
            return
        rows = re.findall(r'<div class="game-row">(.*?)</div>', out["s"]["content"], re.S)
        assert len(rows) == 3
        g1, g2, _ = rows
        assert "G1" in g1 and "11–22" in g1 and "★" in g1 and "KillerQueen" in g1
        assert 'class="hero-icon"' in g1 and "hero-icon-placeholder" in g1
        assert "33:05" in g1 and 'href="https://www.opendota.com/matches/201"' in g1
        assert "Not scored" in g2 and "Not scored" not in g1

    def test_latest_result_games_button_jumps_and_unfolds(self):
        """The Latest result card's "Games" button selects the current week and adds the series key to the open set so its games are unfolded."""
        body = _fn_body(_js(), "showScheduleLatestGames")
        assert "_schedOpenGames.add(key);" in body and "selectScheduleWeek(i);" in body
        out = _run_schedule("""
  await loadSchedule();
  toggleScheduleHide();
  selectScheduleWeek(2);
  out.card = snap().now;
  showScheduleLatestGames(id("201,202,203"), 1);
  out.s = snap();
""")
        if out is None:
            return
        assert 'onclick="showScheduleLatestGames(this.dataset.key, 1)">Games</button>' in out["card"]
        assert ">Week 2</h3>" in out["s"]["content"]
        assert 'aria-expanded="true"' in _row(out["s"]["content"], "Charlie", "Delta")
        assert out["s"]["content"].count('class="game-row"') == 3

    def test_series_without_games_shows_vs_and_no_games_button(self):
        """Failure path: a series with no resolved games shows "vs" and renders no games button."""
        data = _scenario()
        data["weeks"][1]["div2"][0]["series_result"]["games"] = []
        out = _run_schedule("""
  await loadSchedule();
  toggleScheduleHide();
  out.s = snap();
""", data=data)
        if out is None:
            return
        upcoming = _row(out["s"]["content"], "Bravo", "Delta")
        assert '<span class="series-score no-result">vs</span>' in upcoming and "aria-expanded" not in upcoming
        played_no_games = _row(out["s"]["content"], "Charlie", "Delta")
        assert "aria-expanded" not in played_no_games and "games</button>" not in played_no_games


class TestScheduleUxReviewFixes:
    """UX review follow-up: keyboard focus survives redraws, reveals can be undone,
    hidden rows don't link to the spoiling team popup, a constant toggle label,
    "No result" for past fixtures without games, and one aligned column grid."""

    def test_focus_restored_after_redraw(self):
        """render() remembers the focused Schedule control (data-focus) and, when the redraw removed it, focuses the same control or its successor (Reveal → games button, else the week heading)."""
        body = _load_schedule()
        render = _nested(body, "render")
        assert render.index("const prevFocus = _schedFocusTarget();") < render.index("renderIfChanged(content")
        assert render.index("renderIfChanged(content, weekPanelHtml") < render.index("_schedRestoreFocus(prevFocus);") < render.index("_schedRerender = render;")
        restore = _fn_body(_js(), "_schedRestoreFocus")
        assert 'tries.push(`games-${id}`, "latest-games")' in restore and 'tries.push("week-title")' in restore
        assert '<h3 tabindex="-1" data-focus="week-title">' in body
        for key in ('data-focus="reveal-${id}"', 'data-focus="games-${id}"', 'data-focus="week-${i}"',
                    'data-focus="div-${v}"', 'data-focus="reveal-week"', 'data-focus="hide-week"'):
            assert key in body, key

    def test_hide_week_again_undoes_reveals_made_on_the_tab(self):
        """After "Reveal week", the week header offers "Hide week again", which hides those series again and brings back "Reveal week"."""
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(1);
  revealScheduleWeek(1);
  out.revealed = snap();
  hideScheduleWeekAgain(1);
  out.hidden = snap();
""")
        if out is None:
            return
        assert "Hide week again" in out["revealed"]["content"] and "Reveal week" not in out["revealed"]["content"]
        assert "Played" not in _row(out["revealed"]["content"], "Charlie", "Delta")
        assert "Reveal week" in out["hidden"]["content"] and "Hide week again" not in out["hidden"]["content"]
        assert "Played" in _row(out["hidden"]["content"], "Charlie", "Delta")
        assert "[]" == out["hidden"]["store"]["kc_schedule_revealed"]

    def test_hidden_rows_use_plain_team_names(self):
        """Failure path: a hidden row never links a team name (the team popup lists results)."""
        hidden = _nested(_load_schedule(), "hiddenRow")
        assert '(_escHtml(s.team1) || "—")' in hidden and '(_escHtml(s.team2) || "—")' in hidden
        assert "teamHtml" not in hidden and "teamLink" not in hidden

    def test_toggle_label_is_constant(self):
        """The hide toggle keeps the label "Hide results"; only aria-pressed (and its styling) changes."""
        assert 'onclick="toggleScheduleHide()">Hide results</button>' in _schedule_markup()
        assert "toggle.textContent" not in _load_schedule()

    def test_past_fixture_without_games_shows_no_result(self):
        """A fixture past its date with no resolved games shows "No result", not "vs" and a watch link as if upcoming."""
        data = _scenario()
        data["weeks"][1]["div2"][0]["series_result"] = None
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(1);
  out.s = snap();
""", data=data)
        if out is None:
            return
        row = _row(out["s"]["content"], "Charlie", "Delta")
        assert '<span class="series-played">No result</span>' in row and ">vs<" not in row and "Reveal" not in row

    def test_rows_and_game_rows_share_one_aligned_grid(self):
        """Series rows and game rows use the same column grid; teams face the score; links and buttons sit in fixed slots; dates use English weekdays."""
        css = _css()
        assert "--sched-cols:" in css
        assert "grid-template-columns: var(--sched-cols)" in _rule(css, ".series-row")
        assert "grid-template-columns: var(--sched-cols)" in _rule(css, ".game-row")
        assert "text-align: right" in _rule(css, ".series-team") and "text-align: left" in _rule(css, ".series-team.right")
        assert "grid-template-columns: minmax(0, 1fr) 96px" in _rule(css, ".series-links")
        assert "repeat(auto-fit, minmax(260px, 1fr))" in _rule(css, ".schedule-now")
        assert 'const _SCHED_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];' in _js()
        assert "fi-FI" not in _load_schedule()

    def test_next_up_lists_up_to_three_series(self):
        """Next up shows the next three timed series as compact rows (time, division, teams, watch), with the countdown to the first in the card header."""
        strip = _nested(_load_schedule(), "nowStripHtml")
        assert ".slice(0, 3)" in strip and 'class="next-row"' in strip
        css = _css()
        assert 'grid-template-areas: "when teams watch"' in _rule(css, ".next-row")
        data = _scenario()
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""", data=data)
        if out is None:
            return
        nxt = _now_card(out["s"]["now"], "next")
        assert 1 <= nxt.count('class="next-row"') <= 3
        assert nxt.count('class="now-countdown"') == 1

    def test_streamer_name_before_watch_button(self):
        """The streamer (feed label, else the channel from the stream URL) is shown before the watch button."""
        js = _js()
        assert "function _schedStreamerName(url)" in js
        assert '${streamerHtml(s)}<a class="${cls}"' in _load_schedule()
        out = _run_schedule("""
  out.n = [_schedStreamerName("https://www.twitch.tv/kanaliiga"), _schedStreamerName("https://youtube.com/@kanaliigatv"),
           _schedStreamerName("https://kick.com/dota_fi/videos"), _schedStreamerName("https://example.org/live"),
           _schedStreamerName("not a url")];
""")
        if out is None:
            return
        assert out["n"] == ["kanaliiga", "kanaliigatv", "dota_fi", "example.org", ""]

    def test_upcoming_without_stream_shows_caster_tbd_and_disabled_watch(self):
        """An upcoming fixture with no stream URL shows "Caster TBD" (or the feed's label) and a greyed-out Watch that is not a link."""
        body = _load_schedule()
        watch = _nested(body, "upcomingWatch")
        assert '"Caster TBD"' in watch and 'aria-disabled="true"' in watch and "is-disabled" in watch
        assert "<a " not in watch.split("if (s.stream_url) return streamLink(s, fallback, cls);")[1]
        assert "cursor: not-allowed" in _rule(_css(), ".now-card-link.is-disabled")
        data = _scenario()
        out = _run_schedule("""
  await loadSchedule();
  selectScheduleWeek(2);
  out.s = snap();
""", data=data)
        if out is None:
            return
        # Charlie vs Bravo (week 3) is a timed upcoming fixture with no stream in the scenario.
        row = _row(out["s"]["content"], "Charlie", "Bravo")
        assert "Caster TBD" in row and 'aria-disabled="true"' in row and "href=" not in row

    def test_next_up_fills_with_untimed_feed_weeks(self):
        """With fewer than three timed series, Next up adds one summary row per coming feed week whose matches have no time ("Week 5 / Mon 12.10." and "Next week · 7 matches, times to be announced"), with a View week button."""
        strip = _nested(_load_schedule(), "nowStripHtml")
        assert "slice(0, 3 - nextList.length)" in strip and "View week" in strip and "s.feedWeek" in strip
        assert 'feedWeek: week.label' in _load_schedule()
        out = _run_schedule("""
  await loadSchedule();
  out.s = snap();
""")
        if out is None:
            return
        nxt = _now_card(out["s"]["now"], "next")
        assert nxt.count('class="next-row') <= 3
        if 'next-tbd' in nxt:
            assert "times to be announced" in nxt and "View week</button>" in nxt and "fixture" not in nxt

    def test_weeks_away_label(self):
        """Untimed weeks in Next up are named relative to now: "This week", "Next week", "In 2 weeks"."""
        out = _run_schedule("""
  const mon = new Date(2026, 9, 5, 0, 0).getTime() / 1000;  // Mon 5.10.2026
  const now = mon + 86400 + 7 * 3600;                         // Tue 6.10. 07:00
  out.r = [_schedWeeksAway(mon, now), _schedWeeksAway(mon + 7 * 86400, now),
           _schedWeeksAway(mon + 14 * 86400, now), _schedWeeksAway(mon + 21 * 86400 + 3600, now)];
""")
        if out is None:
            return
        assert out["r"] == ["This week", "Next week", "In 2 weeks", "In 3 weeks"]
