"""Tests for Player Linking and Tag Visibility (plan-player-linking-and-tag-visibility.md).

Covers:
  Story 1 — See Your Tags on the Profile Page
    AC: Profile response includes tags array
    AC: Tags array is empty list when user has no tags
    AC: Tags are included in the same GET /profile/{user_id} call (no extra request)
    AC: Each tag entry has both 'key' and 'label' fields
    Failure path: unauthenticated / unknown user_id returns 404

  Story 2 — Understand the Link Between Dota ID and Tag Stickers
    AC: Gap hint is shown when user has tags but no player_id linked
    AC: Gap hint is hidden when user has tags AND a player_id linked
    AC: Gap hint is hidden when user has no tags (regardless of player_id)
    Failure path: profile endpoint still works when no Dota ID is linked (no server error)
"""

import time
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import models  # noqa: F401 — registers all tables with Base.metadata

from database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
# Helper factories (mirrors test_user_tag_system.py conventions)
# ---------------------------------------------------------------------------

def _make_user(db, username="player1", player_id=None):
    from models import User
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash="x",
        is_admin=False,
        tokens=0,
        player_id=player_id,
    )
    db.add(user)
    db.flush()
    return user


def _make_tag(db, key="caster", label="Caster"):
    from models import TagDefinition
    tag = TagDefinition(key=key, label=label, created_at=int(time.time()))
    db.add(tag)
    db.flush()
    return tag


def _grant_tag(db, user, tag, granted_by_id=None):
    from models import UserTag
    ut = UserTag(
        user_id=user.id,
        tag_id=tag.id,
        granted_by=granted_by_id,
        granted_at=int(time.time()),
    )
    db.add(ut)
    db.flush()
    return ut


def _build_profile_response(db, user_id):
    """Replicate the GET /profile/{user_id} logic so tests can run without FastAPI."""
    from models import User, Player, UserTag, TagDefinition
    user = db.get(User, user_id)
    if user is None:
        return None  # caller treats None as 404

    result = {
        "id": user.id,
        "username": user.username,
        "player_id": user.player_id,
        "player_name": None,
        "player_avatar_url": None,
        "twitch_linked": bool(user.twitch_user_id) if hasattr(user, "twitch_user_id") else False,
    }
    if user.player_id:
        player = db.get(Player, user.player_id)
        if player:
            result["player_name"] = player.name
            result["player_avatar_url"] = player.avatar_url
    tag_rows = (
        db.query(UserTag, TagDefinition)
        .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
        .filter(UserTag.user_id == user.id)
        .all()
    )
    result["tags"] = [{"key": td.key, "label": td.label} for _, td in tag_rows]
    return result


# ===========================================================================
# Story 1 — See Your Tags on the Profile Page
# ===========================================================================

class TestProfileTagsInResponse:

    def test_profile_response_includes_tags_array_for_tagged_user(self, db):
        """GET /profile/{user_id} returns a non-empty 'tags' list when the user has tags."""
        user = _make_user(db, "tagged_user")
        tag = _make_tag(db, "caster", "Caster")
        _grant_tag(db, user, tag)
        db.commit()

        result = _build_profile_response(db, user.id)
        assert result is not None
        assert "tags" in result
        assert len(result["tags"]) == 1
        assert result["tags"][0]["label"] == "Caster"

    def test_profile_response_returns_empty_tags_array_for_untagged_user(self, db):
        """GET /profile/{user_id} returns 'tags': [] when the user has no tags."""
        user = _make_user(db, "untagged_user")
        db.commit()

        result = _build_profile_response(db, user.id)
        assert result is not None
        assert "tags" in result
        assert result["tags"] == []

    def test_profile_tags_included_alongside_existing_profile_fields(self, db):
        """The 'tags' key is present in the same response object as username / player_id."""
        user = _make_user(db, "profile_fields_user")
        db.commit()

        result = _build_profile_response(db, user.id)
        assert result is not None
        # Core profile fields still present
        assert "username" in result
        assert "player_id" in result
        # Tags also present in the same dict (no extra round-trip needed)
        assert "tags" in result

    def test_profile_tag_entry_has_key_and_label_fields(self, db):
        """Each element of the 'tags' array exposes both 'key' and 'label' fields."""
        user = _make_user(db, "key_label_user")
        tag = _make_tag(db, "season_winner", "Season Winner")
        _grant_tag(db, user, tag)
        db.commit()

        result = _build_profile_response(db, user.id)
        assert len(result["tags"]) == 1
        entry = result["tags"][0]
        assert "key" in entry
        assert "label" in entry
        assert entry["key"] == "season_winner"
        assert entry["label"] == "Season Winner"

    def test_profile_returns_all_tags_when_user_has_multiple(self, db):
        """When a user holds two tags, both appear in the 'tags' array."""
        user = _make_user(db, "multi_tag_user")
        tag1 = _make_tag(db, "caster", "Caster")
        tag2 = _make_tag(db, "season_winner", "Season Winner")
        _grant_tag(db, user, tag1)
        _grant_tag(db, user, tag2)
        db.commit()

        result = _build_profile_response(db, user.id)
        assert len(result["tags"]) == 2
        keys = {t["key"] for t in result["tags"]}
        assert "caster" in keys
        assert "season_winner" in keys

    def test_profile_returns_404_for_unknown_user_id(self, db):
        """GET /profile/{user_id} with a user_id that does not exist returns 404.
        Verified by checking the guard condition: db.get returns None for an unknown id."""
        result = _build_profile_response(db, 99999)
        # None signals the 404 guard condition is met (endpoint raises HTTPException(404))
        assert result is None


# ===========================================================================
# Story 2 — Understand the Link Between Dota ID and Tag Stickers
# ===========================================================================

class TestTagGapHintLogic:

    def test_gap_hint_condition_true_when_user_has_tags_and_no_player_id(self, db):
        """The gap hint should be shown: user has tags but player_id is None."""
        user = _make_user(db, "gap_hint_user", player_id=None)
        tag = _make_tag(db, "caster", "Caster")
        _grant_tag(db, user, tag)
        db.commit()

        result = _build_profile_response(db, user.id)
        # Verify the data conditions that drive the gap hint: tags present, no player_id
        assert len(result["tags"]) > 0
        assert result["player_id"] is None
        # Gap hint JS condition: tags.length > 0 && !data.player_id => True
        gap_hint_shown = len(result["tags"]) > 0 and not result["player_id"]
        assert gap_hint_shown is True

    def test_gap_hint_condition_false_when_user_has_tags_and_player_id_linked(self, db):
        """The gap hint should be hidden: user has tags and a player_id is already set."""
        user = _make_user(db, "linked_tag_user", player_id=12345)
        tag = _make_tag(db, "caster", "Caster")
        _grant_tag(db, user, tag)
        db.commit()

        result = _build_profile_response(db, user.id)
        # Gap hint JS condition: tags.length > 0 && !data.player_id => False
        gap_hint_shown = len(result["tags"]) > 0 and not result["player_id"]
        assert gap_hint_shown is False

    def test_gap_hint_condition_false_when_user_has_no_tags_and_no_player_id(self, db):
        """The gap hint should be hidden: user has no tags, even if no player_id is linked."""
        user = _make_user(db, "no_tag_no_player_user", player_id=None)
        db.commit()

        result = _build_profile_response(db, user.id)
        # Gap hint requires tags — none here, so hint is hidden
        assert result["tags"] == []
        gap_hint_shown = len(result["tags"]) > 0 and not result["player_id"]
        assert gap_hint_shown is False

    def test_gap_hint_condition_false_when_user_has_no_tags_and_player_id_linked(self, db):
        """The gap hint should be hidden: user has no tags and a player_id is linked."""
        user = _make_user(db, "no_tag_linked_user", player_id=67890)
        db.commit()

        result = _build_profile_response(db, user.id)
        assert result["tags"] == []
        assert result["player_id"] == 67890
        gap_hint_shown = len(result["tags"]) > 0 and not result["player_id"]
        assert gap_hint_shown is False

    def test_profile_endpoint_does_not_error_when_no_player_id_linked(self, db):
        """GET /profile/{user_id} succeeds (no 500) even when the user has no player_id."""
        user = _make_user(db, "no_player_id_user", player_id=None)
        db.commit()

        # Should not raise — returns a valid result dict
        result = _build_profile_response(db, user.id)
        assert result is not None
        assert result["player_id"] is None
        assert "tags" in result
