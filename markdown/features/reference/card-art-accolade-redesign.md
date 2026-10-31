# Card Art Accolade Redesign

New illustrated card templates with purpose-built slots for everything a card shows — photo, team logo, name, team name, stats, and a 6-slot accolade badge grid — replacing the original templates restored by [Card Visuals Rollback](card-visuals-rollback.md) (#228). Unlike layout A (#218), the new design has a clean place for accolades, so they return to the card face using dedicated badge art instead of the Lucide icon pips used elsewhere on the site. Tags stay off the card face.

See [Card Image Generation](card-image-generation.md) for the full compositing pipeline and current slot coordinates; this doc is the record of the change itself.

---

## What changed from the restored (#228) art

| Area | Before this change | After this change |
|---|---|---|
| Templates | `assets/Card_Template_{Common,Rare,Epic,Legendary}.png`, 597×845, transparent cutouts for photo/logo | `assets/card_templates/Card_{Grey,Blue,Purple,Gold}.png`, 687×1024, opaque slot fills |
| Compositing order | Photo and logo pasted first, template composited on top through transparent cutouts | Template composited first as the base, photo/logo/text/accolades pasted on top into the opaque slots |
| Player photo | 350 px circle crop | Square crop filling a square slot |
| Team logo | 104 px circle crop | Aspect-fit into a larger rectangular box, no crop |
| Accolades on the card face | None (moved to the card viewer by #228, then to the player popup by #230) | Up to 6 accolade badge icons in a 3×2 grid, one per accolade the player holds (priority-capped when a player has more than 6) |
| Holo | Legendary template with a procedurally generated rainbow sheen (`_holo_sheen`) | Dedicated `Card_Holo.png` template; no procedural sheen |

Accolades elsewhere on the site (Players list, Teams tab, team popup, Hall of Fame, player popup's Accolades timeline) are unchanged — the card face icons are additive, using their own badge art rather than `ACCOLADE_KINDS`' Lucide icon names, mapped in `backend/image.py`.

## Accolade icon priority (card face, 6 slots)

When a player holds more than 6 accolades, the card shows the highest-priority 6, newest season first within a tier:

1. Division champion (div1, div2)
2. Division runner-up
3. Division third place
4. Fantasy winner
5. Performance awards (Most Points, Best Average, Best Single Match)
6. Seasons played

## Assets

New templates live under `assets/card_templates/` (`Card_Grey.png`, `Card_Blue.png`, `Card_Purple.png`, `Card_Gold.png`, `Card_Holo.png`, all 687×1024 RGBA); new accolade badges live under `assets/accolades/` (`Accolade_*.png`, one per `ACCOLADE_KINDS` key). Both folders moved from their untracked planning-time locations (`assets/Card templates/`, `assets/Accolades/`) into these clean, tracked, lower-cased paths. The pre-redesign `assets/Card_Template_{Common,Rare,Epic,Legendary}.png` files are removed.

## Final slot coordinates and the icon filename map

See [Card Image Generation](card-image-generation.md) for the full, current slot-rect table (`_PHOTO_SLOT`, `_NAME_BAR`, `_TEAM_NAME_BAR`, `_STATS_BOX`, `_LOGO_BOX`, the accolade grid) and the `_ACCOLADE_ICON_FILES` map — both measured against the shipped templates, not the plan's first-pass pixel-scan estimates.

## Plan

`markdown/plans/plan-card-art-accolade-redesign.md`
