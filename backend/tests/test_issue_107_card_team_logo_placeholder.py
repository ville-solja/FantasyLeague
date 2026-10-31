"""Tests for the Card Team Logo Placeholder feature
(plan-issue-107-card-team-logo-placeholder.md).

Covers the single user story in that plan:
  - Blank Placeholder for Missing Team Logo

Rewritten for plan-card-art-accolade-redesign.md: the team-logo slot is no longer a
104 px circle (`_SMALL_CIRCLE`) but an aspect-fit box (`image._LOGO_BOX`). When
`_load_team_logo_for_card` resolves to nothing (no local Dotabuff PNG cache and no
usable `logo_url`), `generate_card_image` falls back to
`_blank_logo_placeholder(w, h)` — a solid black RGBA image sized to the box, pasted
with the same box-centred compositing as a real (aspect-fit) logo — so the badge slot
always shows something. Player avatar rendering (the photo slot) is unaffected; only
the team-logo box gets this treatment.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import image


# ===========================================================================
# Story: Blank Placeholder for Missing Team Logo
# ===========================================================================

class TestBlankPlaceholderForMissingTeamLogo:

    def test_generate_card_image_paints_black_box_when_team_logo_missing(self):
        """AC: when neither the local Dotabuff PNG cache nor `logo_url` resolves to a
        usable image, the team logo slot is filled with a solid black placeholder
        instead of being left unpainted."""
        img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Nonexistent Team XYZ 12345",
            team_logo_url=None,
        )
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        # Centre of the badge slot: previously unpainted (would show the template's
        # own fill), now filled with the solid black placeholder.
        assert img.getpixel(((lx0 + lx1) // 2, (ly0 + ly1) // 2)) == (0, 0, 0, 255)

    def test_blank_logo_placeholder_matches_real_logo_box_size_and_position(self, monkeypatch):
        """AC: the placeholder uses the same box, size, and position as a real team
        logo, so the card layout is identical either way."""
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        lw, lh = lx1 - lx0, ly1 - ly0

        def fake_logo(team_name, team_logo_url, size):
            w, h = size
            assert (w, h) == (lw, lh)
            return image.Image.new("RGBA", (w, h), (0, 200, 0, 255))

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

        # Same centre position for both — a real logo's colour, the placeholder's black.
        cxy = ((lx0 + lx1) // 2, (ly0 + ly1) // 2)
        assert real_logo_img.getpixel(cxy) == (0, 200, 0, 255)
        assert placeholder_img.getpixel(cxy) == (0, 0, 0, 255)

        # Same box size/position: a corner just outside the box shows through to
        # whatever the template paints there — identical for both images, since
        # neither the real logo colour nor the placeholder's black extends there.
        corner = (lx0 - 4, ly0 - 4)
        assert real_logo_img.getpixel(corner) == placeholder_img.getpixel(corner)
        assert real_logo_img.getpixel(corner) != (0, 200, 0, 255)
        assert placeholder_img.getpixel(corner) != (0, 0, 0, 255)

    def test_generate_card_image_placeholder_replaced_once_logo_becomes_available(self, monkeypatch):
        """AC: once a team logo becomes available (local cache populated via ingest,
        or `logo_url` set), it replaces the placeholder on the next card image
        request — no cache to invalidate, since the image is generated fresh every
        request."""
        lx0, ly0, lx1, ly1 = image._LOGO_BOX
        cxy = ((lx0 + lx1) // 2, (ly0 + ly1) // 2)

        # First request: no logo resolvable yet — placeholder shows.
        before_img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Team Pending Logo",
            team_logo_url=None,
        )
        assert before_img.getpixel(cxy) == (0, 0, 0, 255)

        # Simulate the logo becoming available (ingest populated the local cache,
        # or an admin set logo_url) — the very next request should use it instead.
        def fake_logo(team_name, team_logo_url, size):
            return image.Image.new("RGBA", size, (10, 20, 230, 255))

        monkeypatch.setattr(image, "_load_team_logo_for_card", fake_logo)
        after_img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Team Pending Logo",
            team_logo_url=None,
        )
        assert after_img.getpixel(cxy) == (10, 20, 230, 255)

    def test_generate_card_image_player_photo_slot_unaffected_by_logo_placeholder(self):
        """AC: player photo behaviour is unchanged — only the team logo slot gets
        the new placeholder treatment; a missing photo still leaves the slot
        unpainted (showing the template) rather than gaining a black placeholder of
        its own."""
        img = image.generate_card_image(
            card_type="common",
            player_name="Test Player",
            avatar_url=None,
            team_name="Nonexistent Team XYZ 12345",
            team_logo_url=None,
        )
        template = image._load_template("common", False)
        px0, py0, _, _ = image._PHOTO_SLOT
        xy = (px0 + 10, py0 + 10)
        # No photo and no photo-slot placeholder exists — the slot stays whatever the
        # bare template paints there, not black.
        assert img.getpixel(xy) == template.getpixel(xy)
        assert img.getpixel(xy) != (0, 0, 0, 255)
