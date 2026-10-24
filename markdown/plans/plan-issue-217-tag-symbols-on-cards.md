# Plan: Tag Symbols on Cards

## Context
User tags (caster, season winner, any admin-defined tag) show on a player's cards as 60×60 PNG stickers. `backend/image.py` (`_apply_stickers`, `STICKER_SIZE`, `STICKER_START_X`, `STICKER_Y`) composites them into the top-left of the 597×845 card image. The card image route (`routers/cards.py`) passes the tag keys of the user verifiably linked to the player (`player_links.verified_users_for_player`, #209). Scaled into a card slot, a sticker is a few pixels wide, unreadable and without a tooltip.

#50 added accolade pips: an HTML overlay down the card's right edge with hover, focus and tap tooltips (`accoladePipsHtml`, `data-tip`, `.card-pips`). This plan moves tags into the same kind of overlay, on the card's **left** edge, and adds an **admin** symbol for a player whose linked account is a site admin.

**Decisions** (change them in review if needed):
- **Left column of tag pips:** same look, size and tooltip as accolade pips, stacked down the left edge from the top-left corner where the stickers sat. The card's right side keeps the accolade pips.
- **Which symbols, top to bottom:**
  1. **Admin** (Lucide `shield`, tooltip "Kana Cards admin") when the linked user `is_admin`.
  2. **Caster** (Lucide `mic`, tooltip "Caster").
  3. Any other tag, with Lucide `tag` and its label as the tooltip, in tag-definition order.
- **Season winner:** the `season_winner` tag is **not** shown as a tag pip, because the Fantasy Winner accolade pip (#50) already shows the same thing on the right edge.
- **Stickers retired:** card images no longer composite tag stickers; the route stops passing `tag_keys`, and `_apply_stickers` and the sticker constants are removed. Images have no server-side cache (`Cache-Control: no-store`), so the change shows at once. The sticker PNGs in `assets/stickers/` stay in the repo for now, unused.
- **Data, without user ids:** `GET /accolades` gains `tags: {"<player id>": [{key, label}]}`, with `admin` included as a pseudo-key when the linked user is an admin.
  - Only Steam-verified links count (`player_links`, #209), and only full, non-demo accounts.
  - The admin badge and user tags are already public on the leaderboard and profile, so this exposes nothing new.
- **One registry:** `TAG_SYMBOLS` in `frontend/app-globals.js` (key → icon, tooltip, colour token, order) and one renderer, `tagPipsHtml(tags)`. Each of `.card-pips` gets a sibling, `.card-tag-pips`, wherever cards render pips: card viewer, draw reveal, My Team, collection.
  - The player popup header shows the tag pips before the accolade pips.
- **Colour tokens:** `--tag-admin` and `--tag-caster` match the existing role badges (`role-badge-admin`, `role-badge-caster`), and other tags use a neutral `--tag-generic`. Every kind has its own icon, so colour is never the only difference.

Resolves GitHub issue #217.

## User Stories

### Tags Read as Symbols on Cards
**User story**
As a visitor looking at a card, I want a caster's or admin's tag shown as a clear symbol I can hover, so that I can see who they are without squinting at a tiny sticker.

**Acceptance criteria**
- **Left column:** a player whose Steam-verified linked user has tags shows tag pips down the card's left edge, starting at the top-left. Admin comes first (shield, "Kana Cards admin"), then caster (mic, "Caster"), then other tags (tag icon, their label as the tooltip).
- **Where they show:** the pips appear in the card viewer, the draw reveal, My Team (roster and bench) and the collection. They sit on the opposite edge from the accolade pips and never overlap them.
- **Tooltips:** they use the shared `data-tip` tooltip (hover, focus, tap; Escape closes) and carry an `aria-label` with the same text.
- **No season winner pip:** `season_winner` never renders as a tag pip; the Fantasy Winner accolade pip covers it.
- **Who gets pips:** a player without a verified linked user, or whose user has no tags and isn't an admin, has no tag pips.
- **No markup outside the helper:** no view builds tag pip markup outside `tagPipsHtml`.

### Card Images Stop Carrying Tag Stickers
**User story**
As the operator, I want tags removed from the card image itself, so that a card never shows a sticker and a symbol for the same tag, and a tag change shows at once.

**Acceptance criteria**
- **Image:** `GET /cards/{id}/image` composites no tag stickers. `_apply_stickers` and its constants are removed, and the route no longer reads tags.
- **Live updates:** granting or removing a tag, or changing admin status, changes the card's tag pips on the next page load without touching the image.

### Tags Data Is Public but Carries No User Identity
**User story**
As the operator, I want the tag data behind the symbols to reveal no more than the site already shows, so that tags on cards don't leak who owns which account.

**Acceptance criteria**
- **API:** `GET /accolades` adds `tags: {"<player id>": [{key, label}]}`, with `{key: "admin", label: "Admin"}` first when the verified linked user is an admin, and `season_winner` left out.
- **No identity:** no user id, username or email appears anywhere in the response.
- **Verified links only:** only Steam-verified links on full, non-demo accounts contribute (`player_links`). A typed-in or stale link contributes nothing.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/history.py` | `GET /accolades` adds `tags` |
| `backend/player_links.py` or `backend/accolades.py` | `tags_by_player(db)`: verified links → each user's tag keys and labels plus admin; `season_winner` left out |
| `backend/routers/cards.py` | Card image route stops reading tags and passing `tag_keys` |
| `backend/image.py` | Remove `_apply_stickers`, the `STICKER_*` constants and the `tag_keys` parameter |
| `frontend/app-globals.js` | `TAG_SYMBOLS`, `tagPipsHtml`, `playerTags(playerId)` from the cached `/accolades` |
| `frontend/app-cards.js`, `frontend/app-roster.js`, `frontend/app-player-popup.js` | Render `.card-tag-pips` beside `.card-pips`; tag pips in the popup header |
| `frontend/style.css`, `frontend/colors_and_type.css`, `design/colors_and_type.css` | `.card-tag-pips` on the left edge; `--tag-*` tokens (both copies identical); CSS before GUIDED TOUR |
| `.claude/skills/README.md` | Tag symbol table next to the accolade symbol table |
| `markdown/features/reference/user-tag-system.md`, `markdown/features/reference/player-linking-and-tag-visibility.md`, `markdown/features/reference/card-image-generation.md`, `markdown/features/reference/tag-symbols-on-cards.md` | Docs |
| `backend/tests/test_issue_217_tag_symbols_on_cards.py` | Tests |

No migration, no new env var.

### Step 1 — Data
`tags_by_player(db)` takes the verified links from `player_links.verified_links`. It joins `UserTag` and `TagDefinition`, adds `admin` for `is_admin` users, and leaves out `season_winner`. Expose it as `tags` in `GET /accolades`.

### Step 2 — Remove stickers
Drop the tag lookup in the card image route and the sticker compositing in `image.py`. Update tests that pin `tag_keys` or stickers in the image to the new intended behaviour.

### Step 3 — Frontend
Add the registry and helper, the left column on every card view, and the popup header. Keep the shared `data-tip` tooltip.

### Step 4 — Design system
Add the tokens in both colour files, the left-column CSS, and the README table.

### Step 5 — Docs and tests
**Tests:**
- **`/accolades`:**
  - the tags field holds admin first, caster and a generic tag;
  - `season_winner` is left out;
  - verified links only (no tags through a typed-in or stale link, or for a demo or soft account);
  - no user ids or usernames.
- **Card image:** no sticker compositing, and no `tag_keys` parameter.
- **Frontend (Node harness and source):**
  - order, icons, tooltip and `aria-label`;
  - no `season_winner` pip;
  - pips on every card view, on the left;
  - helper-only markup;
  - tokens in both colour files.

## Verification
- **Caster:** a caster's card on the test environment shows a mic symbol at the top-left. Hovering it says "Caster", and no tiny sticker remains in the image.
- **Admin:** a player whose verified account is an admin shows the shield symbol first.
- **Live change:** removing the caster tag in Admin removes the symbol on reload.
- **Season winner:** a fantasy winner shows the medal on the right edge and no extra tag symbol.
