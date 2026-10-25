"""Tests for the Card Team Logo Placeholder feature
(plan-issue-107-card-team-logo-placeholder.md).

Covers the single user story in that plan:
  - Blank Placeholder for Missing Team Logo

`backend/image.py::generate_card_image` currently skips pasting anything into the
team-logo badge slot when `_load_team_logo_for_card` returns `None` (no local
Dotabuff PNG cache and no usable `logo_url`), leaving the slot unpainted. The fix
adds `_blank_logo_placeholder(diameter)` — a solid black circular RGBA image — and
falls back to it in `generate_card_image` so the badge slot always shows something,
using the exact same circular crop/size/position as a real logo. Player avatar
rendering (the big circle) is unaffected; only the team-logo (small circle) slot
gets this treatment.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import image


def _centre(slot):
    return ((slot[0] + slot[2]) // 2, (slot[1] + slot[3]) // 2)


# ===========================================================================
# Story: Blank Placeholder for Missing Team Logo
# ===========================================================================

class TestBlankPlaceholderForMissingTeamLogo:

    def test_generate_card_image_paints_black_circle_when_team_logo_missing(self):
        """AC: when neither the local Dotabuff PNG cache nor `logo_url` resolves to a
        usable image, the team logo slot is filled with a solid black circular
        placeholder instead of being left unpainted."""
        img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Nonexistent Team XYZ 12345",
            team_logo_url=None,
        )
        # Centre of the badge slot: previously unpainted (would show the dark base
        # colour), now filled with the solid black placeholder.
        assert img.getpixel(_centre(image._LOGO_SLOT)) == (0, 0, 0, 255)

    def test_blank_logo_placeholder_matches_real_logo_size_and_position(self, monkeypatch):
        """AC: the placeholder uses the same size and position as a real team logo,
        so the card layout is identical either way (issue #218: the full 100 x 60
        logo slot, no circle crop)."""
        slot = image._LOGO_SLOT
        size = (slot[2] - slot[0], slot[3] - slot[1])

        def fake_logo(team_name, team_logo_url, d):
            assert d == size
            return image.Image.new("RGBA", d, (0, 200, 0, 255))

        monkeypatch.setattr(image, "_load_team_logo_for_card", fake_logo)
        real_logo_img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Some Real Team",
            team_logo_url="https://example.test/logo.png",
        )
        monkeypatch.undo()

        placeholder_img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Nonexistent Team XYZ 12345",
            team_logo_url=None,
        )

        # Same position for both — a real logo's colour, the placeholder's black.
        assert real_logo_img.getpixel(_centre(slot)) == (0, 200, 0, 255)
        assert placeholder_img.getpixel(_centre(slot)) == (0, 0, 0, 255)

        # Same size: both fill the slot to its corners (no circle crop) and stop at
        # its edge, where the template's type-line frame is identical for both.
        for corner in ((slot[0], slot[1]), (slot[2] - 1, slot[3] - 1)):
            assert real_logo_img.getpixel(corner) == (0, 200, 0, 255)
            assert placeholder_img.getpixel(corner) == (0, 0, 0, 255)
        outside = (slot[2], (slot[1] + slot[3]) // 2)
        assert real_logo_img.getpixel(outside) == placeholder_img.getpixel(outside)
        assert real_logo_img.getpixel(outside) != (0, 200, 0, 255)

    def test_generate_card_image_placeholder_replaced_once_logo_becomes_available(self, monkeypatch):
        """AC: once a team logo becomes available (local cache populated via ingest,
        or `logo_url` set), it replaces the placeholder on the next card image
        request — no cache to invalidate, since the image is generated fresh every
        request."""
        centre = _centre(image._LOGO_SLOT)

        # First request: no logo resolvable yet — placeholder shows.
        before_img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Team Pending Logo",
            team_logo_url=None,
        )
        assert before_img.getpixel(centre) == (0, 0, 0, 255)

        # Simulate the logo becoming available (ingest populated the local cache,
        # or an admin set logo_url) — the very next request should use it instead.
        def fake_logo(team_name, team_logo_url, d):
            return image.Image.new("RGBA", d, (10, 20, 230, 255))

        monkeypatch.setattr(image, "_load_team_logo_for_card", fake_logo)
        after_img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Team Pending Logo",
            team_logo_url=None,
        )
        assert after_img.getpixel(centre) == (10, 20, 230, 255)

    def test_generate_card_image_player_avatar_slot_unaffected_by_logo_placeholder(self):
        """AC: player avatar behaviour is unchanged — only the team logo slot gets
        the new placeholder treatment; a missing avatar still leaves the big circle
        unpainted rather than gaining a black placeholder of its own."""
        img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Nonexistent Team XYZ 12345",
            team_logo_url=None,
        )
        # No avatar and no player-avatar placeholder exists — the portrait slot stays
        # the plain dark base colour, not black.
        assert img.getpixel(_centre(image._PORTRAIT_SLOT)) == (35, 37, 40, 255)
