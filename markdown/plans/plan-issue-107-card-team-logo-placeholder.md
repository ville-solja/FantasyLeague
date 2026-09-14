# Plan: Card Team Logo Placeholder

## Context
Card images currently leave the team-logo badge slot unpainted whenever no logo can be
resolved for a team — `backend/image.py::_load_team_logo_for_card` returns `None` when a team
has neither a locally-scraped Dotabuff PNG nor a usable `logo_url`, and
`generate_card_image`'s compositing step simply skips pasting anything in that case. This is
common pre-season, before a team's first match has been ingested and its logo scraped/set, and
it makes the badge slot look broken rather than intentional (see the issue screenshot). Per the
reporter's own follow-up comment, logos will populate naturally once first games are played and
ingest runs — the actual fix requested is cosmetic: render a plain black circular placeholder
in the badge slot instead of leaving it empty, so the card looks clean and deliberate until a
real logo is available. Once a logo does resolve (local cache populated by ingest, or
`logo_url` set), it replaces the placeholder automatically on the next request, since card
images are generated fresh every time with no server-side caching.

*Resolves GitHub issue #107.*

## User Stories

### Blank Placeholder for Missing Team Logo
**User story**
As a user, I want a card's team logo slot to show a clean placeholder instead of looking broken
when no team logo is available yet (e.g. before a team has played its first match), so the card
still looks polished pre-season.

**Acceptance criteria**
- When neither the local Dotabuff PNG cache nor the team's HTTP `logo_url` resolves to a usable
  image, the team logo slot is filled with a solid black circular placeholder instead of being
  left unpainted
- The placeholder uses the same circular crop, size, and position as a real team logo, so the
  card layout is identical either way
- Once a team logo becomes available (local cache populated via ingest, or `logo_url` set), it
  replaces the placeholder on the next card image request — no cache to invalidate, since the
  image is generated fresh on every request
- Player avatar behaviour is unchanged — only the team logo slot gets the new placeholder
  treatment

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/image.py` | Add `_blank_logo_placeholder(diameter)`; use it as the fallback when `_load_team_logo_for_card` returns `None` in `generate_card_image` |
| `markdown/features/reference/card-image-generation.md` | Correct "Missing logos are silently skipped" / "the team logo slot is left empty" wording for the team-logo case |
| `markdown/stories/cards.md` | Scope the existing "Card Visual Identity" criterion ("If avatar or logo is unavailable, the card still renders correctly with the slot left empty") to the avatar case only, since team logo now gets a placeholder instead |

### Step 1 — Blank placeholder helper
In `backend/image.py`, alongside `_load_team_logo_for_card`:
```python
def _blank_logo_placeholder(diameter: int):
    """Solid black circular placeholder for a card's team-logo slot when no logo
    can be resolved yet (e.g. before a team's local Dotabuff PNG has been scraped
    or logo_url populated) — cleaner than leaving the slot unpainted."""
    return Image.new("RGBA", (diameter, diameter), (0, 0, 0, 255))
```

### Step 2 — Always paste something into the badge slot
In `generate_card_image`, replace:
```python
logo = _load_team_logo_for_card(team_name, team_logo_url, sr * 2)
if logo:
    base.paste(_circle_crop(logo), (scx - sr, scy - sr), _circle_crop(logo))
```
with:
```python
logo = _load_team_logo_for_card(team_name, team_logo_url, sr * 2) or _blank_logo_placeholder(sr * 2)
base.paste(_circle_crop(logo), (scx - sr, scy - sr), _circle_crop(logo))
```
`_circle_crop` already handles a plain solid-color RGBA image the same way it handles a real
logo, so no further change is needed to the compositing step.

### Step 3 — Documentation corrections
- `card-image-generation.md`, "Compositing pipeline" step 3: change "Missing logos are silently
  skipped" to describe the black-placeholder fallback.
- `card-image-generation.md`, "Team logo sources": change "If neither source is available, the
  team logo slot is left empty" to describe the placeholder.
- `markdown/stories/cards.md`, "Card Visual Identity" acceptance criteria: split the combined
  avatar/logo "left empty" bullet so it reflects that only the avatar slot is left empty; the
  team logo slot now shows the black placeholder (covered by the new story above).

## Verification
- Generate a card image (`GET /cards/{card_id}/image`) for a team with no local Dotabuff PNG
  and no `logo_url` set — badge slot shows a solid black circle instead of a gap
- Generate a card image for a team with a resolvable logo — rendering is unchanged from before
- After ingest populates the team's local logo PNG (or an admin sets `logo_url`), re-request
  the same card's image — the black placeholder is replaced by the real logo with no extra step
- Confirm player avatar rendering for a player with no avatar is unaffected (still the dark base
  colour, no black circle) — the placeholder is scoped to the team logo slot only
- Run `cd backend && python -m pytest tests/ -v` — full suite passes
