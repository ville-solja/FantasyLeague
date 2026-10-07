"""Architecture review fixes (2026-09-24):

1. Forwarded-header trust. The image used to run uvicorn with
   --forwarded-allow-ips "*", so any client that reached port 8000 could set
   X-Forwarded-For and appear as a new IP on every request, bypassing the
   per-IP rate limits. The image now trusts only private networks via
   FORWARDED_ALLOW_IPS.
2. Twitch MVP / token-drop uniqueness. twitch_mvp is unique on match_id and
   twitch_token_drops on (channel_id, series_id). MVPs are written with an
   upsert, and a drop is claimed by inserting its row before any tokens are
   granted, so concurrent confirmations cannot create duplicate MVP rows or pay
   out a drop twice.
"""
import asyncio
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import twitch
from migrate import _m026_twitch_mvp_drop_unique
from models import Match, Player, TwitchMVP, TwitchPresence, TwitchTokenDrop, User

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"


# ---------------------------------------------------------------------------
# 1. Forwarded-header trust
# ---------------------------------------------------------------------------

def _dockerfile_forwarded_allow_ips() -> str:
    m = re.search(r'^ENV FORWARDED_ALLOW_IPS="([^"]+)"', DOCKERFILE.read_text(), re.M)
    assert m, "Dockerfile must set FORWARDED_ALLOW_IPS"
    return m.group(1)


def _client_seen(peer_ip: str, xff: str) -> str:
    """Run uvicorn's proxy-header middleware with the image's trust list and
    return the client address the app (and the rate limiter) would see."""
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    mw = ProxyHeadersMiddleware(app, trusted_hosts=_dockerfile_forwarded_allow_ips())
    scope = {
        "type": "http", "scheme": "http", "client": (peer_ip, 50000),
        "headers": [(b"x-forwarded-for", xff.encode())],
    }
    asyncio.run(mw(scope, None, None))
    return seen["client"]


def test_dockerfile_does_not_trust_all_forwarded_headers():
    content = DOCKERFILE.read_text()
    assert '"--forwarded-allow-ips", "*"' not in content
    assert "*" not in _dockerfile_forwarded_allow_ips()
    assert '"--proxy-headers"' in content


def test_public_client_cannot_spoof_its_ip():
    assert _client_seen("203.0.113.7", "1.2.3.4") == "203.0.113.7"


@pytest.mark.parametrize("proxy_ip", ["172.18.0.1", "172.17.0.1", "10.0.0.5", "192.168.1.10", "127.0.0.1"])
def test_private_proxy_forwarded_client_is_used(proxy_ip):
    assert _client_seen(proxy_ip, "198.51.100.23") == "198.51.100.23"


def test_client_supplied_xff_prefix_is_ignored_behind_proxy():
    # The client sends "X-Forwarded-For: 1.2.3.4"; the proxy appends the real
    # address. The rightmost untrusted address wins, not the spoofed one.
    assert _client_seen("172.18.0.1", "1.2.3.4, 198.51.100.23") == "198.51.100.23"


def test_compose_bind_address_is_configurable():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert '"${APP_BIND_ADDRESS:-0.0.0.0}:8000:8000"' in compose


# ---------------------------------------------------------------------------
# 2. Twitch MVP / token-drop uniqueness
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(db):
    db.add(Match(match_id=1001))
    db.add_all([Player(id=1, name="Alpha"), Player(id=2, name="Beta")])
    db.add(User(id=10, username="viewer", password_hash="x", tokens=0, twitch_user_id="Uviewer"))
    import time as _t
    db.add(TwitchPresence(twitch_user_id="Uviewer", channel_id="chan", seen_at=int(_t.time())))
    db.commit()
    return db


def test_upsert_mvp_keeps_one_row_and_returns_previous(seeded):
    db = seeded
    assert twitch.upsert_mvp(db, 1001, 1, "chan") is None
    assert twitch.upsert_mvp(db, 1001, 2, "chan") == 1
    db.commit()
    rows = db.query(TwitchMVP).filter_by(match_id=1001).all()
    assert len(rows) == 1
    assert rows[0].player_id == 2


def test_twitch_mvp_rejects_second_row_for_same_match(seeded):
    db = seeded
    db.add(TwitchMVP(match_id=1001, player_id=1, channel_id="a", selected_at=1))
    db.commit()
    db.add(TwitchMVP(match_id=1001, player_id=2, channel_id="b", selected_at=2))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_claim_drop_succeeds_once(seeded):
    db = seeded
    assert twitch._claim_drop(db, "chan", "1001") is True
    assert twitch._claim_drop(db, "chan", "1001") is False
    assert twitch._claim_drop(db, "other-chan", "1001") is True
    db.commit()
    assert db.query(TwitchTokenDrop).filter_by(channel_id="chan", series_id="1001").count() == 1


def test_token_drop_grants_once_and_records_count(seeded):
    db = seeded
    winners, pool, already = twitch._execute_token_drop(db, "chan", 1001, {})
    db.commit()
    assert (winners, pool, already) == (["viewer"], 1, False)
    assert db.get(User, 10).tokens == 1
    assert db.query(TwitchTokenDrop).filter_by(channel_id="chan", series_id="1001").one().count == 1

    winners, pool, already = twitch._execute_token_drop(db, "chan", 1001, {})
    db.commit()
    assert already is True and winners == []
    assert db.get(User, 10).tokens == 1


def test_lost_claim_race_grants_no_tokens(seeded, monkeypatch):
    """The pre-check saw no drop, but a concurrent request claimed it first."""
    db = seeded
    monkeypatch.setattr(twitch, "_claim_drop", lambda *_a, **_k: False)
    winners, pool, already = twitch._execute_token_drop(db, "chan", 1001, {})
    db.commit()
    assert already is True and winners == []
    assert db.get(User, 10).tokens == 0


def test_migration_dedupes_and_adds_unique_indexes():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE twitch_mvp (id INTEGER PRIMARY KEY, match_id INTEGER, "
                          "player_id INTEGER, channel_id TEXT, selected_at INTEGER)"))
        conn.execute(text("CREATE TABLE twitch_token_drops (id INTEGER PRIMARY KEY, channel_id TEXT, "
                          "series_id TEXT, dropped_at INTEGER, count INTEGER)"))
        conn.execute(text("INSERT INTO twitch_mvp VALUES (1, 5, 1, 'c', 1), (2, 5, 2, 'c', 2), (3, 6, 3, 'c', 3)"))
        conn.execute(text("INSERT INTO twitch_token_drops VALUES (1, 'c', '5', 1, 4), (2, 'c', '5', 2, 4), "
                          "(3, 'd', '5', 3, 1)"))
        conn.commit()

        _m026_twitch_mvp_drop_unique(conn)

        mvps = conn.execute(text("SELECT id, match_id, player_id FROM twitch_mvp ORDER BY id")).fetchall()
        assert [tuple(r) for r in mvps] == [(2, 5, 2), (3, 6, 3)]  # newest selection kept
        drops = conn.execute(text("SELECT id FROM twitch_token_drops ORDER BY id")).fetchall()
        assert [r[0] for r in drops] == [1, 3]  # earliest drop per channel kept
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO twitch_mvp (match_id, player_id) VALUES (5, 9)"))
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO twitch_token_drops (channel_id, series_id) VALUES ('c', '5')"))
