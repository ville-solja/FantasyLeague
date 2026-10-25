# Kanaliiga Design System

Design system for **Kanaliiga** — a Finnish amateur Dota 2 league ("Corporate Esports League") — and its spin-off products, notably **Kanaliiga Fantasy**.

The brand's visual tone is set by its stream overlays and league poster artwork: **dark Dota-map imagery**, **bold condensed display type** (Big Shoulders Text), **orange/red flame accents**, and **angular hex banners**. This system treats those as the source of truth. The current Fantasy web-app frontend is the *functional* reference only — its plain dark/monospace look is **not** the desired aesthetic.

---

## Products / surfaces

1. **Kanaliiga.fi marketing site** — league homepage, news, signups, shop. Dark atmospheric Dota hero imagery + orange accents + clean sans nav.
2. **Kanaliiga Fantasy web app** (`frontend/` in the repo) — tabs for My Team / Profile / Leaderboards / Players / Teams / Schedule / Admin. Players draft cards (Common → Legendary), earn weekly/season points.
3. **Twitch extension** (`twitch-extension/`) — panel on Kanaliiga streams for token drops, MVP selection, account linking.
4. **Stream overlays** (Striimijutut_S14) — pre-/in-game broadcast graphics: matchup banner, idle screen, season logos.

---

## Sources

| Source | Location |
|---|---|
| GitHub repo | `ville-solja/FantasyLeague` (main) — FastAPI + vanilla HTML/JS + Twitch extension |
| League site | https://kanaliiga.fi |
| Stream / designer assets | `uploads/fantasy-league-designer/` (imported to `assets/stream/`, `reference/`, `fonts/`) |
| Card template PNGs | `assets/Card_Template_{Common,Rare,Epic,Legendary}.png` (in repo, not yet copied) |

> **Note** — the screenshots under `reference/` are of the *current* implementation. Except for screenshot-11 (kanaliiga.fi marketing site), they do **not** represent the target aesthetic. Use the stream assets and `colors_and_type.css` as the source of truth.

---

## Index

| File / folder | What's in it |
|---|---|
| `README.md` | You are here. Brand context, content fundamentals, visual foundations, iconography. |
| `colors_and_type.css` | All design tokens (CSS variables) + semantic element defaults. **Import this first** in any artifact. |
| `fonts/` | `BigShouldersText-VariableFont_wght.ttf` (primary display) + SIL OFL license. |
| `assets/` | Logos, stream overlay art, Dota backgrounds, VS banner. |
| `assets/stream/` | Original stream-overlay source files (season 14). |
| `reference/` | Screenshots of the current implementation (functional reference only). |
| `preview/` | Design-system preview cards rendered in the Design System tab. |
| `ui_kits/fantasy_web/` | Web-app UI kit — React JSX components + `index.html` click-through. |
| `ui_kits/stream_overlay/` | Stream-overlay "UI kit" — matchup banner, idle screen. |
| `SKILL.md` | Claude Skill manifest for when this system is used as a skill. |

---

## CONTENT FUNDAMENTALS

**Brand name:** "Kanaliiga" (literally "chicken league" in Finnish — "kana" = chicken, "liiga" = league). The logo is a cartoon **chicken** inside a flame-shaped shield with the tagline *"Corporate Esports League"*. The chicken is a knowing, self-deprecating mascot for what is an amateur league of Finnish corporate teams.

### Voice and tone
- **Dry, plain, direct.** The league takes Dota seriously but doesn't take itself too seriously. No marketing puffery, no exclamation points.
- **Confident esports, not hype.** Tone of a broadcaster or analyst: "Rosters lock every Sunday." "Season 14 sign-ups open 23.9.2025." Never "🎉 Huge news!"
- **Bilingual reality.** The kanaliiga.fi site runs in **Finnish**; the Fantasy app runs in **English**. Both coexist — don't force translations. Finnish strings on overlays ("Ottelupari", "Striimi", "Säännöt ja ohjeet") are part of the brand.
- **In the match, not above it.** Esports terminology (GPM, wards, B02, Division 1, Group Stage, Casting by…) is used plainly, not explained.

### Casing
- **Display text / titles / buttons: ALL CAPS** with wide tracking. This is non-negotiable — it's the voice of the overlays and the logo.
- **Body / paragraph: sentence case.** No Title Case For Headlines.
- **Numbers and stats: tabular, uppercase units** — `1,455 GPM`, `19-8-0 K/D/A`.

### Pronouns
- **You / your** when speaking to the manager ("Your roster locks Sunday", "Draft players onto your fantasy roster").
- **We** is rare; the league speaks in third-person institutional voice.

### Emoji / decoration
- **No emoji** in UI. The brand is already visual — logo, flame, Dota imagery do the work. Decorative emoji undercut the esports tone.
- **Unicode dashes and pipes** (`—`, `·`, `|`) are fine as dividers.
- **Sentence punctuation is minimal** on display strings ("VS.", "DOTA 2", "SEASON 14") — often no trailing period.

### Examples from the product
- Logo tagline: `CORPORATE ESPORTS LEAGUE · KANALIIGA`
- Overlay title: `DIVISION 1 · GROUP STAGE (B02)`
- Overlay caster credit: `Casting by Muffa`
- Fantasy CTA: `Draw a card` (not "Draw a card! 🎴")
- Profile copy: `Link your OpenDota account ID. Future features may include granting you a card representing yourself as a player.`
- Admin copy: `Busts the in-memory cache and re-fetches from the Google Sheet.` (terse, technical, dry)
- Schedule row: `REAKTOR   0   VS.   0   INNOFACTOR` — flat, symmetric, no flourish.

---

## VISUAL FOUNDATIONS

### Palette
The entire system runs on **orange + red flame** against **near-black neutrals**. That's it. No blue accent, no purple, no teal — except where **rarity** demands it in the Fantasy card system (rare=blue, epic=purple, legendary=amber). Keep rarity colors scoped to card slots and badges; never use them as chrome.

- **Primary:** `--k-orange-500` `#e85d1c` (flame / DOTA 2 badge orange).
- **Primary deep:** `--k-orange-700` `#a83c0a`, `--k-red-500` `#c8321a` (flame base, hover states, sunset sky).
- **Accent glow:** `--k-amber-500` `#f0a83a` (legendary rarity, Dota emblem glow, VS hex highlight).
- **Neutrals:** `--k-ink-950` `#0a0a0c` (page bg) → `--k-ink-800` `#1a1a20` (cards) → `--k-ink-100` `#e4e4e8` (body text). True black `#000` reserved for logo outlines and VS banner edge.
- **Rarity:** common `#9a9aa2`, rare `#5aa0e8`, epic `#b06ae0`, legendary `#f0a83a`.
- **Semantic:** ok `#3ecf6a`, warn `#f0a83a`, err `#e05050`, info `#5aa0e8`, twitch `#9147ff`.

### Type
- **Display:** **Big Shoulders Text** (variable, 100–900). Condensed, engineered, all-caps with wide tracking. Used for H1/H2/H3, buttons, eyebrows, numeric scores, tab labels. The brand's single voice.
- **Body:** **Inter** as a neutral companion where reading comfort matters (long copy, forms, tables). Ships as a system-font stack fallback; `colors_and_type.css` does not self-host Inter — include via Google Fonts when used.
- **Mono:** system mono stack (`ui-monospace`, `JetBrains Mono` fallback) for code, IDs, admin/debug affordances.
- **Tracking:** `0.04em` on normal display, `0.12em` on H2, `0.22em` on eyebrows. Body stays at 0.
- **Sizes:** see tokens in `colors_and_type.css`. Hero `112px`, display up to `72px`, body `15px` base.

### Backgrounds
- **Primary:** flat `--k-ink-950`. No gradients by default; the UI should feel like a blackout studio so the orange pops.
- **Imagery backdrops:** Dota 2 dusk-map art (`assets/bg_dota_landscape.png`) or season hero artwork for **idle screens, splash, hero blocks only**. Always under a **vertical protection gradient** (`--grad-protect`) or a ≥40% black scrim to keep text legible.
- **Gradients:** use sparingly — `--grad-orange` for the VS banner + accent bars, `--grad-dusk` for atmospheric block tops. No bluish-purple gradients. No full-bleed gradient pages.
- **No repeating patterns / textures.** Grain is OK in photography; not synthesized.

### Cards / surfaces
- Flat `--bg-card` fill (`#1a1a20`), `1px solid --border` (`#33333d`), radius `--r-md` (6px). Restrained.
- Rarity-aware card slots glow **only** on the specific card art (`--sh-glow-rare/epic/legendary`); the container stays flat.
- No left-border accent cards. No rounded-colored-stripe cards. No drop-shadow on every card — reserve `--sh-lg` for hovered card art and the card-reveal modal.

### Borders
- `1px` neutral hairlines (`--border-soft`) between rows and tabs.
- `1.5–2px` accent borders on focused / selected states, colored with `--accent` or the relevant rarity color.
- **3px** double-line edge on the **hex VS banner** (angular black + orange stroke, matching `assets/banner_vs.png`).

### Radii
- Tiny: `2px` on tag chips, `4px` on buttons and inputs, `6px` on cards/panels, `10px` on modals.
- **No pill buttons** for primary actions — buttons are rectangular with small radius to echo the angular logo/banner geometry. `--r-pill` exists only for avatar rings and status dots.

### Shadows / elevation
- **Inner page:** flat. No shadows on base cards.
- **Hover + reveal:** `--sh-lg` (`0 12px 28px rgba(0,0,0,.6)`), rarity-tinted glow on hover.
- **Modals:** `--sh-xl` + 85% black overlay behind.
- **Signature glows:** `--sh-glow-orange` on the primary CTA hover, `--sh-glow-amber` on the legendary reveal.

### Hover / press / focus
- **Hover:** buttons shift to `--accent-hover` (`#d24e13`) plus a subtle `--sh-glow-orange`. Card images translate `-5px` and scale `1.03` (from the existing implementation; keep it — it's already good).
- **Press:** no shrink; colors deepen one step. Tabs show `border-bottom 2px solid --accent`.
- **Focus:** `2px solid --accent` outline with `2px offset`. Never remove focus rings.
- Ghost buttons: border-only; hover fills `--accent-ghost` (`rgba(232,93,28,.12)`).

### States and emphasis
How a control shows it is selected, what role and status badges look like, how the signed-in user's rows and highlights inside data are marked, and what can be selected. Each rule names its tokens (in `colors_and_type.css`) and its shared class (the "Shared states" section of `frontend/style.css`). Surfaces use these classes; they don't define their own copies.

- **Selected:** accent text plus a 2 px accent underline (tabs), or a 1.5–2 px border (chips, toggles). Schedule chips keep a neutral selected border, because the accent border there marks the current week.
- **Selected + hover / focus-visible:** inverted, with a `--state-selected-hover-bg` fill (`--accent`) and `--state-selected-hover-fg` text (`--accent-fg`). One shared selector list covers every selected control: `.tab.active`, `.weekly-summary-tab-btn.active`, `.howtoplay-tab-btn.active`, `.admin-tab-btn.active`, `.schedule-div-chip.active`, `.schedule-week-chip.selected`, `.schedule-hide-toggle[aria-pressed="true"]` and `.players-filter-chip.active`. Accent details inside a selected control (the week chip's "This week" label and hidden-results marker) switch to `--state-selected-hover-fg` while inverted, so they stay visible. Focus keeps its `2px solid --accent` outline. Unselected hover stays as it is (muted → `--fg`).
- **Role badges** (`.role-badge`, built by `adminBadgeHtml` and `tagBadgeHtml`): display font, bold, `--fs-sm` (Big Shoulders is never set below `--fs-sm`), uppercase, `--tr-wider`. Coloured text, no fill, a 1 px border in the same colour (`currentColor`), `--r-xs` (2 px). Colours: ADMIN `--badge-admin` (`--accent`), Season Winner `--badge-winner` (`--k-amber-500`), Caster `--badge-caster` (`--fg`), any other tag `--badge-tag` (`--fg-muted`). Every badge has a `title` giving its reason. Rarity colours are never used for roles, and no tag can take the admin colour.
- **Status badges** (`.status-badge`, built by `statusBadgeHtml`; also `.league-week-tag` and `.live-tag`): the same type and shape in neutral, `--badge-status` text with a `--border` outline, so they read as information rather than roles. Used for TESTER, ID SHARED, the Steam and Twitch link badges, "League week N" and "(You)". LIVE keeps the semantic `--k-err` text: it is the one status that asks for attention.
- **Self (the signed-in user):** `.row-self`, a full-row `--row-self-bg` tint (`--accent-ghost`) and bold text, plus a "(You)" status badge. No left bar and no inline colours. Used in the season, weekly and past season standings; a row's expandable detail row gets the same tint. Logged out, no row is marked.
- **Emphasis inside data:** the winning side is a bold `--mark-winner` name (`.mark-winner`) under a "Winner" label; the MVP is a `--mark-mvp` "MVP" label (`.mark-mvp`) before the name; surfaces put these classes in their markup rather than copying the colours, and the name itself stays plain. The two never share a colour or a form. No rings or outlines around floating elements: borders belong to controls and cards only. Exemption: transient motion highlights, such as the recap's glow on an MVP game chip (`.weekly-summary-game-mvp.hl`), may glow or fill while the animation plays; they are gone when it ends.
- **Rank medals** (`.rank-medal`, built by `rankMedalHtml`): a player's last known Dota 2 medal, drawn by the app with CSS (a small shape per medal, the medal name and stars as ★ marks); no Dota images. Display font, bold, `--fs-sm`, uppercase, text in the medal colour `--medal-herald` … `--medal-immortal` (each at least 6:1 on `--bg-card` and the rarity reveal backgrounds). Medal colours are for medals only.
- **Selection:** images (`img`) and controls (`button`) are `user-select: none`, and images are not draggable (`-webkit-user-drag: none`, and `draggable="false"` on every `<img>` the frontend modules generate). Names, dates, numbers and prose stay selectable.
- **Ids are text, not numbers:** OpenDota ids and other identifiers are text inputs (`type="text" inputmode="numeric"`, with `pattern="[0-9]*"` where it helps), never number spinners: +1/−1 makes no sense for a 6–10 digit id. The code checks digits itself and says "OpenDota ids are digits only". Decimal values such as an accolade value use `inputmode="decimal"`, also without a spinner.
- **Data rows:** repeated rows (game lists, standings, tables) use a fixed-column grid with `tabular-nums` on numbers, and every cell is always emitted (empty when it doesn't apply), so columns line up across rows and cards. Inline chips must not change row height: no vertical padding or border on a chip inside a row.

### Accolade symbols
Season accolades (issue 50) read like a mana cost: every kind has its own Lucide icon, colour token and plate, so symbols differ without relying on colour. The rule is **pips for a glance, chips where the names fit**.

| Accolade | Name | Icon | Plate | Colour token |
|---|---|---|---|---|
| Div 1 champion | Div 1 Champion | `crown` | filled | `--accolade-div1` (amber) |
| Div 2 champion | Div 2 Champion | `trophy` | filled | `--accolade-div2` (silver) |
| Most points | Most Points | `flame` | outlined | `--accolade-points` |
| Best average | Best Average | `gauge` | outlined | `--accolade-average` |
| Best single match | Best Single Match | `zap` | outlined | `--accolade-match` |
| Fantasy winner | Fantasy Winner | `medal` | outlined | `--accolade-fantasy` |
| Played | Played | `calendar-check` | outlined, muted | `--accolade-played` (grey) |

- **Pips** (`.accolade-pip`, built by `accoladePipsHtml`; `accoladeDetailsHtml` reuses the class as a decorative symbol on its detail lines): one per earned kind in the table's order, with a count from two; Played comes last, muted, and always shows its seasons count. Each pip is focusable, carries its text as `aria-label`, and shows a tooltip (`.accolade-tip`) on hover, focus or tap that closes on Escape, blur or a tap elsewhere. Used in the Players list, the Teams tab, the team popup, the Hall of fame and the player popup header. Never on a card face (issue 228).
- **Chips** (`.accolade-chip`, built only by `accoladeChipsHtml`): one per accolade with the full name ("S16 Div 1 Champion"), newest season first, champions first within a season. Used in Player management, the popup timeline and History; at phone width those views show the pips instead (`.accolade-swap`).
- **Detail lines** (`.card-detail`, built only through the shared `_cardDetailLine`, by `accoladeDetailsHtml` and `tagDetailsHtml`): the card viewer's Accolades section, one line per accolade with its pip symbol (decorative) and text, newest season first, champions first within a season: "S15 Div 1 Champion · with Team", "S15 Most Points · 812.3 pts"; Played is one line ("Played 7 seasons · S4–S16") with the seasons in a disclosure (issue 228).
- The registry is `ACCOLADE_KINDS` in `frontend/app-globals.js`, mirrored in `backend/accolades.py`. No view builds its own symbol markup.
- **Holo**: the iridescent sheen of a Holo card is allowed only on the card art (the card image and its one-time reveal sweep), never on chrome.

### Tag symbols
User tags (issue 217) show as pips in the player popup header and the team popup, and as the card viewer's Tags section (issue 228), for the user verifiably linked to that player. Card faces carry no tag pips. They share the accolade pip's shape, tooltip and focus behaviour; every kind has its own Lucide icon, so colour is never the only difference.

| Tag | Tooltip | Icon | Colour token |
|---|---|---|---|
| Admin (the linked user is a site admin) | Kana Cards admin | `shield` | `--tag-admin` (= `--badge-admin`) |
| Caster | Caster | `mic` | `--tag-caster` (= `--badge-caster`) |
| Any other tag | the tag's label | `tag` | `--tag-generic` (= `--badge-tag`) |

- **Pips** (`.card-tag-pip`, built by `tagPipsHtml`; `tagDetailsHtml` reuses the class as a decorative symbol. The "card" prefix is historical: since issue 228 no card face shows these pips): admin, caster, then other tags in tag-definition order. Used in the player popup header and the team popup, before the accolade pips.
- **Detail lines** (`.card-detail`, built by `tagDetailsHtml` through `_cardDetailLine`): the card viewer's Tags section, one line per tag with its symbol and text ("Kana Cards admin", "Caster", then other tags by label), above the Accolades section.
- **Season winner** is never a tag pip: the Fantasy Winner accolade pip already shows it.
- The registry is `TAG_SYMBOLS` in `frontend/app-globals.js`; the data is `tags` in `GET /accolades` (keys and labels only). Card images carry no tag stickers.

### Transparency / blur
- **85% black overlay** behind all modals.
- **Gradient protection** on hero imagery: `linear-gradient(180deg, transparent 0%, rgba(0,0,0,.85) 100%)`.
- `backdrop-filter: blur(8px)` on the Twitch-extension panel (sits over a live stream) and on sticky schedule headers. Elsewhere, no blur — it blurs the edge of the brand.

### Motion
- **Easings:** `--ease-out` for entrances, `--ease-io` for transitions, `--ease-back` for small card-reveal overshoot. No bounces on chrome.
- **Durations:** `120ms` for hover color shifts, `200ms` default, `360ms` for panel expansion, `680ms` for the card-reveal burst + shimmer.
- **Signature animations** (keep these from the repo):
  - Radial rarity flash on card reveal (`reveal-draw-burst`).
  - Animated "card back" stripes + shimmer while drawing (`drawBackPulse` / `drawShimmer`).
  - No pulsing CTAs. No bouncing icons. No parallax.
- Respect `prefers-reduced-motion` — every animated reveal has a static fallback.

### Layout rules
- Content max-width `1360px`, centered. Gutters `24px`.
- **Tabs at the top**, single horizontal strip, active tab = orange + `2px` orange underline.
- **Grids:** cards reflow via `repeat(auto-fit, minmax(320px, 1fr))`. Stream layouts are fixed 16:9 (1920×1080).
- Key reserved regions on stream overlays — top-left division badge, top-right format badge, center logo cluster, bottom VS banner, bottom-left caster credit.

### Imagery tone
- **Warm + cinematic.** Sunset / dusk / firelit Dota 2 map art — orange highlights, cool blue statues, dark silhouettes. Never flat product shots, never cool-toned screenshots.
- Photography (if any) should feel **warm, contrasty, slightly filmic**. Black-and-white only for logo marks.

---

## ICONOGRAPHY

### Brand marks
- **Primary logo:** `assets/logo_kanaliiga_primary.png` — chicken + flame shield + "CORPORATE ESPORTS LEAGUE / KANALIIGA" wordmark. Use on dark backgrounds at minimum 80×80 px. Never on orange. Never recolor.
- **Square icon (season-versioned):** `assets/stream/square_icon_s14_512.png` — same logo with a season tag badge below. Prefer this for avatar/favicon slots.
- **DOTA 2 lockup:** `assets/stream/dota2_logo.png` — orange DOTA 2 bar + season number. Used on stream overlays to co-brand with Valve's property. Do not modify.
- **VS banner:** `assets/banner_vs.png` — angular hexagonal center "VS." plate with pointed orange/black double-edge bars. The **signature motif** for any competitive matchup card.

### Icon system
The Fantasy codebase does not ship an icon font. Current usage in the repo is sparse: Unicode `×` for close (`\u2715`), `✓` for confirmation, and rarity color dots. This design system formalizes the icon approach as:

- **Primary icon set: Lucide** (MIT licensed, stroke-based) via CDN — `https://unpkg.com/lucide@latest`. Chosen because:
  - Stroke-only, clean geometry matches the angular logo.
  - Wide coverage for esports/data UIs (trophy, swords, shield, users, calendar, bolt, coins, shuffle).
  - Easy to stroke with `currentColor` so icons follow text color.
- **Default size:** 18px in buttons, 20px in tabs, 24px in empty states.
- **Default stroke:** `2px`, color inherits `currentColor`.
- **Substitution flag:** Lucide is a **CDN substitution** — there was no icon set in the original codebase. If you need a specific mark that Lucide lacks, prefer a brand-custom SVG over mixing icon families.

### Emoji & unicode
- **No emoji** in any UI — this is a brand rule.
- Unicode shapes are OK where they carry meaning: `×` close, `✓` OK / confirmation, `—` em-dash, `·` bullet, `→` forward nav. Use sparingly.

### Logos for opposing teams
- Team logos in the Fantasy schedule pull from **Dotabuff** (`assets/dotabuff_league_logos/` in the repo, not yet imported here). When a team logo is missing, use a **monogram chip** — 32×32 square, `--bg-card-hi` fill, first 2 letters of team name in `--font-display` uppercase amber.

### Placeholder imagery
- Three placeholder sizes exist in the repo (`placeholder-24x24`, `placeholder-100x100`, `placeholder-300x200`). Replace with a **flat `--bg-card-hi` square + Lucide `image` icon** in this design system; do not draw new placeholder SVGs.

---

## Getting started

In any HTML artifact:

```html
<link rel="stylesheet" href="colors_and_type.css">
```

Then use tokens and semantic classes — `.k-eyebrow`, `.k-h1`, `.k-numeric`, `--accent`, `--bg-card`, etc. All fonts are self-hosted from `fonts/`. The primary logo lives at `assets/logo_kanaliiga_primary.png`.
