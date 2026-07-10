"""
Tests for the Draw Panel Redesign plan (resolves GitHub issue #73).

Story 1 — Expose Draw Rates via the Config Endpoint
  GET /config must return a `draw_rates` object with normalised percentage
  values (common/rare/epic/legendary) that sum to 100 %.

Story 2 — View Drop Percentages in the Draw Panel (frontend)
  The panel heading must read "Draw" (not "Deck") and app-cards.js must
  read draw_rates from /config and render percentage strings.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pathlib
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_test_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _patch_db_modules(monkeypatch, test_engine, test_sf):
    """Patch database, enrich, ingest and seed to use the in-memory engine."""
    import database
    import enrich
    import ingest
    import seed
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_sf)
    monkeypatch.setattr(enrich, "SessionLocal", test_sf)
    monkeypatch.setattr(ingest, "SessionLocal", test_sf)
    monkeypatch.setattr(seed, "SessionLocal", test_sf)


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient backed by an in-memory SQLite database."""
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")

    test_engine = _make_test_engine()
    test_sf = sessionmaker(bind=test_engine)
    _patch_db_modules(monkeypatch, test_engine, test_sf)

    import importlib
    import main as main_module
    importlib.reload(main_module)
    main_module.engine = test_engine
    main_module.SessionLocal = test_sf

    from fastapi.testclient import TestClient
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def client_with_custom_weights(monkeypatch):
    """TestClient where the test controls Weight rows via a separate clean DB.

    lifespan_engine — receives create_all + seeding from the app startup
    test_engine     — fresh in-memory DB injected via get_db override; tests
                      insert custom Weight rows here without clashing with seeds
    """
    monkeypatch.setenv("AUTO_INGEST_LEAGUES", "")
    monkeypatch.setenv("DEBUG", "true")

    lifespan_engine = _make_test_engine()
    lifespan_sf = sessionmaker(bind=lifespan_engine)
    _patch_db_modules(monkeypatch, lifespan_engine, lifespan_sf)

    test_engine = _make_test_engine()
    test_sf = sessionmaker(bind=test_engine)

    import importlib
    import main as main_module
    importlib.reload(main_module)
    main_module.engine = lifespan_engine
    main_module.SessionLocal = lifespan_sf

    from database import Base, get_db
    from models import Weight

    # Create tables in the test engine (no seeding — test controls the data)
    Base.metadata.create_all(test_engine)

    def override_get_db():
        db = test_sf()
        try:
            yield db
        finally:
            db.close()

    main_module.app.dependency_overrides[get_db] = override_get_db

    from fastapi.testclient import TestClient
    with TestClient(main_module.app, raise_server_exceptions=True) as c:
        session = test_sf()
        yield c, session, Weight
        session.close()

    main_module.app.dependency_overrides.clear()


FRONTEND_DIR = pathlib.Path(__file__).parent.parent.parent / "frontend"


# ---------------------------------------------------------------------------
# Story 1 — Expose Draw Rates via the Config Endpoint
# ---------------------------------------------------------------------------

class TestConfigDrawRates:

    def test_get_config_returns_draw_rates_key(self, client):
        """GET /config response payload must contain a top-level `draw_rates` key."""
        resp = client.get("/config")
        assert resp.status_code == 200
        assert "draw_rates" in resp.json()

    def test_draw_rates_contains_all_four_rarity_keys(self, client):
        """draw_rates must have exactly the keys common, rare, epic, legendary."""
        data = client.get("/config").json()
        rates = data["draw_rates"]
        assert set(rates.keys()) == {"common", "rare", "epic", "legendary"}

    def test_draw_rates_values_are_floats(self, client):
        """Each draw_rates value must be a float (not an int or string)."""
        rates = client.get("/config").json()["draw_rates"]
        for key, val in rates.items():
            assert isinstance(val, float), f"{key} is {type(val)}, expected float"

    def test_draw_rates_sum_to_100_with_default_weights(self, client):
        """With standard seeded weights the four percentages must sum to 100.0."""
        rates = client.get("/config").json()["draw_rates"]
        total = sum(rates.values())
        assert abs(total - 100.0) < 0.1

    def test_draw_rates_rounded_to_one_decimal_place(self, client):
        """Each percentage value must be expressed to at most 1 decimal place."""
        rates = client.get("/config").json()["draw_rates"]
        for key, val in rates.items():
            # round-tripping through 1 decimal place must not change the value
            assert round(val, 1) == val, f"{key}={val} has more than 1 decimal place"

    def test_draw_rates_fallback_to_defaults_when_weights_missing(self, client_with_custom_weights):
        """When no draw_rate_* rows exist in the database the endpoint falls back
        to the seeded defaults: common=60, rare=25, epic=10, legendary=5."""
        c, session, Weight = client_with_custom_weights
        # No draw_rate_* rows inserted — expect defaults
        rates = c.get("/config").json()["draw_rates"]
        assert rates["common"] == 60.0
        assert rates["rare"] == 25.0
        assert rates["epic"] == 10.0
        assert rates["legendary"] == 5.0

    def test_draw_rates_fallback_defaults_sum_to_100(self, client_with_custom_weights):
        """The fallback default percentages (60/25/10/5) must themselves sum to 100."""
        c, session, Weight = client_with_custom_weights
        rates = c.get("/config").json()["draw_rates"]
        assert abs(sum(rates.values()) - 100.0) < 0.1

    def test_draw_rates_reflect_custom_weights_in_db(self, client_with_custom_weights):
        """When draw_rate_* Weight rows are present their values are normalised and
        returned instead of the defaults."""
        c, session, Weight = client_with_custom_weights
        for key, val in [
            ("draw_rate_common", 50.0),
            ("draw_rate_rare", 30.0),
            ("draw_rate_epic", 15.0),
            ("draw_rate_legendary", 5.0),
        ]:
            session.add(Weight(key=key, label=key, value=val))
        session.commit()

        rates = c.get("/config").json()["draw_rates"]
        # Total raw = 100, so normalised values equal raw values
        assert rates["common"] == 50.0
        assert rates["rare"] == 30.0
        assert rates["epic"] == 15.0
        assert rates["legendary"] == 5.0

    def test_draw_rates_normalise_unequal_raw_weights_to_100(self, client_with_custom_weights):
        """Raw weights that do not already sum to 100 must be normalised so the
        returned percentages always sum to 100."""
        c, session, Weight = client_with_custom_weights
        for key, val in [
            ("draw_rate_common", 6.0),
            ("draw_rate_rare", 2.5),
            ("draw_rate_epic", 1.0),
            ("draw_rate_legendary", 0.5),
        ]:
            session.add(Weight(key=key, label=key, value=val))
        session.commit()

        rates = c.get("/config").json()["draw_rates"]
        assert abs(sum(rates.values()) - 100.0) < 0.2

    def test_get_config_still_returns_existing_fields_alongside_draw_rates(self, client):
        """Adding draw_rates must not remove token_name, initial_tokens,
        app_version, app_release, or team_booster_cost from the response."""
        data = client.get("/config").json()
        for field in ("token_name", "initial_tokens", "app_version", "app_release", "team_booster_cost"):
            assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Story 2 — View Drop Percentages in the Draw Panel (frontend)
# ---------------------------------------------------------------------------

class TestDrawPanelFrontend:

    def test_index_html_panel_heading_reads_draw_not_deck(self):
        """The panel heading in index.html must be 'Draw', not 'Deck'."""
        html = (FRONTEND_DIR / "index.html").read_text()
        assert "<h2>Draw</h2>" in html

    def test_index_html_does_not_contain_deck_heading(self):
        """index.html must not contain an <h2>Deck</h2> heading (case-sensitive)."""
        html = (FRONTEND_DIR / "index.html").read_text()
        assert "<h2>Deck</h2>" not in html

    def test_index_html_retains_deck_common_id_for_js_targeting(self):
        """The element with id='deck-common' must still be present so that
        app-cards.js can write the percentage into it without refactoring."""
        html = (FRONTEND_DIR / "index.html").read_text()
        assert 'id="deck-common"' in html

    def test_index_html_retains_deck_rare_id_for_js_targeting(self):
        """The element with id='deck-rare' must still be present."""
        html = (FRONTEND_DIR / "index.html").read_text()
        assert 'id="deck-rare"' in html

    def test_index_html_retains_deck_epic_id_for_js_targeting(self):
        """The element with id='deck-epic' must still be present."""
        html = (FRONTEND_DIR / "index.html").read_text()
        assert 'id="deck-epic"' in html

    def test_index_html_retains_deck_legendary_id_for_js_targeting(self):
        """The element with id='deck-legendary' must still be present."""
        html = (FRONTEND_DIR / "index.html").read_text()
        assert 'id="deck-legendary"' in html

    def test_app_cards_js_load_deck_fetches_config_endpoint(self):
        """loadDeck() in app-cards.js must fetch /config (to obtain draw_rates),
        not only /deck."""
        js = (FRONTEND_DIR / "app-cards.js").read_text()
        assert "/config" in js

    def test_app_cards_js_load_deck_writes_percentage_string_to_deck_elements(self):
        """loadDeck() must write a string containing '%' into the deck-{r} elements
        (e.g. '60%'), not a plain count."""
        js = (FRONTEND_DIR / "app-cards.js").read_text()
        assert "'%'" in js or '"%"' in js or "`%`" in js or "rates[r]}%" in js

    def test_app_cards_js_load_deck_still_fetches_deck_endpoint_for_status_line(self):
        """loadDeck() must still fetch /deck so the 'X draws available' status
        line remains functional."""
        js = (FRONTEND_DIR / "app-cards.js").read_text()
        assert "/deck" in js

    def test_app_cards_js_load_deck_has_fallback_rates_when_config_missing(self):
        """loadDeck() must define a fallback for draw_rates (e.g. cfg.draw_rates ||
        { common: 60, rare: 25, epic: 10, legendary: 5 }) so the panel degrades
        gracefully if /config does not return the key."""
        js = (FRONTEND_DIR / "app-cards.js").read_text()
        assert "cfg.draw_rates ||" in js or "cfg.draw_rates||" in js
