# Card Team Logo Placeholder

A small correction to card image generation (`reference/card-image-generation.md`): when a
team's logo can't be resolved yet, the badge slot gets a solid black placeholder instead of
being left unpainted.

*(see `markdown/plans/plan-issue-107-card-team-logo-placeholder.md`, resolves GitHub issue #107)*

> **Box shape updated by the Card Art Accolade Redesign.** The team-logo slot was a 104 px
> circle crop (`_SMALL_CIRCLE`) before `markdown/plans/plan-card-art-accolade-redesign.md`; it
> is now a larger rectangular, aspect-fit box (`image._LOGO_BOX`). The placeholder behaviour
> described below is unchanged in spirit — only the shape it fills changed, from a circle to the
> box.

---

## Why

Before a team's first match is ingested, it typically has neither a locally-scraped Dotabuff
logo PNG nor a `logo_url`, so `backend/image.py::_load_team_logo_for_card` returns `None`. The
compositing step used to skip pasting anything in that case, leaving the badge slot looking
broken rather than intentional. Logos populate naturally once ingest runs — this fix only
changes what's shown in the meantime.

## Behaviour

`generate_card_image` falls back to `_blank_logo_placeholder(w, h)` — a plain solid black RGBA
image sized to the logo box (`image._LOGO_BOX`) — whenever `_load_team_logo_for_card` resolves
to nothing. Position and size are identical to a real (aspect-fit) logo, so the card layout
doesn't shift. Because card images are generated fresh on every `GET /cards/{card_id}/image`
request (no server-side caching), the placeholder is replaced by a real logo automatically as
soon as one becomes resolvable — no cache to invalidate.

Scoped to the team logo slot only; a missing player photo is unaffected and still renders as the
template's own slot fill, per existing behaviour.

See `reference/card-image-generation.md` for the full compositing pipeline this fallback sits
within.
