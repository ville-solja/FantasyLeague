"""Tests for plan-issue-249-roster-after-draw (GitHub issue #249).

After a web draw, My Team leaves a locked week it was showing and reloads the editable
roster, so the drawn card lands in its slot or on the bench. With no upcoming week, the
week picker gets a first option "Next week (not scheduled)", and `GET /roster/{user_id}`
without `week_id` returns no week points (it used to sum card points from time 0 to now).
The deck-to-reveal lift frame no longer spreads a `DOMRect` (`{ ...from }` gave NaN).

Developer notes (fixtures and helpers to reuse):
- `db` fixture from conftest; `models` is imported at module level so tables exist.
- Backend: call `routers.cards._build_roster_response(db, user_id, week_id)` directly
  (as `_roster_points` in test_issue_141_stored_card_points.py does), or the route
  function `routers.cards.get_roster(user_id, week_id=None, db=db, current_user={...})`
  as in test_get_roster_admin_session_freshness.py.
- Seeding: follow `_seed` in test_issue_250_weekly_points_clarity.py (`_add_weights` from
  test_issue_141, users, players, teams, cards, weeks, `WeeklyRosterEntry`, matches,
  `PlayerMatchStats`, then `card_points.rebuild_all(db)`). The "no upcoming week" case
  needs every `Week.start_time <= clock.now(db)` (`weeks.get_next_editable_week` uses
  `clock.now`; the builder's old fallback window was `0..time.time()`): place weeks and matches
  relative to `int(time.time())` (e.g. a locked week that ended an hour ago and a live
  locked week covering now), with scored matches in those windows so a 0..now sum would
  be non-zero. The "upcoming week" case adds an unlocked week starting in the future
  with a scored match whose start_time falls inside it (override with
  `Match.week_override_id` if needed).
- Frontend: static reads with `_f(name)` from test_issue_202_ui_feedback_polish.py and
  function slices with `_fn_body(js, name)` from test_issue_151_weekly_report_aesthetics.py
  (it drops `async`; re-add it when pasting into a harness). Node harnesses use
  `_run_node(script)` from test_issue_202 (skips when node is missing). The reveal's
  "Draw another card" path is `revealAction` -> `drawCard` / `_drawBoosterForTeam`;
  `confirmReroll` is the modifier reroll, which adds no card and keeps the week shown.
- Behaviour of a whole draw: `_run(steps, draw=...)` from test_issue_205 (its harness
  declares `_rosterWeekId`; set `globalThis._weeks` in the steps).
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import card_points
import models  # noqa: F401  (registers tables for the db fixture)
from models import (
    Card, CardMatchPoints, Match, Player, PlayerMatchStats, Team, User, Week, WeeklyRosterEntry,
)
from routers import cards as cards_router
from routers.cards import _build_roster_response
from scoring import display_points, fantasy_score
from tests.test_issue_141_stored_card_points import _WEIGHTS, _add_weights, _stats
from tests.test_issue_151_weekly_report_aesthetics import _fn_body
from tests.test_issue_202_ui_feedback_polish import _f, _run_node
from tests.test_issue_205_card_draw_animations import _run as _run_draw

_HELPER_CALL = "_showEditableRosterForDraw()"
_RELOAD = "_drawRosterReload = loadRoster(_rosterWeekId)"
_NEXT_LABEL = "Next week (not scheduled)"


def _fn(js, name, is_async=False):
    """A whole function, pasteable into a Node harness (`_fn_body` drops `async`)."""
    return ("async " if is_async else "") + _fn_body(js, name) + "\n}\n"


# ---------------------------------------------------------------------------
# Story: A Drawn Card Shows Up in My Roster
# ---------------------------------------------------------------------------

def _run_helper(week_id, weeks):
    script = f"""
let _weeks = {json.dumps(weeks)};
let _rosterWeekId = {json.dumps(week_id)};
let calls = 0;
function _renderWeekSelector() {{ calls++; }}
{_fn(_f("app-cards.js"), "_showEditableRosterForDraw")}
_showEditableRosterForDraw();
console.log(JSON.stringify({{ weekId: _rosterWeekId, calls }}));
"""
    return _run_node(script)


class TestDrawShowsEditableRoster:

    def test_show_editable_roster_for_draw_defined_in_app_cards(self):
        """AC (switch back): app-cards.js defines `function _showEditableRosterForDraw(`; its body (via `_fn_body`) returns early when `_rosterWeekId === null`, looks the shown week up in `_weeks`, returns when that week is not `is_locked`, otherwise sets `_rosterWeekId = null` and calls `_renderWeekSelector()`."""
        js = _f("app-cards.js")
        assert js.count("function _showEditableRosterForDraw(") == 1
        body = _fn_body(js, "_showEditableRosterForDraw")
        early = body.index("if (_rosterWeekId === null) return;")
        lookup = body.index("_weeks")
        unlocked = body.index("!shown.is_locked) return;")
        reset = body.index("_rosterWeekId = null;")
        render = body.index("_renderWeekSelector()")
        assert early < lookup < unlocked < reset < render

    def test_show_editable_roster_for_draw_resets_locked_week_node(self):
        """AC (switch back): Node harness (`_run_node`) with `_weeks = [{id: 10, is_locked: true}]`, `_rosterWeekId = 10` and a spy `_renderWeekSelector`: after `_showEditableRosterForDraw()`, `_rosterWeekId` is `null` and the spy was called once."""
        out = _run_helper(10, [{"id": 10, "is_locked": True}])
        assert out == {"weekId": None, "calls": 1}

    def test_show_editable_roster_for_draw_keeps_unlocked_or_default_view_node(self):
        """AC (unchanged otherwise, failure path): same harness; with `_rosterWeekId = null`, or with `_rosterWeekId = 11` where week 11 has `is_locked: false`, `_showEditableRosterForDraw()` leaves `_rosterWeekId` unchanged and never calls `_renderWeekSelector`."""
        weeks = [{"id": 10, "is_locked": True}, {"id": 11, "is_locked": False}]
        assert _run_helper(None, weeks) == {"weekId": None, "calls": 0}
        assert _run_helper(11, weeks) == {"weekId": 11, "calls": 0}

    def test_draw_card_calls_helper_before_roster_reload(self):
        """AC (switch back): in `_fn_body(app-cards.js, "drawCard")`, `_showEditableRosterForDraw()` appears, and its index is before the index of `_drawRosterReload = loadRoster(_rosterWeekId)`."""
        body = _fn_body(_f("app-cards.js"), "drawCard")
        assert body.count(_HELPER_CALL) == 1
        assert body.index(_HELPER_CALL) < body.index(_RELOAD)

    def test_draw_booster_for_team_calls_helper_before_roster_reload(self):
        """AC (switch back, team draw): in `_fn_body(app-cards.js, "_drawBoosterForTeam")`, `_showEditableRosterForDraw()` appears before `_drawRosterReload = loadRoster(_rosterWeekId)`."""
        body = _fn_body(_f("app-cards.js"), "_drawBoosterForTeam")
        assert body.count(_HELPER_CALL) == 1
        assert body.index(_HELPER_CALL) < body.index(_RELOAD)

    def test_confirm_reroll_keeps_week_and_draw_another_uses_draw_functions(self):
        """AC (switch back, "Draw another card"; unchanged otherwise): `confirmReroll` is the modifier reroll, which adds no card: it reloads with `loadRoster(_rosterWeekId)` and never calls `_showEditableRosterForDraw`. The reveal's "Draw another card" (`revealAction`) goes through `drawCard()` / `_drawBoosterForTeam(teamId)`, which do call it. (Renamed from `test_confirm_reroll_calls_helper_before_roster_reload`, which took `confirmReroll` for the "Draw another card" path.)"""
        js = _f("app-cards.js")
        reroll = _fn_body(js, "confirmReroll")
        assert "/reroll" in reroll and "loadRoster(_rosterWeekId)" in reroll
        assert "_showEditableRosterForDraw" not in reroll
        action = _fn_body(js, "revealAction")
        assert "_drawBoosterForTeam(teamId)" in action and "drawCard()" in action
        assert "loadRoster(" not in action
        for name in ("drawCard", "_drawBoosterForTeam"):
            assert _HELPER_CALL in _fn_body(js, name), name
        # Only the two draws call the helper (the third match is its definition).
        assert js.count(_HELPER_CALL) == 3

    def test_failed_draw_does_not_switch_week(self):
        """AC (failure path: no tokens, empty deck): in `drawCard` and `_drawBoosterForTeam`, the `return` taken on a failed response (`!res.ok`) comes before the `_showEditableRosterForDraw()` call (`confirmReroll` never calls it), so a failed draw never changes the week shown. Run through the draw harness: a 400 answer keeps the locked week, a 200 answer goes back to the editable roster."""
        js = _f("app-cards.js")
        for name in ("drawCard", "_drawBoosterForTeam"):
            body = _fn_body(js, name)
            assert body.index("if (!res.ok)") < body.index(_HELPER_CALL), name
        assert _HELPER_CALL not in _fn_body(js, "confirmReroll")

        steps = """
  globalThis._weeks = [{ id: 10, is_locked: true }];
  _rosterWeekId = 10;
  drawCard();
  await advance(3000);
  out.weekId = _rosterWeekId;
"""
        failed = _run_draw(steps, draw={"status": 400, "body": {"detail": "No tokens left"}})
        assert failed["weekId"] == 10
        assert _run_draw(steps)["weekId"] is None

    def test_lift_frame_does_not_spread_dom_rect(self):
        """AC (visible, landing flight): app-cards.js contains no `{ ...from` spread; the lifted rect is built from fields (`from.left`, `from.top - 24`, `from.width`, `from.height`) passed to `_rectTransform` with `" rotate(-3deg)"`."""
        js = _f("app-cards.js")
        assert "{ ...from" not in js and "{...from" not in js
        start = js.index("const lifted = _rectTransform(")
        stmt = js[start:js.index(";", start)]
        for field in ("left: from.left", "top: from.top - 24", "width: from.width",
                      "height: from.height"):
            assert field in stmt, field
        assert stmt.rstrip().endswith('to, " rotate(-3deg)")')
        # A DOMRect-like object (prototype getters only) gives a finite transform.
        out = _run_node(f"""
{_fn(js, "_rectTransform")}
class R {{ get left() {{ return 10; }} get top() {{ return 100; }} get width() {{ return 50; }} get height() {{ return 70; }} }}
const from = new R(), to = {{ left: 0, top: 0, width: 100, height: 140 }};
console.log(JSON.stringify({{
  spread: _rectTransform({{ ...from, top: from.top - 24 }}, to),
  fields: _rectTransform({{ left: from.left, top: from.top - 24, width: from.width, height: from.height }}, to),
}}));
""")
        assert "NaN" in out["spread"]
        assert out["fields"] == "translate(10px, 76px) scale(0.5, 0.5)"


# ---------------------------------------------------------------------------
# Story: The Week Picker Says Which Roster Is Shown
# ---------------------------------------------------------------------------

_SELECTOR_HARNESS = """
const NOW = Math.floor(Date.now() / 1000);
let _weeks = __WEEKS__;
let _rosterWeekId = __WEEK_ID__;
const sel = { innerHTML: "", value: "unset", options: [] };
const document = { getElementById: id => (id === "rosterWeekSelect" ? sel : null) };
const _escHtml = s => String(s);
function renderIfChanged(el, html) { el.innerHTML = html; return true; }
let loaded = [];
function loadRoster(id) { loaded.push(id); }
__FNS__
__STEPS__
"""


def _run_selector(steps, weeks_js, week_id=None):
    js = _f("app-roster.js")
    fns = _fn(js, "_renderWeekSelector") + _fn(js, "onRosterWeekChange")
    return _run_node(_SELECTOR_HARNESS.replace("__WEEKS__", weeks_js)
                     .replace("__WEEK_ID__", json.dumps(week_id))
                     .replace("__FNS__", fns).replace("__STEPS__", steps))


_PAST_AND_LIVE = """[
  { id: 1, label: "Week 1", start_time: NOW - 7200, end_time: NOW - 3600, is_locked: true },
  { id: 2, label: "Final", start_time: NOW - 3599, end_time: NOW + 3600, is_locked: true },
]"""
_RENDER = "_renderWeekSelector(); console.log(JSON.stringify({ html: sel.innerHTML, value: sel.value }));"


class TestWeekPickerNextWeekOption:

    def test_render_week_selector_has_next_week_not_scheduled_option(self):
        """AC (no upcoming week): `_fn_body(app-roster.js, "_renderWeekSelector")` contains the text "Next week (not scheduled)" in an `<option value="">`, added only when `nextWeek` is undefined and marked `selected` when `_rosterWeekId === null`."""
        body = _fn_body(_f("app-roster.js"), "_renderWeekSelector")
        assert body.count(_NEXT_LABEL) == 1
        start = body.index("const noWeek = nextWeek ? \"\" :")
        stmt = body[start:body.index(";", start)]
        assert '<option value=""${_rosterWeekId === null ? " selected" : ""}>' + _NEXT_LABEL + "</option>" in stmt
        assert "noWeek + _weeks.map(" in body

    def test_render_week_selector_no_upcoming_week_node(self):
        """AC (no upcoming week): Node harness with a stub `<select id="rosterWeekSelect">` element, `_weeks` holding only past/live weeks and `_rosterWeekId = null`: the rendered markup's first option is `<option value="" selected>Next week (not scheduled)</option>`, followed by the past and live week options."""
        out = _run_selector(_RENDER, _PAST_AND_LIVE)
        assert out["html"] == (
            '<option value="" selected>Next week (not scheduled)</option>'
            '<option value="1">Week 1 ✓</option>'
            '<option value="2">Final (live)</option>')
        assert out["value"] == ""
        # With a locked week picked, the extra option is there but not selected.
        picked = _run_selector(_RENDER, _PAST_AND_LIVE, week_id=2)
        assert picked["html"].startswith('<option value="">' + _NEXT_LABEL + "</option>")
        assert '<option value="2" selected>Final (live)</option>' in picked["html"]

    def test_render_week_selector_with_upcoming_week_has_no_extra_option_node(self):
        """AC (upcoming week exists, failure path): same harness with one week whose `start_time` is in the future: no "Next week (not scheduled)" option, and that week's option carries `selected`."""
        weeks = _PAST_AND_LIVE.rstrip("]") + (
            '  { id: 3, label: "Week 3", start_time: NOW + 3601, end_time: NOW + 7200, is_locked: false },\n]')
        out = _run_selector(_RENDER, weeks)
        assert _NEXT_LABEL not in out["html"] and 'value=""' not in out["html"]
        assert '<option value="3" selected>Week 3 (upcoming)</option>' in out["html"]
        assert out["html"].count(" selected") == 1
        # Back to no pick (after a draw): the selection moves to the upcoming week
        # even when the markup itself did not change.
        assert out["value"] == "3"

    def test_on_roster_week_change_maps_empty_value_to_null(self):
        """AC (choosing it): Node harness for `onRosterWeekChange` with a stub select whose `value` is `""` and a spy `loadRoster`: `_rosterWeekId` is `null` (not `NaN`) and `loadRoster` is called with `null`; with value `"7"` it is `7`."""
        out = _run_selector("""
_rosterWeekId = 2;
sel.value = "";
onRosterWeekChange();
const empty = _rosterWeekId;
sel.value = "7";
onRosterWeekChange();
console.log(JSON.stringify({ empty, isNull: empty === null, seven: _rosterWeekId, loaded }));
""", _PAST_AND_LIVE)
        assert out == {"empty": None, "isNull": True, "seven": 7, "loaded": [None, 7]}


# ---------------------------------------------------------------------------
# Story: No Week Points Without a Week
# ---------------------------------------------------------------------------

_UID = 1
_USER = {"user_id": _UID, "username": "alice", "is_admin": False}
# (match_id, seconds from now, week_override_id, {player_id: (kills, deaths, gpm)})
_GAMES = [
    (1, -5000, None, {101: (5, 2, 437), 102: (3, 12, 391), 103: (1, 1, 512)}),
    (2, -1000, None, {101: (2, 1, 403), 102: (4, 0, 455), 103: (6, 3, 377)}),
]
_UPCOMING_GAME = (3, -500, 3, {101: (7, 4, 521), 102: (2, 2, 333), 103: (4, 5, 299)})


def _seed(db, upcoming=False):
    """alice holds c1 rare P101 and c2 common P102 (active) and c5 common P103 (bench).
    Week 1 ended an hour ago, week 2 is live; both locked with c1 and c2 rostered, and
    each has one scored game. `upcoming` adds unlocked week 3 with a game of its own."""
    now = int(time.time())
    _add_weights(db)
    db.add(User(id=_UID, username="alice", email="a@test", password_hash="x", tokens=5))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    for pid in (101, 102, 103):
        db.add(Player(id=pid, name=f"P{pid}"))
    db.add(Card(id=1, player_id=101, owner_id=_UID, card_type="rare", is_active=True, slot_index=0))
    db.add(Card(id=2, player_id=102, owner_id=_UID, card_type="common", is_active=True, slot_index=1))
    db.add(Card(id=5, player_id=103, owner_id=_UID, card_type="common", is_active=False))
    db.add(Week(id=1, label="Week 1", start_time=now - 7200, end_time=now - 3600, is_locked=True))
    db.add(Week(id=2, label="Final", start_time=now - 3599, end_time=now + 3600, is_locked=True))
    games = list(_GAMES)
    if upcoming:
        db.add(Week(id=3, label="Week 3", start_time=now + 3601, end_time=now + 7200, is_locked=False))
        games.append(_UPCOMING_GAME)
    for week_id in (1, 2):
        for card_id in (1, 2):
            db.add(WeeklyRosterEntry(week_id=week_id, user_id=_UID, card_id=card_id))
    for match_id, offset, override, players in games:
        db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=2, start_time=now + offset,
                     radiant_win=True, league_id=1, week_override_id=override))
        for pid, (kills, deaths, gpm) in players.items():
            stats = _stats(kills, deaths, gpm)
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=1 if pid != 103 else 2,
                                    fantasy_points=round(fantasy_score(stats, _WEIGHTS), 4), **stats))
    db.commit()
    card_points.rebuild_all(db)


def _stored_sum(db, card_ids, match_ids):
    return sum(r.points for r in db.query(CardMatchPoints)
               .filter(CardMatchPoints.card_id.in_(card_ids),
                       CardMatchPoints.match_id.in_(match_ids)).all())


def _assert_no_week_points(data):
    assert data["week"] is None
    assert data["combined_value"] == 0.0
    cards = data["active"] + data["bench"]
    assert len(cards) == 3
    assert [c["total_points"] for c in cards] == [0.0, 0.0, 0.0]
    assert [c["match_count"] for c in cards] == [0, 0, 0]


class TestNoWeekPointsWithoutWeek:

    def test_get_roster_no_upcoming_week_returns_zero_week_points(self, db):
        """AC (API): with only past/live locked weeks and scored matches in them, `_build_roster_response(db, uid, None)` returns `week` None, `combined_value` 0.0 and `total_points` 0.0 on every card in `active` and `bench`."""
        _seed(db)
        # The old 0..now window would have summed these.
        assert _stored_sum(db, [1, 2, 5], [1, 2]) > 0
        _assert_no_week_points(_build_roster_response(db, _UID, None))

    def test_get_roster_no_upcoming_week_keeps_cards_and_season_points(self, db):
        """AC (API): in the same seed, the card ids in `active` and `bench` equal the user's owned cards (active ones in `active`), and `season_points` equals `display_points` of the sum of the user's counted locked-week `card_match_points` (the value before the change)."""
        _seed(db)
        data = _build_roster_response(db, _UID, None)
        assert [c["id"] for c in data["active"]] == [1, 2]
        assert [c["id"] for c in data["bench"]] == [5]
        expected = display_points(_stored_sum(db, [1, 2], [1, 2]))
        assert expected > 0
        assert data["season_points"] == expected
        assert data["tokens"] == 5

    def test_get_roster_route_no_upcoming_week_zero_points(self, db):
        """AC (API): `routers.cards.get_roster(uid, week_id=None, db=db, current_user={"user_id": uid, "username": ..., "is_admin": False})` returns the same zero week points and `week: None`."""
        _seed(db)
        data = cards_router.get_roster(_UID, week_id=None, db=db, current_user=_USER)
        _assert_no_week_points(data)
        assert "version" in data

    def test_get_roster_upcoming_week_points_unchanged(self, db):
        """AC (with a week): with an unlocked week starting in the future and a scored match in its window, `_build_roster_response(db, uid, None)` returns that week as `week` and each card's `total_points` equal to `display_points` of its stored `card_match_points` in that window (non-zero), with `combined_value` their sum."""
        _seed(db, upcoming=True)
        data = _build_roster_response(db, _UID, None)
        assert data["week"]["id"] == 3 and data["week"]["is_locked"] is False
        points = {c["id"]: c["total_points"] for c in data["active"] + data["bench"]}
        assert set(points) == {1, 2, 5}
        for card_id, shown in points.items():
            expected = display_points(_stored_sum(db, [card_id], [3]))
            assert expected != 0
            assert shown == expected, card_id
        assert data["combined_value"] == display_points(_stored_sum(db, [1, 2], [3]))

    def test_get_roster_explicit_locked_week_snapshot_unchanged(self, db):
        """AC (with a week, explicit `week_id`): for a locked week with `WeeklyRosterEntry` rows, `_build_roster_response(db, uid, week_id)` returns the snapshot cards and each card's week `total_points` (non-zero), as today."""
        _seed(db)
        for week_id, match_id in ((1, 1), (2, 2)):
            data = _build_roster_response(db, _UID, week_id)
            assert data["week"]["id"] == week_id and data["week"]["is_locked"] is True
            assert [c["id"] for c in data["active"]] == [1, 2]
            assert data["bench"] == []
            for c in data["active"]:
                expected = display_points(_stored_sum(db, [c["id"]], [match_id]))
                assert expected != 0
                assert c["total_points"] == expected
            assert data["combined_value"] == display_points(_stored_sum(db, [1, 2], [match_id]))

    def test_load_roster_status_no_upcoming_week(self):
        """AC (UI): `_fn_body(app-roster.js, "loadRoster")` sets `rosterWeekStatus`'s text to "No upcoming week" when `week` is null (the branch is no longer skipped by `if (weekStatusEl && week)`)."""
        body = _fn_body(_f("app-roster.js"), "loadRoster")
        assert "if (weekStatusEl && week) {" not in body
        el = body.index('document.getElementById("rosterWeekStatus")')
        branch = body.index("if (weekStatusEl && !week) {")
        text = body.index('weekStatusEl.textContent = "No upcoming week";')
        other = body.index("} else if (weekStatusEl) {")
        assert el < branch < text < other < body.index('"In progress"')
