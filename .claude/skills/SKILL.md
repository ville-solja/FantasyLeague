---
name: kanaliiga-design
description: Use this skill to generate well-branded interfaces and assets for Kanaliiga (Finnish amateur Dota 2 "Corporate Esports League") and its Fantasy app, either for production or throwaway prototypes/mocks/decks/stream overlays. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files. Key entry points:

- `README.md` — brand context, content fundamentals, visual foundations, iconography (READ FIRST)
- `colors_and_type.css` — all design tokens; include via `<link rel="stylesheet">` in every artifact
- `fonts/BigShouldersText-VariableFont_wght.ttf` — the single brand display font (self-host)
- `assets/logo_kanaliiga_primary.png` — primary logo (chicken + flame shield)
- `assets/bg_dota_landscape.png` — Dota dusk-map hero background
- `assets/banner_vs.png` — signature hex VS banner
- `ui_kits/fantasy_web/` — Kanaliiga Fantasy web-app components + click-through
- `ui_kits/stream_overlay/` — broadcast matchup overlay

If creating visual artifacts (slides, mocks, throwaway prototypes, stream scenes, marketing): copy assets out and create static HTML files for the user to view. If working on production code for the FantasyLeague repo, copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

Core rules that define this brand:
- Display type is **Big Shoulders Text** in ALL CAPS with wide tracking. Body is Inter.
- Palette is orange/red flame on near-black. No blue/purple/teal chrome. Rarity blues/purples/amber only scoped to Fantasy card slots.
- No emoji. No bluish-purple gradients. No pill CTAs. No left-border accent cards.
- Tone is dry, terse, confident esports. Finnish strings on overlays are part of the brand.
- Iconography is Lucide (CDN substitution — flag if user wants something else).
