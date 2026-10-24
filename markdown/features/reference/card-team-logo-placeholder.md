# Card Team Logo Placeholder

A small correction to card image generation (`reference/card-image-generation.md`): when a
team's logo can't be resolved yet, the badge slot gets a solid black circular placeholder
instead of being left unpainted.

*(see `markdown/plans/plan-issue-107-card-team-logo-placeholder.md`, resolves GitHub issue #107)*

---

## Why

Before a team's first match is ingested, it typically has neither a locally-scraped Dotabuff
logo PNG nor a `logo_url`, so `backend/image.py::_load_team_logo_for_card` returns `None`. The
compositing step used to skip pasting anything in that case, leaving the badge slot looking
broken rather than intentional. Logos populate naturally once ingest runs — this fix only
changes what's shown in the meantime.

## Behaviour

`generate_card_image` falls back to `_blank_logo_placeholder(diameter)` — a plain solid
black RGBA square, circle-cropped the same way a real logo is — whenever
`_load_team_logo_for_card` resolves to nothing. Position, size, and crop are identical to a real
logo, so the card layout doesn't shift. Because card images are generated fresh on every
`GET /cards/{card_id}/image` request (no server-side caching), the placeholder is replaced by a
real logo automatically as soon as one becomes resolvable — no cache to invalidate.

Scoped to the team logo slot only; a missing player avatar is unaffected and still renders as
the plain dark card background, per existing behaviour.

See `reference/card-image-generation.md` for the full compositing pipeline this fallback sits
within.
