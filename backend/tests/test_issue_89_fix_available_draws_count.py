"""
Tests for plan-issue-89-fix-available-draws-count.

Covers the two user stories from
markdown/plans/plan-issue-89-fix-available-draws-count.md. This is a
frontend-only bug fix (resolves GitHub issue #89) to `loadDeck()` in
`frontend/app-cards.js` (lines 358-377): the "X draws available" status line
(`#deckStatus`) currently sums `GET /deck`'s four per-rarity undrawn-combination
counts, which can show 300+ and disagrees with the correct, adjacent
`#drawCounter` element. The fix sources the status line from the user's token
balance (`_tokenBalance`, `frontend/app-globals.js`) instead — the same value
`#drawCounter` already uses via `updateTokenDisplay()` — and removes the
now-unused `GET /deck` fetch from `loadDeck()`. `GET /deck` itself is
unchanged and continues to serve the team-booster panel unmodified.

Every stub below fails with "not yet implemented" until the developer
implements the plan. Most stubs assert against `frontend/app-cards.js`,
`frontend/app-globals.js`, and `markdown/features/reference/draw-panel-redesign.md`
file contents (a frontend-only feature is still string/regex-checkable via
pytest, it just has no DB or endpoint surface to exercise for the fix itself).
One stub — confirming `GET /deck`'s contract is unchanged — exercises the
actual backend endpoint via a FastAPI TestClient, since that acceptance
criterion is explicitly about the backend surface being untouched:

  Story: Accurate Available Draws Count
    - `#deckStatus` derives its number from the user's token balance, not
      from `GET /deck`'s summed per-rarity undrawn-combination counts
    - Immediately after a successful standard or team-booster draw, the
      number decreases by 1 to match the new token balance from the draw
      response, with no page refresh needed
    - When the user has 0 tokens, the line shows "No draws available",
      matching `POST /draw`'s actual 409 draw-eligibility behavior at that
      point
    - Logged-out users are not shown a specific draws-available number
      derived from data that doesn't apply to them, mirroring the existing
      logged-out behavior of `#drawCounter`

  Story: Consistent Draw-Count Messaging
    - `#drawCounter` and `#deckStatus`'s "draws available" text derive from
      the same source of truth (`_tokenBalance`)
    - After a successful draw (standard or team-booster), both indicators
      update together in the same call, so they can never show conflicting
      numbers even momentarily
    - `GET /deck`'s response shape, and its use by the team-booster panel
      (`GET /deck/booster`, `loadBoosterTeams()`), are unaffected by this fix
      (failure case: the fix accidentally changes `/deck`'s contract or how
      the booster panel consumes it)
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
APP_CARDS_JS_PATH = os.path.join(FRONTEND_DIR, "app-cards.js")
APP_GLOBALS_JS_PATH = os.path.join(FRONTEND_DIR, "app-globals.js")

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DRAW_PANEL_DOC_PATH = os.path.join(
    REPO_ROOT, "markdown", "features", "reference", "draw-panel-redesign.md"
)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_function(js, name):
    """Return the full source of a top-level `async function {name}() { ... }`
    or `function {name}() { ... }` block, matched by brace-depth counting so
    nested braces inside the function body don't truncate the match."""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", js)
    assert m, f"{name}() not found in source"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    return js[start:i - 1]


# ---------------------------------------------------------------------------
# Story: Accurate Available Draws Count
# ---------------------------------------------------------------------------

class TestAccurateAvailableDrawsCount:

    def test_deck_status_line_derived_from_token_balance_not_deck_sum(self):
        """loadDeck() in frontend/app-cards.js no longer fetches GET /deck or
        sums its per-rarity values for #deckStatus; the "draws available"
        number is derived from `_tokenBalance` (frontend/app-globals.js)
        instead (failure case: `${API}/deck` still fetched by loadDeck(), or
        `#deckStatus` text still built from Object.values(deck).reduce(...))."""
        js = _read(APP_CARDS_JS_PATH)
        body = _extract_function(js, "loadDeck")
        assert "${API}/deck`" not in body, "loadDeck() must no longer fetch GET /deck"
        assert "Object.values(deck)" not in body, "loadDeck() must no longer sum a deck object"
        assert "_tokenBalance" in body, "loadDeck() must derive its total from _tokenBalance"

    def test_deck_status_decrements_immediately_after_standard_draw(self):
        """After a successful standard draw (drawCard() in app-cards.js),
        #deckStatus's "draws available" number decreases by 1 to match the
        new token balance returned in the /draw response, with no page
        refresh needed — i.e. loadDeck() (or the token-balance update it
        reads from) runs synchronously after updateTokenDisplay(data.tokens)
        in the draw success path."""
        js = _read(APP_CARDS_JS_PATH)
        body = _extract_function(js, "drawCard")
        update_idx = body.find("updateTokenDisplay(")
        load_deck_idx = body.find("loadDeck()")
        assert update_idx != -1, "drawCard() must call updateTokenDisplay(...)"
        assert load_deck_idx != -1, "drawCard() must call loadDeck()"
        assert update_idx < load_deck_idx, (
            "updateTokenDisplay(...) must run before loadDeck() in drawCard() "
            "so #deckStatus reflects the new token balance immediately"
        )

    def test_deck_status_decrements_immediately_after_booster_draw(self):
        """After a successful team-booster draw (_drawBoosterForTeam() in
        app-cards.js), #deckStatus's "draws available" number decreases to
        match the new token balance returned in the /draw/booster/{team_id}
        response, with no page refresh needed."""
        js = _read(APP_CARDS_JS_PATH)
        body = _extract_function(js, "_drawBoosterForTeam")
        update_idx = body.find("updateTokenDisplay(")
        load_deck_idx = body.find("loadDeck()")
        assert update_idx != -1, "_drawBoosterForTeam() must call updateTokenDisplay(...)"
        assert load_deck_idx != -1, "_drawBoosterForTeam() must call loadDeck()"
        assert update_idx < load_deck_idx, (
            "updateTokenDisplay(...) must run before loadDeck() in "
            "_drawBoosterForTeam() so #deckStatus reflects the new token "
            "balance immediately"
        )

    def test_deck_status_shows_no_draws_available_at_zero_tokens(self):
        """When _tokenBalance is 0, #deckStatus reads exactly "No draws
        available", matching the account's actual draw eligibility (POST
        /draw returns 409 "Not enough tokens" at this point) — no more
        disagreement between a large displayed count and an immediate
        real-world failure."""
        js = _read(APP_CARDS_JS_PATH)
        body = _extract_function(js, "loadDeck")
        assert '"No draws available"' in body
        # The ternary must gate on total > 0 (total <= 0, incl. 0, falls
        # through to "No draws available"), and total must derive from
        # _tokenBalance so a 0 balance yields total === 0.
        assert re.search(r"total\s*>\s*0", body), (
            "loadDeck() must only show a positive count when total > 0"
        )
        assert re.search(r"_tokenBalance\s*\?\?\s*0", body), (
            "loadDeck() must default total to 0 when _tokenBalance is unset"
        )

    def test_deck_status_hides_specific_count_for_logged_out_users(self):
        """Logged-out users (no activeUserId) are not shown a specific
        draws-available number derived from data that doesn't apply to them,
        mirroring #drawCounter's existing logged-out behavior in
        updateTokenDisplay() (frontend/app-globals.js)."""
        js = _read(APP_CARDS_JS_PATH)
        body = _extract_function(js, "loadDeck")
        # setStatus("deckStatus", ...) must be gated on activeUserId, not
        # just on the token total, so a logged-out user (activeUserId ===
        # null) always falls through to "No draws available" regardless of
        # any stray _tokenBalance value.
        assert re.search(r"activeUserId\s*&&\s*total\s*>\s*0", body), (
            "loadDeck()'s deckStatus ternary must require activeUserId "
            "before showing a specific draws-available count"
        )


# ---------------------------------------------------------------------------
# Story: Consistent Draw-Count Messaging
# ---------------------------------------------------------------------------

class TestConsistentDrawCountMessaging:

    def test_deck_counter_and_status_share_token_balance_source_of_truth(self):
        """#drawCounter (updateTokenDisplay() in frontend/app-globals.js) and
        #deckStatus's "draws available" text (loadDeck() in
        frontend/app-cards.js) both derive from the same `_tokenBalance`
        value, so they can never disagree (failure case: #deckStatus still
        computed from a separate /deck-derived total)."""
        globals_js = _read(APP_GLOBALS_JS_PATH)
        update_body = _extract_function(globals_js, "updateTokenDisplay")
        assert "_tokenBalance = balance" in update_body, (
            "updateTokenDisplay() must set the shared _tokenBalance global"
        )
        assert "drawCounter" in update_body, (
            "updateTokenDisplay() must still drive #drawCounter"
        )

        cards_js = _read(APP_CARDS_JS_PATH)
        deck_body = _extract_function(cards_js, "loadDeck")
        assert "_tokenBalance" in deck_body, (
            "loadDeck() must read the same _tokenBalance global for #deckStatus"
        )
        assert "${API}/deck`" not in deck_body, (
            "loadDeck() must not derive #deckStatus from a separate /deck-based total"
        )

    def test_both_draw_indicators_update_together_after_a_draw(self):
        """After a successful draw (standard via drawCard() or booster via
        _drawBoosterForTeam()), #drawCounter and #deckStatus update together
        within the same success-path call sequence (updateTokenDisplay()
        followed by loadDeck() reading the now-current _tokenBalance), so
        they can never show conflicting numbers even momentarily."""
        js = _read(APP_CARDS_JS_PATH)
        for fn_name in ("drawCard", "_drawBoosterForTeam"):
            body = _extract_function(js, fn_name)
            update_idx = body.find("updateTokenDisplay(")
            load_deck_idx = body.find("loadDeck()")
            assert update_idx != -1 and load_deck_idx != -1, (
                f"{fn_name}() must call both updateTokenDisplay(...) and loadDeck()"
            )
            assert update_idx < load_deck_idx, (
                f"{fn_name}() must call updateTokenDisplay(...) before loadDeck() "
                "so #drawCounter and #deckStatus update together, in order, within "
                "the same success path"
            )

    def test_draw_panel_redesign_doc_describes_token_balance_status_line_source(self):
        """markdown/features/reference/draw-panel-redesign.md's "Frontend
        change" and "Implementation notes" sections describe the corrected
        status-line source (_tokenBalance) and state that loadDeck() no
        longer fetches GET /deck, replacing the prior description that
        attributed the status line's draw count to GET /deck."""
        doc = _read(DRAW_PANEL_DOC_PATH)
        assert "_tokenBalance" in doc, (
            "doc must describe the status line as sourced from _tokenBalance"
        )
        assert "no longer fetches" in doc or "no longer fetch" in doc, (
            "doc must state that loadDeck() no longer fetches GET /deck"
        )
        # Guard against the stale description lingering unmodified.
        assert "summed" in doc or "sourced from the user's token balance" in doc, (
            "doc must explain the corrected (not the old summed-GET/deck) status line source"
        )

    def test_get_deck_endpoint_contract_and_booster_panel_usage_unchanged(self):
        """GET /deck's response shape (a {common, rare, epic, legendary}
        object of per-rarity undrawn-combination counts) is unaffected by
        this fix, and GET /deck/booster plus the team-booster panel's
        loadBoosterTeams() (which does not call loadDeck()) continue to work
        as before — this fix only changes how loadDeck()'s status line
        interprets data, not the /deck endpoint's contract or any other
        caller of it. Unlike the other stubs in this file, this one is free
        to exercise the actual GET /deck endpoint via a FastAPI TestClient
        once implemented, since it is asserting backend behavior explicitly
        required to stay unchanged."""
        import time

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from starlette.middleware.sessions import SessionMiddleware

        from database import Base, get_db
        from models import Player, User
        from auth import hash_password
        from routers import auth as auth_router
        from routers import cards as cards_router

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        def _override_get_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret-key-123")
        app.include_router(auth_router.router)
        app.include_router(cards_router.router)
        app.dependency_overrides[get_db] = _override_get_db

        db = Session()
        db.add(User(
            username="carol",
            email="carol@example.com",
            password_hash=hash_password("secret123"),
            tokens=5,
            created_at=int(time.time()),
        ))
        db.add(Player(id=1, name="PlayerOne"))
        db.commit()
        db.close()

        client = TestClient(app, raise_server_exceptions=True)

        login_resp = client.post(
            "/login", json={"username": "carol", "password": "secret123"}
        )
        assert login_resp.status_code == 200

        deck_resp = client.get("/deck")
        assert deck_resp.status_code == 200
        deck = deck_resp.json()
        assert set(deck.keys()) == {"common", "rare", "epic", "legendary"}
        # One player, none owned yet -> exactly one undrawn combo per rarity.
        assert deck == {"common": 1, "rare": 1, "epic": 1, "legendary": 1}

        booster_resp = client.get("/deck/booster")
        assert booster_resp.status_code == 200
        assert isinstance(booster_resp.json(), list)
