"""
Tests for plan-issue-152-weekly-recap-animations.md (resolves GitHub issue #152).

The Weekly Report's My roster column (#151) gains a per-card points breakdown and a
card-by-card reveal animation. `card_utils.card_points_breakdown(stats, card_type,
weights, rarity, mods, mvp_bonus)` returns the exact parts of one game's card points
(raw, rarity, per-modifier, MVP), which sum to `card_utils._compute_card_points`.
`routers.weekly_summary._build_roster_block` adds `breakdown = {raw, steps[]}` to every
counted card of a revealed week (steps: rarity, modifiers, one MVP step per MVP game
with its `match_id`), rounded with `scoring.display_points` and with the rounding
remainder on the last step (or on `raw`). The frontend renders breakdown chips
(`.recap-chip`), a rarity caption under the thumbnail, "MVP +x" on game rows, and a
reveal controller (`_recapAnimation` run id, Skip / Replay, played weeks in
`localStorage`, `prefers-reduced-motion`, `aria-busy`).

  Story 1: Points Breakdown per Card      (TestPointsBreakdownPerCard)
  Story 2: Card-by-Card Reveal            (TestCardByCardReveal)
  Story 3: Bonus Highlights               (TestBonusHighlights)
  Story 4: Control and Accessibility      (TestControlAndAccessibility)

Approach notes for the implementer:

- `db` fixture from conftest (in-memory SQLite). Keep `import models` at module level so
  every table is registered before the fixture runs (lessons-learned 2026-10-01).
- Seeding: copy the `_seed` / `_add_match` pattern from
  test_issue_151_weekly_report_aesthetics.py: weights (`Weight` rows incl.
  `mvp_bonus_pct`, `rarity_<type>`, `death_pool`, `death_deduction`), users, teams,
  players, cards (`card_type`, `is_active`, `slot_index`), weeks, matches and
  `PlayerMatchStats` (with `is_mvp`), then `card_points.rebuild_all(db)` so stored
  `card_match_points` rows exist (every reader sums stored rows), then
  `weeks._snapshot_week(db, week)`, `week.is_locked = True` and a `WeeklySummary` row.
  Modifiers are `CardModifier` rows (stat_key, bonus pct); add them before
  `rebuild_all`. Read a card's modifiers with `card_points._modifiers(db, [card_id])`.
- Substitution scenario (test_issue_129_automatic_bench_substitution.py `_seed`):
  active A played, B 0 matches, bench C (slot_index 0) and D (slot_index 1) played ->
  after `weeks.run_substitutions(db, week)` B is subbed_out ("Did not play"), C subbed_in.
- Readers are called directly: `_build_week_summary(db, week, revealed, user_id)` and
  read `summary["roster"]["cards"]`, `roster["week_total"]`, card `week_points`,
  `games[].match_id`. Compare rounded reader output to `display_points(exact)`
  (lessons-learned 2026-10-01, #149); compare exact sums with a 1e-6 tolerance.
- Breakdown math: import `card_points_breakdown`, `_compute_card_points`,
  `_load_weights`, `_mvp_bonus_delta` from `card_utils`. `rarity` comes from
  `_load_weights` as `{"mod_<type>": pct/100}`. Iterate every rarity (common, rare,
  epic, legendary) x modifiers on/off x MVP on/off, plus a `deaths` modifier.
  Import new names inside the test bodies (or after implementation at module level)
  so this file collects before `card_points_breakdown` exists.
- Shared labels: `STAT_LABELS` moves out of `backend/image.py` (`_STAT_LABELS_CARD`)
  to `scoring.py` or `card_utils.py`; image.py imports it.
- Frontend criteria are static text checks of `frontend/index.html`,
  `frontend/style.css`, `frontend/app-weekly-summary.js`; reuse the `_read`,
  `_css_blocks`, `_css_rule`, `_media_body` and `_fn_body` helpers from
  test_issue_151_weekly_report_aesthetics.py. Styles must use tokens only (no hex).
- Bump the suite-size check in tests/test_issue_85_split_admin_router.py once these
  pass.

Manual-only (need a real browser, see the plan's Verification section): actual timing
and smoothness of the transitions, the visual pop/glow, Results column usability
during the animation, no console errors after leaving mid-animation.

Run with: cd backend && python3 -m pytest tests/test_issue_152_weekly_recap_animations.py -v
"""

import itertools
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401  (registers every table on Base before the db fixture runs)
import card_points
import weeks
from card_utils import (
    _compute_card_points, _load_weights, _mvp_bonus_delta, card_points_breakdown,
)
from models import (
    Card, CardMatchPoints, CardModifier, Match, Player, PlayerMatchStats, Team, User, Week,
    Weight, WeeklySummary,
)
from routers.weekly_summary import _build_week_summary
from scoring import _death_contribution, display_points, fantasy_score, stat_dict_from_row

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
_STYLE_CSS_PATH = os.path.join(_FRONTEND_DIR, "style.css")
_APP_WEEKLY_SUMMARY_JS_PATH = os.path.join(_FRONTEND_DIR, "app-weekly-summary.js")
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# Static-text helpers (same as test_issue_151_weekly_report_aesthetics.py)
# ---------------------------------------------------------------------------

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _css_blocks(css, selector_re):
    """(selector, body) for every rule whose selector matches selector_re."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if re.search(selector_re, m.group(1))]


def _css_rule(css, selector):
    """Body of the first rule whose selector is exactly `selector`."""
    for sel, body in _css_blocks(css, re.escape(selector)):
        if sel == selector:
            return body
    raise AssertionError(f"no CSS rule for {selector}")


def _media_body(css, query):
    start = css.index(f"@media ({query})", css.index("issue #152"))
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[i + 1:j]
    raise AssertionError(query)


def _fn_body(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start)]


def _js():
    return _read(_APP_WEEKLY_SUMMARY_JS_PATH)


def _recap_css():
    """The issue #152 section of style.css (chips and reveal animation)."""
    css = _read(_STYLE_CSS_PATH)
    start = css.index("/* ---- Breakdown chips and reveal animation (issue #152) ---- */")
    return css[start:css.index('/* ---- "Recap is ready" popup ---- */', start)]


# ---------------------------------------------------------------------------
# Seeding: alice (1) owns active A (card 1, slot 0) and B (card 2, slot 1), bench C
# (card 3) and D (card 4). Week 1 (0..1000) locked with a generated report.
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "kills": 0.3, "assists": 0.15, "gold_per_min": 0.002,
    "death_pool": 3.0, "death_deduction": 0.3, "mvp_bonus_pct": 10.0,
    "rarity_common": 0.0, "rarity_rare": 1.0, "rarity_epic": 2.0, "rarity_legendary": 3.0,
    "modifier_count_common": 0.0, "modifier_count_rare": 1.0, "modifier_count_epic": 2.0,
    "modifier_count_legendary": 3.0, "modifier_bonus_pct": 10.0, "team_booster_cost": 3.0,
}
A, B, C, D, E = 101, 102, 103, 104, 105
HALLA, KUURA = 1, 2
RARITIES = ("common", "rare", "epic", "legendary")

# (match_id, start, excluded, {pid: (team, kills, deaths, gpm, mvp)})
_MATCHES = [
    (1, 100, False, {A: (HALLA, 5, 2, 437, True), B: (HALLA, 1, 1, 300, False),
                     C: (HALLA, 3, 1, 391, False), E: (KUURA, 2, 4, 350, False)}),
    (2, 200, False, {A: (HALLA, 2, 1, 403, False), B: (HALLA, 4, 3, 512, False),
                     C: (HALLA, 4, 0, 455, False), E: (KUURA, 7, 0, 520, True)}),
    (3, 300, False, {A: (HALLA, 7, 0, 611, True), B: (HALLA, 0, 5, 280, False),
                     E: (KUURA, 1, 6, 300, False)}),
]


def _add_match(db, match_id, start, excluded, players):
    db.add(Match(match_id=match_id, radiant_team_id=HALLA, dire_team_id=KUURA,
                 start_time=start, radiant_win=True, league_id=1,
                 excluded_from_scoring=excluded))
    for pid, (team, kills, deaths, gpm, mvp) in players.items():
        stats = {"kills": kills, "deaths": deaths, "gold_per_min": gpm}
        db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=team,
                                fantasy_points=round(fantasy_score(stats, _WEIGHTS), 4),
                                is_mvp=mvp, **stats))


def _seed(db, a_type="legendary", b_type="common", a_mods=(("kills", 10.0), ("gold_per_min", 10.0)),
          matches=_MATCHES, extra_matches=(), substitute=False):
    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.add(User(id=1, username="alice", email="a@test", password_hash="x", tokens=5))
    db.add(Team(id=HALLA, name="Halla"))
    db.add(Team(id=KUURA, name="Kuura"))
    for pid in (A, B, C, D, E):
        db.add(Player(id=pid, name=f"P{pid}", is_active=True))
    for cid, pid, ctype, active, slot in ((1, A, a_type, True, 0), (2, B, b_type, True, 1),
                                          (3, C, "rare", False, 0), (4, D, "common", False, 1)):
        db.add(Card(id=cid, player_id=pid, owner_id=1, card_type=ctype,
                    is_active=active, slot_index=slot))
    db.flush()
    for stat, pct in a_mods:
        db.add(CardModifier(card_id=1, stat_key=stat, bonus_pct=pct))
    db.add(CardModifier(card_id=3, stat_key="kills", bonus_pct=10.0))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=1000, is_locked=False))
    db.add(Week(id=2, label="Week 2", start_time=1001, end_time=2000, is_locked=False))
    for m in list(matches) + list(extra_matches):
        _add_match(db, *m)
    db.commit()
    card_points.rebuild_all(db)
    week = db.get(Week, 1)
    weeks._snapshot_week(db, week)
    week.is_locked = True
    db.add(WeeklySummary(week_id=1, generated_at=int(time.time())))
    db.commit()
    if substitute:
        weeks.run_substitutions(db, week)
        db.commit()
    return week


def _cards(db, revealed=True):
    return _build_week_summary(db, db.get(Week, 1), revealed, 1)["roster"]["cards"]


def _card(db, card_id, revealed=True):
    return next(c for c in _cards(db, revealed) if c["card_id"] == card_id)


def _stored(db, card_id, match_ids):
    return sum(r.points for r in db.query(CardMatchPoints).filter(
        CardMatchPoints.card_id == card_id, CardMatchPoints.match_id.in_(match_ids)).all())


def _exact_parts(db, card_id):
    """Exact breakdown parts summed over the card's games in week 1 (none excluded here)."""
    weights, rarity = _load_weights(db)
    card = db.get(Card, card_id)
    mods = card_points._modifiers(db, [card_id]).get(card_id, {})
    total = 0.0
    for stat in db.query(PlayerMatchStats).join(Match, Match.match_id == PlayerMatchStats.match_id).filter(
            PlayerMatchStats.player_id == card.player_id, Match.start_time <= 1000,
            Match.excluded_from_scoring.isnot(True)).all():
        parts = card_points_breakdown(stat_dict_from_row(stat), card.card_type, weights, rarity, mods,
                                      _mvp_bonus_delta(stat, weights) if stat.is_mvp else 0.0)
        total += parts["raw"] + parts["rarity"] + sum(parts["modifiers"].values()) + parts["mvp"]
    return total


def _random_stats(rng):
    return {"kills": rng.randint(0, 15), "assists": rng.randint(0, 25),
            "deaths": rng.randint(0, 14), "gold_per_min": rng.uniform(200, 800)}


def _rarity():
    return {f"mod_{r}": _WEIGHTS[f"rarity_{r}"] / 100 for r in RARITIES}


def _sum_parts(parts):
    return parts["raw"] + parts["rarity"] + sum(parts["modifiers"].values()) + parts["mvp"]


# ---------------------------------------------------------------------------
# Story 1: Points Breakdown per Card
# ---------------------------------------------------------------------------

class TestPointsBreakdownPerCard:

    # --- breakdown math (card_utils.card_points_breakdown) ---

    def test_card_points_breakdown_parts_sum_to_compute_card_points_each_rarity(self):
        """card_utils.card_points_breakdown: raw + rarity + sum(modifiers) + mvp equals
        _compute_card_points(stats, card_type, weights, rarity, mods, mvp_bonus) within 1e-9
        for every rarity (common/rare/epic/legendary), with and without modifiers, and with
        and without an MVP bonus (_mvp_bonus_delta)."""
        rng = random.Random(152)
        rarity = _rarity()
        mod_sets = [{}, {"kills": 10.0}, {"kills": 10.0, "gold_per_min": 15.0, "assists": 5.0}]
        for card_type, mods, mvp_on in itertools.product(RARITIES, mod_sets, (False, True)):
            for _ in range(20):
                stats = _random_stats(rng)
                mvp = fantasy_score(stats, _WEIGHTS) * _WEIGHTS["mvp_bonus_pct"] / 100 if mvp_on else 0.0
                parts = card_points_breakdown(stats, card_type, _WEIGHTS, rarity, mods, mvp)
                expected = _compute_card_points(stats, card_type, _WEIGHTS, rarity, mods, mvp_bonus=mvp)
                assert abs(_sum_parts(parts) - expected) < 1e-9, (card_type, mods, mvp_on)

    def test_card_points_breakdown_deaths_modifier_uses_death_contribution(self):
        """card_points_breakdown: a `deaths` modifier part is
        _death_contribution(deaths, weights) x pct/100 x (1 + rarity_mod), and the parts
        still sum to _compute_card_points within 1e-9."""
        rarity = _rarity()
        for card_type in RARITIES:
            for deaths in (0, 4, 20):  # 20 deaths floors the pool at 0
                stats = {"kills": 6, "deaths": deaths, "gold_per_min": 500}
                mods = {"deaths": 20.0, "kills": 10.0}
                parts = card_points_breakdown(stats, card_type, _WEIGHTS, rarity, mods, 0.0)
                r = rarity[f"mod_{card_type}"]
                assert parts["modifiers"]["deaths"] == pytest.approx(
                    _death_contribution(deaths, _WEIGHTS) * 20.0 / 100 * (1 + r), abs=1e-12)
                expected = _compute_card_points(stats, card_type, _WEIGHTS, rarity, mods)
                assert abs(_sum_parts(parts) - expected) < 1e-9

    def test_card_points_breakdown_part_formulas(self):
        """card_points_breakdown: raw == fantasy_score(stats), rarity == raw x rarity_mod,
        each modifier == weight x value x pct/100 x (1 + rarity_mod), mvp == mvp_bonus x
        (1 + rarity_mod), rarity_pct == rarity_mod x 100."""
        rarity = _rarity()
        stats = {"kills": 8, "assists": 3, "deaths": 2, "gold_per_min": 612.5}
        mods = {"kills": 10.0, "gold_per_min": 15.0}
        r = rarity["mod_epic"]
        parts = card_points_breakdown(stats, "epic", _WEIGHTS, rarity, mods, 1.25)
        raw = fantasy_score(stats, _WEIGHTS)
        assert parts["raw"] == pytest.approx(raw, abs=1e-12)
        assert parts["rarity"] == pytest.approx(raw * r, abs=1e-12)
        assert parts["modifiers"]["kills"] == pytest.approx(0.3 * 8 * 10.0 / 100 * (1 + r), abs=1e-12)
        assert parts["modifiers"]["gold_per_min"] == pytest.approx(0.002 * 612.5 * 15.0 / 100 * (1 + r), abs=1e-12)
        assert parts["mvp"] == pytest.approx(1.25 * (1 + r), abs=1e-12)
        assert parts["rarity_pct"] == pytest.approx(r * 100, abs=1e-12)

    def test_card_points_breakdown_common_no_mods_no_mvp_is_raw_only(self):
        """card_points_breakdown for a common card (rarity_common 0) with no modifiers and
        mvp_bonus 0: rarity == 0, modifiers == {}, mvp == 0, raw == _compute_card_points."""
        rarity = _rarity()
        stats = {"kills": 4, "deaths": 3, "gold_per_min": 450}
        parts = card_points_breakdown(stats, "common", _WEIGHTS, rarity, {}, 0.0)
        assert parts["rarity"] == 0
        assert parts["modifiers"] == {}
        assert parts["mvp"] == 0
        assert parts["raw"] == pytest.approx(_compute_card_points(stats, "common", _WEIGHTS, rarity, {}), abs=1e-12)

    def test_stat_labels_shared_and_image_imports_it(self):
        """Modifier labels reuse the card-image labels: a shared STAT_LABELS lives in
        scoring.py or card_utils.py, and backend/image.py no longer defines its own
        _STAT_LABELS_CARD dict (it imports the shared one); the API does not import image."""
        import scoring
        assert scoring.STAT_LABELS["gold_per_min"] == "GPM"
        for stat in scoring.SCORING_STATS + ["deaths"]:
            assert stat in scoring.STAT_LABELS, stat
        image_src = _read(os.path.join(_BACKEND_DIR, "image.py"))
        assert "_STAT_LABELS_CARD" not in image_src
        assert "from scoring import STAT_LABELS" in image_src
        router_src = _read(os.path.join(_BACKEND_DIR, "routers", "weekly_summary.py"))
        assert "from scoring import STAT_LABELS" in router_src
        assert not re.search(r"from image import [^\n]*STAT_LABELS", router_src)
        assert "import image" not in _read(os.path.join(_BACKEND_DIR, "card_utils.py"))
        assert "import image" not in _read(os.path.join(_BACKEND_DIR, "scoring.py"))

    # --- API (_build_roster_block via _build_week_summary) ---

    def test_build_week_summary_counted_card_has_breakdown_raw_and_steps(self, db):
        """Every counted card in a revealed week's roster.cards (GET /weekly-summary/{week_id})
        has `breakdown` with `raw` and a `steps` list covering its counted, scored games."""
        _seed(db)
        cards = _cards(db)
        counted = [c for c in cards if c["counted"]]
        assert [c["card_id"] for c in counted] == [1, 2]
        for c in counted:
            assert set(c["breakdown"]) == {"raw", "steps"}
            assert isinstance(c["breakdown"]["steps"], list)
        weights, _ = _load_weights(db)
        b = next(c for c in counted if c["card_id"] == 2)  # common, no modifiers, no MVP
        raw_exact = sum(fantasy_score({"kills": k, "deaths": d, "gold_per_min": g}, weights)
                        for k, d, g in ((1, 1, 300), (4, 3, 512), (0, 5, 280)))
        assert b["breakdown"]["raw"] == display_points(raw_exact)

    def test_build_week_summary_breakdown_step_order(self, db):
        """breakdown.steps[].kind order: "rarity" first (only when pct > 0), then one
        "modifier" per modifier in the card's modifier order, then one "mvp" per MVP game
        in game order."""
        _seed(db, a_mods=(("kills", 10.0), ("gold_per_min", 10.0)))
        steps = _card(db, 1)["breakdown"]["steps"]
        assert [s["kind"] for s in steps] == ["rarity", "modifier", "modifier", "mvp", "mvp"]
        card_mods = [m["stat"] for m in _card(db, 1)["modifiers"]]
        assert [s["stat"] for s in steps if s["kind"] == "modifier"] == card_mods
        assert [s["match_id"] for s in steps if s["kind"] == "mvp"] == [1, 3]  # game order

    def test_build_week_summary_breakdown_rarity_step_fields(self, db):
        """Rarity step: {"kind": "rarity", "label": <rarity name>, "pct": rarity_<type>,
        "points": display_points(...)}; omitted for a common card whose rarity bonus is 0."""
        _seed(db, a_type="legendary", b_type="common")
        weights, rarity = _load_weights(db)
        rar = _card(db, 1)["breakdown"]["steps"][0]
        assert rar["kind"] == "rarity" and rar["label"] == "Legendary"
        assert rar["pct"] == _WEIGHTS["rarity_legendary"]
        raw_exact = sum(fantasy_score({"kills": k, "deaths": d, "gold_per_min": g}, weights)
                        for k, d, g in ((5, 2, 437), (2, 1, 403), (7, 0, 611)))
        assert rar["points"] == display_points(raw_exact * rarity["mod_legendary"])
        assert all(s["kind"] != "rarity" for s in _card(db, 2)["breakdown"]["steps"])

    def test_build_week_summary_breakdown_modifier_step_fields(self, db):
        """Modifier step: {"kind": "modifier", "stat": stat_key, "label": STAT_LABELS label
        (e.g. "GPM"), "pct": the modifier row's pct, "points": display_points(...)}."""
        _seed(db, a_type="rare", a_mods=(("gold_per_min", 10.0),))
        weights, rarity = _load_weights(db)
        mod = next(s for s in _card(db, 1)["breakdown"]["steps"] if s["kind"] == "modifier")
        assert mod["stat"] == "gold_per_min" and mod["label"] == "GPM" and mod["pct"] == 10.0
        exact = sum(0.002 * g * 10.0 / 100 * (1 + rarity["mod_rare"]) for g in (437, 403, 611))
        assert mod["points"] == display_points(exact)

    def test_build_week_summary_two_mvp_games_give_two_mvp_steps_with_match_id(self, db):
        """A player who was MVP in two counted games gets two breakdown.steps with
        kind "mvp", each with that game's `match_id`, pct == mvp_bonus_pct and its own points."""
        _seed(db, a_type="epic", a_mods=())
        weights, rarity = _load_weights(db)
        mvps = [s for s in _card(db, 1)["breakdown"]["steps"] if s["kind"] == "mvp"]
        assert [s["match_id"] for s in mvps] == [1, 3]
        for s, (k, d, g) in zip(mvps, ((5, 2, 437), (7, 0, 611))):
            assert s["pct"] == _WEIGHTS["mvp_bonus_pct"] and s["label"] == "MVP"
            bonus = fantasy_score({"kills": k, "deaths": d, "gold_per_min": g}, weights) * 10.0 / 100
            exact = bonus * (1 + rarity["mod_epic"])
            assert abs(s["points"] - display_points(exact)) <= 0.1 + 1e-9  # last step holds the remainder
        assert mvps[0]["points"] != mvps[1]["points"]

    def test_build_week_summary_mvp_step_match_ids_are_in_games(self, db):
        """Each MVP step's `match_id` matches one of the card's games[].match_id so the UI
        can find the row; non-MVP games produce no MVP step."""
        _seed(db)
        card = _card(db, 1)
        game_ids = {g["match_id"] for g in card["games"]}
        mvp_games = {g["match_id"] for g in card["games"] if g["is_mvp"]}
        mvp_steps = {s["match_id"] for s in card["breakdown"]["steps"] if s["kind"] == "mvp"}
        assert mvp_steps <= game_ids
        assert mvp_steps == mvp_games == {1, 3}
        assert 2 in game_ids and 2 not in mvp_steps

    def test_build_week_summary_breakdown_exact_parts_sum_to_stored_points(self, db):
        """The exact (unrounded) parts summed over the card's counted, scored games equal
        the card's stored card_match_points sum within 1e-6."""
        _seed(db, a_mods=(("deaths", 10.0), ("kills", 10.0)))
        for a_type in RARITIES:
            db.get(Card, 1).card_type = a_type
            db.commit()
            card_points.rebuild_all(db)
            for card_id in (1, 2):
                assert abs(_exact_parts(db, card_id) - _stored(db, card_id, [1, 2, 3])) < 1e-6

    def test_build_week_summary_breakdown_rounded_raw_plus_steps_equals_week_points(self, db):
        """Rounded breakdown.raw + sum(steps[].points) == the card's week_points exactly;
        raw and steps are rounded with display_points and the remainder goes to the last step."""
        _seed(db)
        for c in _cards(db):
            if not c["counted"]:
                continue
            bd = c["breakdown"]
            total = bd["raw"] + sum(s["points"] for s in bd["steps"])
            assert abs(total - c["week_points"]) < 1e-9
            assert display_points(total) == c["week_points"]
            assert bd["raw"] == display_points(bd["raw"])
            for s in bd["steps"]:
                assert s["points"] == display_points(s["points"])

    def test_build_week_summary_breakdown_remainder_on_raw_when_no_steps(self, db):
        """A card with no steps (common, no modifiers, no MVP) has steps == [] and
        breakdown.raw == week_points (the rounding remainder goes to raw)."""
        _seed(db, b_type="common")
        b = _card(db, 2)
        assert b["breakdown"]["steps"] == []
        assert b["breakdown"]["raw"] == b["week_points"]
        assert b["week_points"] == display_points(_stored(db, 2, [1, 2, 3]))

    def test_build_week_summary_did_not_play_card_has_no_breakdown(self, db):
        """Failure path: a card in the "Did not play" group (e.g. subbed_out B after
        weeks.run_substitutions) has no `breakdown` key."""
        no_b = [(mid, start, exc, {p: v for p, v in players.items() if p != B})
                for mid, start, exc, players in _MATCHES]
        _seed(db, matches=no_b, substitute=True)
        cards = _cards(db)
        b = next(c for c in cards if c["card_id"] == 2)
        assert b["subbed_out"] and not b["counted"]
        assert "breakdown" not in b

    def test_build_week_summary_unrevealed_week_has_no_breakdown(self, db):
        """Failure path: _build_week_summary(db, week, revealed=False, user_id) returns no
        `breakdown` on any roster card."""
        _seed(db)
        cards = _cards(db, revealed=False)
        assert cards
        assert all("breakdown" not in c for c in cards)
        assert "breakdown" not in repr(cards)

    def test_build_week_summary_breakdown_excludes_excluded_matches(self, db):
        """Failure path: a match with excluded_from_scoring (outside scored_match_sql()) or
        outside the week window adds nothing to raw, modifiers or MVP steps."""
        extra = [
            (4, 400, True, {A: (HALLA, 20, 0, 900, True)}),     # excluded from scoring
            (5, 1500, False, {A: (HALLA, 20, 0, 900, True)}),   # week 2
        ]
        _seed(db, extra_matches=extra)
        card = _card(db, 1)
        bd = card["breakdown"]
        assert {s["match_id"] for s in bd["steps"] if s["kind"] == "mvp"} == {1, 3}
        weights, _ = _load_weights(db)
        raw_exact = sum(fantasy_score({"kills": k, "deaths": d, "gold_per_min": g}, weights)
                        for k, d, g in ((5, 2, 437), (2, 1, 403), (7, 0, 611)))
        assert bd["raw"] == display_points(raw_exact)
        assert abs(bd["raw"] + sum(s["points"] for s in bd["steps"]) - card["week_points"]) < 1e-9
        assert card["week_points"] == display_points(_stored(db, 1, [1, 2, 3]))

    def test_build_week_summary_subbed_in_card_has_breakdown(self, db):
        """A subbed_in bench card (after weeks.run_substitutions) is counted and gets a
        breakdown whose rounded raw + steps equal its week_points."""
        no_b = [(mid, start, exc, {p: v for p, v in players.items() if p != B})
                for mid, start, exc, players in _MATCHES]
        _seed(db, matches=no_b, substitute=True)
        c = _card(db, 3)
        assert c["subbed_in"] and c["counted"]
        bd = c["breakdown"]
        assert [s["kind"] for s in bd["steps"]] == ["rarity", "modifier"]
        assert abs(bd["raw"] + sum(s["points"] for s in bd["steps"]) - c["week_points"]) < 1e-9
        assert c["week_points"] == display_points(_stored(db, 3, [1, 2]))

    # --- static breakdown chips (_weeklySummaryRosterCardHtml) ---

    def test_roster_card_html_tag_row_raw_modifiers_then_status(self):
        """_weeklySummaryRosterCardHtml tag row, left to right: "RAW {raw}" .recap-chip,
        one .recap-chip per modifier step "{LABEL} +{pct}% +{points}", then the status tag
        ("SUBBED IN") last; no rarity chip in the row."""
        card = _fn_body(_js(), "_weeklySummaryRosterCardHtml")
        tags = card[card.index('<div class="weekly-summary-roster-tags">'):]
        tags = tags[:tags.index("</div>")]
        assert tags.index("${chips}") < tags.index("${statusTag}")
        chips = card[card.index("let chips = ''"):card.index("const mvpSteps")]
        assert chips.index('data-step="raw">RAW ') < chips.index("st.kind === 'modifier'")
        assert "_recapChipHtml(st, i, pending)" in chips
        assert "rarity" not in chips
        chip = _fn_body(_js(), "_recapChipHtml")
        assert "recap-chip" in chip and "toUpperCase()" in chip
        assert "+${_escHtml(_recapPct(step.pct))}%" in chip and " +${_escHtml(Number(step.points || 0).toFixed(1))}" in chip

    def test_roster_card_html_rarity_tag_removed_from_tag_row(self):
        """The separate rarity tag from #151 is removed from the tag row in favour of the
        rarity name at the thumbnail's foot (thumbnail keeps its rarity-coloured border)."""
        card = _fn_body(_js(), "_weeklySummaryRosterCardHtml")
        assert "rarityTag" not in card
        assert "weekly-summary-tag rarity" not in card
        thumb = card[card.index('<div class="weekly-summary-roster-thumb-col"'):card.index("const names")]
        assert 'class="weekly-summary-roster-thumb-rarity"' in thumb
        assert "${_escHtml(rarity.toUpperCase())}" in thumb
        css = _read(_STYLE_CSS_PATH)
        assert "border-color: var(--k-rarity-legendary)" in _css_rule(
            css, '.weekly-summary-roster-thumb[data-rarity="legendary"]')
        assert not _css_blocks(css, r"\.weekly-summary-tag\.rarity")

    def test_roster_card_html_rarity_caption_under_thumbnail(self):
        """Under the thumbnail, a caption in the rarity colour reads "+{pct}% +{points}"
        only when breakdown.steps has a rarity step; a common card has no caption."""
        card = _fn_body(_js(), "_weeklySummaryRosterCardHtml")
        assert "const rarityStep = steps.find(st => st.kind === 'rarity')" in card
        cap = card[card.index("const rarityCaption"):card.index("const thumb")]
        assert "rarityStep\n    ?" in cap and ": ''" in cap
        assert 'class="weekly-summary-roster-rarity-cap' in cap
        assert "+${_escHtml(_recapPct(rarityStep.pct))}% +${_escHtml(Number(rarityStep.points || 0).toFixed(1))}" in cap
        thumb = card[card.index("const thumb"):card.index("const names")]
        assert thumb.index("</button>") < thumb.index("${rarityCaption}")
        css = _read(_STYLE_CSS_PATH)
        assert "var(--k-rarity-legendary)" in _css_rule(
            css, '.weekly-summary-roster-rarity-cap[data-rarity="legendary"]')

    def test_roster_card_html_mvp_game_tag_shows_bonus(self):
        """In the game rows, an MVP game's tag reads "MVP +{points}" using the MVP step whose
        match_id matches that game; each MVP game shows its own bonus."""
        js = _js()
        card = _fn_body(js, "_weeklySummaryRosterCardHtml")
        assert "if (st.kind === 'mvp') mvpSteps[st.match_id] = st;" in card
        assert "_weeklySummaryGameHtml(g, mvpSteps[g.match_id], pending)" in card
        game = _fn_body(js, "_weeklySummaryGameHtml")
        assert "function _weeklySummaryGameHtml(g, mvpStep" in game
        assert '<span class="recap-mvp-bonus">+${_escHtml(Number(mvpStep.points || 0).toFixed(1))}</span>' in game
        assert "<span>MVP</span>${bonus}" in game
        assert 'data-match-id="${Number(g.match_id)}"' in game

    def test_roster_card_html_game_rows_below_tags_and_not_collapsed(self):
        """Game rows (#151) stay below the tag row and are always shown in full (no fold or
        collapse), during and after the animation."""
        card = _fn_body(_js(), "_weeklySummaryRosterCardHtml")
        revealed = card[card.rindex("return `"):]
        assert revealed.index("weekly-summary-roster-tags") < revealed.index("${games}")
        js = _js()
        for word in ("collapse", "fold", "<details", "max-height"):
            assert word not in js, word
        css = _recap_css()
        assert ".weekly-summary-games" not in css

    def test_recap_chip_row_wraps(self):
        """The chip row wraps when needed (flex-wrap: wrap on the tag row container)."""
        css = _read(_STYLE_CSS_PATH)
        assert "flex-wrap: wrap" in _css_rule(css, ".weekly-summary-roster-tags")

    def test_roster_card_html_escapes_breakdown_values(self):
        """Failure path: breakdown labels and values are passed through the escape helper
        in _weeklySummaryRosterCardHtml (no raw interpolation of step.label)."""
        js = _js()
        src = "".join(_fn_body(js, f) for f in (
            "_weeklySummaryRosterCardHtml", "_weeklySummaryGameHtml", "_recapChipHtml"))
        interpolations = re.findall(r"\$\{([^}]*)\}", src)
        raw = [i for i in interpolations
               if re.search(r"\b(step|st|rarityStep|mvpStep|breakdown)\.(label|pct|points|raw|stat)\b", i)
               and not re.match(r"\s*(_escHtml|Number)\(", i)]
        assert raw == []
        assert "_escHtml(String(step.label || '').toUpperCase())" in src

    def test_subbed_in_card_no_longer_tinted_orange(self):
        """The subbed-in .weekly-summary-roster-card loses the #151 tinted background and
        orange (accent) border; the "SUBBED IN" tag alone marks it, in a neutral tag colour."""
        css = _read(_STYLE_CSS_PATH)
        for sel, body in _css_blocks(css, r"subbed-in"):
            assert "accent" not in body, sel
        state = _css_rule(css, ".weekly-summary-tag.state")
        assert "accent" not in state
        assert "var(--fg-muted)" in state and "var(--border)" in state


# ---------------------------------------------------------------------------
# Story 2: Card-by-Card Reveal
# ---------------------------------------------------------------------------

class TestCardByCardReveal:

    def test_recap_reveals_counted_cards_in_reverse_roster_order_at_top(self):
        """The reveal controller iterates counted cards in reverse roster order and inserts
        each at the top of the My roster list (prepend), so the finished list is My Team order."""
        play = _fn_body(_js(), "_playRecap")
        assert "const counted = cards.filter(c => c.counted);" in play
        assert "for (let i = counted.length - 1; i >= 0; i--)" in play
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "body.prepend(slot)" in reveal

    def test_recap_slot_opens_from_zero_height_ease_out(self):
        """Entry: the new card's slot wrapper opens from height 0 at the top in about 340 ms
        with an ease-out, while the cards below shift down."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "slot.style.height = '0px';" in reveal
        assert "_recapWait(run, _RECAP_SLOT_MS)" in reveal
        assert "const _RECAP_SLOT_MS = 340;" in _js()
        slot = _css_rule(_read(_STYLE_CSS_PATH), ".recap-slot")
        assert "overflow: hidden" in slot
        assert "height 340ms var(--ease-out)" in slot

    def test_recap_card_slides_in_from_left_via_translatex(self):
        """Entry: the card slides in from the left edge of the column (transform: translateX)
        over about 420 ms, ease-out cubic, opacity 0 -> 1 over the first 60% of the slide."""
        css = _read(_STYLE_CSS_PATH)
        assert "transform: translateX(-100%)" in _css_rule(css, ".recap-slide")
        assert "opacity: 0" in _css_rule(css, ".recap-slide")
        slide_in = _css_rule(css, ".recap-slide.in")
        assert "transform 420ms cubic-bezier(0.33, 1, 0.68, 1)" in slide_in  # ease-out cubic
        assert "opacity 252ms" in slide_in  # 60% of 420 ms
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "el.classList.add('recap-current', 'recap-slide')" in reveal
        assert "el.classList.add('in')" in reveal
        assert "const _RECAP_SLIDE_MS = 420;" in _js()

    def test_recap_count_up_duration_clamped(self):
        """Count-up duration is clamp(1000 + raw x 35, 1000, 3000) ms (Math.min/Math.max);
        failure path: raw 0 still takes 1000 ms and a large raw caps at 3000 ms."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "const countMs = Math.min(Math.max(1000 + raw * 35, 1000), 3000);" in reveal
        clamp = lambda raw: min(max(1000 + raw * 35, 1000), 3000)
        assert clamp(0) == 1000 and clamp(-5) == 1000 and clamp(20) == 1700 and clamp(200) == 3000

    def test_recap_count_up_ease_in_with_scale_and_glow(self):
        """The count uses requestAnimationFrame with an ease-in (accelerating) curve from 0
        to breakdown.raw; the number's inline transform scale and orange text-shadow grow
        as it rises."""
        js = _js()
        assert "const _recapEaseIn = t => t * t * t;" in js
        tween = _fn_body(js, "_recapTween")
        assert "requestAnimationFrame(tick)" in tween
        reveal = _fn_body(js, "_recapRevealCard")
        count = reveal[reveal.index("const countMs"):reveal.index("if (!counted) return false;")]
        assert "_recapTween(run, countMs, _recapEaseIn" in count
        assert "raw * e" in count
        assert "num.style.transform = `scale(${1 + 0.25 * e})`" in count
        assert "num.style.textShadow = `0 0 ${Math.round(16 * e)}px var(--accent)`" in count
        assert "display: inline-block" in _css_rule(_read(_STYLE_CSS_PATH), ".recap-total")

    def test_recap_raw_chip_highlighted_during_count_then_lit(self):
        """The RAW .recap-chip has the .hl class for the whole count and shows the running
        value, then settles to .lit about 0.2 s after the count ends (not a flash at the end)."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        hl = reveal.index("rawChip.classList.add('hl')")
        count = reveal.index("_recapTween(run, countMs")
        wait = reveal.index("_recapWait(run, 200)")
        lit = reveal.index("rawChip.classList.add('lit')")
        assert hl < count < wait < lit
        assert "rawValue.textContent = v;" in reveal[count:wait]
        assert reveal.index("rawChip.classList.remove('hl')") > wait

    def test_recap_week_total_counts_from_zero_to_week_total(self):
        """The header week total starts at 0 and adds each card's week_points as that card
        finishes; at the end it equals roster.week_total."""
        play = _fn_body(_js(), "_playRecap")
        assert "let weekTotal = 0;" in play
        assert "total.textContent = `Week total ${_recapPts(0)} pts`;" in play
        loop = play[play.index("for (let i = counted.length - 1"):]
        assert loop.index("_recapRevealCard(run, body, card)") < loop.index("weekTotal += Number(card.week_points || 0)")
        assert "Number(roster.week_total || 0)" in loop
        assert "total.textContent = `Week total ${_recapPts(roster.week_total)} pts`;" in play

    def test_recap_did_not_play_group_appended_after_counted_cards(self):
        """After the counted cards, the "Did not play" group is appended without animation;
        failure path: did-not-play cards are never animated."""
        play = _fn_body(_js(), "_playRecap")
        assert "const didNotPlay = cards.filter(c => c.subbed_out);" in play
        loop_end = play.index("for (let i = counted.length - 1")
        append = play.index("body.insertAdjacentHTML('beforeend'")
        assert append > loop_end
        assert "didNotPlay.map(c => _weeklySummaryRosterCardHtml(c, true))" in play
        assert play.count("_recapRevealCard(") == 1
        assert play.index("_recapRevealCard(") > loop_end
        assert "didNotPlay" not in _fn_body(_js(), "_recapRevealCard")

    def test_recap_only_current_card_has_orange_border(self):
        """During the animation only the card being revealed carries the current-card class
        (orange border and glow); the class is removed when that card finishes."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "el.classList.add('recap-current'" in reveal
        assert "el.classList.remove('recap-current'" in reveal
        assert reveal.index("el.classList.add('recap-current'") < reveal.index("el.classList.remove('recap-current'")
        cur = _css_rule(_read(_STYLE_CSS_PATH), ".weekly-summary-roster-card.recap-current")
        assert "border-color: var(--accent)" in cur and "box-shadow" in cur

    def test_recap_results_column_not_blocked(self):
        """The Results column stays usable: the controller only touches the roster column
        (no pointer-events: none or aria-busy on the results column)."""
        js = _js()
        ctrl = js[js.index("// Reveal animation (issue #152)"):js.index("// Match results column")]
        assert "weeklySummaryContent" not in ctrl
        assert "pointer-events" not in ctrl
        for sel, body in _css_blocks(_recap_css(), r"."):
            if "recap-float" not in sel:
                assert "pointer-events" not in body, sel


# ---------------------------------------------------------------------------
# Story 3: Bonus Highlights
# ---------------------------------------------------------------------------

class TestBonusHighlights:

    def test_recap_steps_play_in_breakdown_order(self):
        """After the count-up, each entry of breakdown.steps plays in order: rarity, then the
        modifiers left to right, then MVP."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "const steps = breakdown.steps || [];" in reveal
        assert "for (let s = 0; s < steps.length; s++)" in reveal
        assert reveal.index("_recapTween(run, countMs") < reveal.index("for (let s = 0; s < steps.length; s++)")

    def test_recap_step_chip_pending_to_highlighted(self):
        """For each step its chip changes from .recap-chip.pending (dashed placeholder) to
        .recap-chip.hl (filled, glowing) with its label and "+points"."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        mod = reveal[reveal.index("step.kind === 'modifier'"):reveal.index("step.kind === 'mvp'")]
        assert "target.classList.remove('pending'); target.classList.add('hl');" in mod
        css = _read(_STYLE_CSS_PATH)
        assert "display: none" in _css_rule(css, ".recap-chip.pending .recap-chip-pts")
        assert "_recapChipHtml(st, i, pending)" in _fn_body(_js(), "_weeklySummaryRosterCardHtml")

    def test_recap_step_sets_card_total_at_once_with_pop(self):
        """At the same moment the card total jumps to its new value (no count-up tween), pops
        about 28% larger (scale ~1.28) and shrinks back over about 520 ms."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        loop = reveal[reveal.index("for (let s = 0; s < steps.length; s++)"):]
        assert "num.textContent =" in loop
        assert "_recapTween" not in loop  # jumps, no count-up
        assert "_recapRestartClass(num, 'recap-pop')" in loop
        css = _read(_STYLE_CSS_PATH)
        assert "recapPop 520ms" in _css_rule(css, ".recap-total.recap-pop")
        assert "scale(1.28)" in css[css.index("@keyframes recapPop"):]

    def test_recap_step_floating_points_label(self):
        """A small floating "+points" label rises from the card total and fades out (CSS
        class with transform/opacity transition or keyframes)."""
        fl = _fn_body(_js(), "_recapFloat")
        assert "f.className = 'recap-float';" in fl
        assert "f.textContent = `+${_recapPts(points)}`;" in fl
        assert "f.remove()" in fl
        assert "_recapFloat(ptsBox, step.points, rarity)" in _fn_body(_js(), "_recapRevealCard")
        css = _read(_STYLE_CSS_PATH)
        assert "recapFloat" in _css_rule(css, ".recap-float")
        kf = css[css.index("@keyframes recapFloat"):]
        kf = kf[:kf.index("\n}\n")]
        assert "translateY" in kf and "opacity: 0" in kf
        assert "position: relative" in _css_rule(css, ".weekly-summary-roster-pts")

    def test_recap_rarity_step_plays_on_thumbnail(self):
        """Rarity step: the thumbnail glows in the rarity colour and scales up slightly, its
        "+pct% +points" caption appears and the floating "+points" uses the rarity colour;
        the card's own border does not change."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        rar = reveal[reveal.index("step.kind === 'rarity'"):reveal.index("step.kind === 'modifier'")]
        assert "el.querySelector('.weekly-summary-roster-thumb-col')" in rar
        assert "target.classList.add('recap-rarity-glow')" in rar
        assert "cap.classList.remove('pending')" in rar
        assert "rarity = target.dataset.rarity" in rar
        assert "recap-current" not in rar  # the card's own border is unchanged
        css = _read(_STYLE_CSS_PATH)
        assert "scale(" in _css_rule(css, ".recap-rarity-glow .weekly-summary-roster-thumb")
        assert "var(--k-rarity-epic)" in _css_rule(
            css, '.recap-rarity-glow[data-rarity="epic"] .weekly-summary-roster-thumb')
        assert "var(--k-rarity-legendary)" in _css_rule(css, '.recap-float[data-rarity="legendary"]')

    def test_recap_modifier_step_chip_glows_orange(self):
        """Modifier step: the modifier's .recap-chip.hl uses the accent (orange) token
        background with a glow."""
        hl = _css_rule(_read(_STYLE_CSS_PATH), ".recap-chip.hl")
        assert "background: var(--accent)" in hl
        assert "box-shadow" in hl and "var(--accent)" in hl

    def test_recap_mvp_step_plays_on_game_row_by_match_id(self):
        """MVP step: the game row with the step's match_id is tinted orange and its MVP tag
        fills, glows and gains "+points"."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        mvp = reveal[reveal.index("step.kind === 'mvp'"):reveal.index("running += ")]
        assert '.weekly-summary-game[data-match-id="${Number(step.match_id)}"]' in mvp
        assert "target.classList.add('recap-mvp-active')" in mvp
        assert "tag.classList.remove('pending'); tag.classList.add('hl');" in mvp
        css = _read(_STYLE_CSS_PATH)
        assert "var(--accent-ghost)" in _css_rule(css, ".weekly-summary-game.recap-mvp-active")
        hl = _css_rule(css, ".weekly-summary-game-mvp.hl")
        assert "background: var(--accent)" in hl and "box-shadow" in hl
        assert "display: none" in _css_rule(css, ".weekly-summary-game-mvp.pending .recap-mvp-bonus")

    def test_recap_multiple_mvp_games_tick_separately(self):
        """A player MVP in several games gets one tick per MVP step, in game order, each with
        its own pop."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        loop = reveal[reveal.index("for (let s = 0; s < steps.length; s++)"):]
        # One iteration (pop, float, wait) per step, so each MVP step is its own tick.
        assert loop.count("_recapRestartClass(num, 'recap-pop')") == 1
        assert "_recapWait(run, _RECAP_STEP_MS)" in loop
        assert "step.match_id" in loop

    def test_recap_card_without_steps_goes_to_next_card(self):
        """Failure path: a card with breakdown.steps == [] (common, no modifiers, no MVP) goes
        straight to the next card with no highlight phase."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "const steps = breakdown.steps || [];" in reveal
        loop = reveal[reveal.index("for (let s = 0; s < steps.length; s++)"):]
        # All highlight waits live inside the steps loop, so an empty list adds no delay.
        after = reveal[reveal.index("rawChip.classList.add('lit')"):]
        assert after.count("_recapWait(") == loop.count("_recapWait(") == 1

    def test_recap_card_total_ends_at_week_points(self):
        """After the last step the card total equals its week_points (values come from the
        API's rounded numbers, not recomputed in JS)."""
        reveal = _fn_body(_js(), "_recapRevealCard")
        assert "s === steps.length - 1 ? _recapPts(card.week_points) : _recapPts(running)" in reveal
        assert "num.textContent = _recapPts(card.week_points);" in reveal
        assert "running += Number(step.points || 0);" in reveal

    def test_recap_chip_styles_use_tokens_only(self):
        """style.css: .recap-chip.pending uses a dashed var(--border) and dim text,
        .recap-chip.lit uses var(--bg-card-hi), .recap-chip.hl the accent or rarity colour
        with a glow; failure path: no hex colours in any .recap-chip rule."""
        css = _read(_STYLE_CSS_PATH)
        pending = _css_rule(css, ".recap-chip.pending")
        assert "dashed var(--border)" in pending and "var(--fg-dim)" in pending
        assert "var(--bg-card-hi)" in _css_rule(css, ".recap-chip.lit")
        assert "var(--accent)" in _css_rule(css, ".recap-chip.hl")
        for sel, body in _css_blocks(css, r"recap-chip"):
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), sel
        section = re.sub(r"/\*.*?\*/", "", _recap_css(), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", section)
        assert "rgba(" not in section
        assert "var(--r-pill)" not in section and "999px" not in section
        assert "border-radius: var(--r-sm)" in _css_rule(css, ".recap-chip")
        assert "border-left" not in section


# ---------------------------------------------------------------------------
# Story 4: Control and Accessibility
# ---------------------------------------------------------------------------

class TestControlAndAccessibility:

    def test_index_html_skip_and_replay_buttons_in_roster_header(self):
        """index.html: a "Skip" and a "Replay" button in the My roster column header."""
        html = _read(_INDEX_HTML_PATH)
        head = html[html.index('id="weeklySummaryRosterTitle"'):html.index('id="weeklySummaryRosterMeta"')]
        assert 'id="weeklyRecapSkip" onclick="skipWeeklyRecap()">Skip</button>' in head
        assert 'id="weeklyRecapReplay" onclick="replayWeeklyRecap()">Replay</button>' in head
        assert head.count('type="button"') == 2
        assert "display: none" in _css_rule(_read(_STYLE_CSS_PATH), ".weekly-recap-btn.hidden")

    def test_recap_skip_visible_while_playing_and_renders_finished_state(self):
        """Skip is shown while the animation plays; pressing it bumps the run id and renders
        the static finished state at once (all chips lit, totals final)."""
        js = _js()
        buttons = _fn_body(js, "_updateRecapButtons")
        assert "skip.classList.toggle('hidden', !_recapAnimation.playing)" in buttons
        skip = _fn_body(js, "skipWeeklyRecap")
        assert skip.index("_stopRecap()") < skip.index("_weeklySummaryRosterHtml(")
        assert "_renderWeeklySummaryRosterHeader(data)" in skip
        assert "_markRecapPlayed(data.week_id)" in skip
        stop = _fn_body(js, "_stopRecap")
        assert "_recapAnimation.runId += 1;" in stop

    def test_recap_replay_visible_when_idle_and_restarts(self):
        """Replay is shown when not playing; it clears the played mark for that week in
        memory only and runs the animation again from the start."""
        js = _js()
        buttons = _fn_body(js, "_updateRecapButtons")
        assert "replay.classList.toggle('hidden', _recapAnimation.playing || !playable" in buttons
        replay = _fn_body(js, "replayWeeklyRecap")
        assert "_playRecap(data)" in replay
        assert "localStorage" not in replay and "_markRecapPlayed" not in replay
        assert _fn_body(js, "_playRecap").split("\n")[1].strip() == "_stopRecap();"

    def test_recap_played_weeks_stored_per_user_in_localstorage(self):
        """Played week ids are stored in localStorage under one key per user (key includes the
        user id); _maybePlayRecap skips the animation for a played week."""
        js = _js()
        assert "return `weeklyRecapPlayed:${activeUserId ?? 'anon'}`;" in _fn_body(js, "_recapStorageKey")
        assert "localStorage.getItem(_recapStorageKey())" in _fn_body(js, "_recapPlayedWeeks")
        assert "localStorage.setItem(_recapStorageKey()" in _fn_body(js, "_markRecapPlayed")
        maybe = _fn_body(js, "_maybePlayRecap")
        assert "if (_recapPlayedWeeks().includes(weekId)) return;" in maybe
        assert "_markRecapPlayed(data.week_id)" in _fn_body(js, "_playRecap")

    def test_recap_localstorage_access_wrapped_in_try_catch(self):
        """Failure path: every localStorage read and write in app-weekly-summary.js is wrapped
        in try/catch, so unavailable storage just means the animation plays again."""
        js = _js()
        for m in re.finditer(r"localStorage\.", js):
            fn_start = js.rindex("\nfunction ", 0, m.start())
            before = js[fn_start:m.start()]
            assert "try {" in before, js[fn_start:m.start() + 40]
            after = js[m.start():js.index("\n}\n", m.start())]
            assert "catch (_)" in after
        assert js.count("localStorage.") == 2

    def test_recap_respects_prefers_reduced_motion_in_js(self):
        """_maybePlayRecap checks _prefersReducedMotion(); with prefers-reduced-motion: reduce
        nothing animates and the finished state is shown."""
        js = _js()
        maybe = _fn_body(js, "_maybePlayRecap")
        assert "if (_prefersReducedMotion()) return;" in maybe
        assert maybe.index("_prefersReducedMotion()") < maybe.index("_playRecap(data)")
        assert "_prefersReducedMotion()" in _fn_body(js, "replayWeeklyRecap")
        render = _fn_body(js, "renderWeeklySummaryContent")
        assert render.index("_weeklySummaryRosterHtml(roster, data.revealed)") < render.index("_maybePlayRecap(")

    def test_recap_reduced_motion_media_query_disables_transitions(self):
        """style.css: @media (prefers-reduced-motion: reduce) sets the recap chip, count,
        pop, slot and slide transitions/animations to none."""
        body = _media_body(_read(_STYLE_CSS_PATH), "prefers-reduced-motion: reduce")
        for sel in (".recap-chip", ".recap-slot", ".recap-slide.in", ".recap-total.recap-pop", ".recap-float"):
            assert sel in body, sel
        assert "transition: none" in body
        assert "animation: none" in body

    def test_close_weekly_summary_cancels_running_recap(self):
        """closeWeeklySummary bumps _recapAnimation.runId (stopping every wait and tween) so
        no timers or requestAnimationFrame loops keep running."""
        js = _js()
        assert "_stopRecap();" in _fn_body(js, "closeWeeklySummary")
        stop = _fn_body(js, "_stopRecap")
        assert "_recapAnimation.runId += 1;" in stop
        assert "_recapAnimation.cancels.forEach(cancel => cancel());" in stop
        assert "clearTimeout(id)" in _fn_body(js, "_recapWait")
        assert "cancelAnimationFrame(frame)" in _fn_body(js, "_recapTween")

    def test_select_weekly_summary_tab_cancels_running_recap(self):
        """selectWeeklySummaryTab (switching week tab / opening another week) bumps the run id
        and stops a running animation cleanly."""
        sel = _fn_body(_js(), "selectWeeklySummaryTab")
        assert sel.index("_stopRecap();") < sel.index("fetch(")

    def test_recap_waits_and_tweens_check_run_id(self):
        """Failure path: every wait and requestAnimationFrame tween in the reveal controller
        compares its captured run id with _recapAnimation.runId and returns when stale."""
        js = _js()
        assert "return run === _recapAnimation.runId;" in _fn_body(js, "_recapAlive")
        wait = _fn_body(js, "_recapWait")
        assert "if (!_recapAlive(run)) return Promise.resolve(false);" in wait
        assert "resolve(_recapAlive(run))" in wait
        tween = _fn_body(js, "_recapTween")
        assert "if (!_recapAlive(run)) return Promise.resolve(false);" in tween
        assert "if (!_recapAlive(run)) { _recapAnimation.cancels.delete(key); resolve(false); return; }" in tween
        reveal = _fn_body(js, "_recapRevealCard")
        awaits = re.findall(r"await (_recap\w+)\(", reveal)
        assert awaits and all(a in ("_recapWait", "_recapTween") for a in awaits)
        assert len(re.findall(r"if \(!await _recap(Wait|Tween)\(run", reveal)) + \
            reveal.count("const counted = await _recapTween(run") == len(awaits)
        assert "if (!counted) return false;" in reveal

    def test_recap_roster_body_aria_busy_while_animating(self):
        """While animating the roster body has aria-busy="true"; it is removed (or "false")
        when the animation finishes, is skipped or is cancelled."""
        js = _js()
        play = _fn_body(js, "_playRecap")
        assert "body.setAttribute('aria-busy', 'true');" in play
        assert "body.removeAttribute('aria-busy');" in play
        assert "body.removeAttribute('aria-busy');" in _fn_body(js, "_stopRecap")
        html = _read(_INDEX_HTML_PATH)
        assert 'id="weeklySummaryContent"' in html
        assert "weeklySummaryContent" not in play

    def test_recap_final_points_in_accessible_text_and_counter_aria_hidden(self):
        """Each card's final week_points are in its accessible text from the start (e.g.
        visually hidden text or aria-label), and the counting number is aria-hidden="true"."""
        card = _fn_body(_js(), "_weeklySummaryRosterCardHtml")
        assert '<span class="recap-total" aria-hidden="true">${_escHtml(shown)}</span>' in card
        assert '<span class="recap-sr">${_escHtml(Number(c.week_points || 0).toFixed(1))} points</span>' in card
        assert "const shown = pending ? '0.0' : _recapPts(c.week_points);" in card
        sr = _css_rule(_read(_STYLE_CSS_PATH), ".recap-sr")
        assert "position: absolute" in sr and "clip:" in sr
        raw_chip = card[card.index('data-step="raw">RAW '):card.index("steps.forEach((st, i)")]
        assert '<span class="recap-chip-raw" aria-hidden="true">' in raw_chip
        assert '<span class="recap-sr">${_escHtml(_recapPts(breakdown.raw))}</span>' in raw_chip
