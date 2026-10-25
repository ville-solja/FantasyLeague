# Tag Symbols on Cards

User tags and admin status show as symbols down a card's left edge, mirroring the accolade pips on the right, instead of tiny stickers baked into the card image (issue #217). Plan: `markdown/plans/plan-issue-217-tag-symbols-on-cards.md`.

---

## Symbols

| Key | Icon | Tooltip | Colour token | Order |
|---|---|---|---|---|
| `admin` (the linked user is a site admin) | `shield` | Kana Cards admin | `--tag-admin` | 1 |
| `caster` | `mic` | Caster | `--tag-caster` | 2 |
| any other tag | `tag` | the tag's label | `--tag-generic` | 3+ (tag-definition order) |
| `season_winner` | not shown | covered by the Fantasy Winner accolade pip | — | — |

- **Who gets them:** only a player's Steam-verified linked user (`player_links.verified_links`: `steam_id` and `player_id` on a full, non-demo account) contributes. A typed-in or stale `player_id`, a demo account or a Twitch-only account adds nothing. When more than one account is verifiably linked to the same player, their tags are merged without duplicates.
- **Shared look:** each symbol is a `.card-tag-pip` with the accolade pip's shape and size (sized in em, so it scales with the card), focusable (`tabindex="0"`), with the same text as `aria-label` and as `data-tip`. The shared tooltip (`showAccoladeTip`, issue 50/208) opens on hover, focus or tap and closes on Escape, blur or a tap elsewhere.
- **Colours:** `--tag-admin`, `--tag-caster` and `--tag-generic` alias the role badge tokens (`--badge-admin`, `--badge-caster`, `--badge-tag`), in both `frontend/colors_and_type.css` and `design/colors_and_type.css`. Every kind has its own icon, so colour is never the only difference.
- **No stickers:** card images no longer composite tag stickers. The PNGs in `assets/stickers/` stay in the repo, unused.

## Where they show

| View | Code | Container |
|---|---|---|
| Card viewer and draw reveal | `_renderCardAccolades` in `frontend/app-cards.js` | `#revealPips` → `.card-tag-pips` beside `.card-pips` |
| My Team roster and bench (the collection) | `_cardSlotHTML` in `frontend/app-roster.js` | `.card-tag-pips` beside `.card-pips` in each `.card-slot` |
| Player popup header | `renderPlayerAccolades` in `frontend/app-player-popup.js` | `#playerModalPips`, tag pips before the accolade pips |

On cards, `.card-tag-pips` sits over the card image's left pillar and `.card-pips` over the right one (layout A, issue #218), so the two columns never overlap. Both are placed and sized in `--card-u`, a hundredth of the card's width: `1cqw` where container queries work (`.card-slot`, `.reveal-img-wrap` and `.draw-landing` declare `container-type: inline-size`), else 1.8 px on the 180 px roster card and 2 px in the 200 px card viewer. A pip is about 10 % of the card's width (`font-size` 5.9 units × the 1.7 em pip), each column is centred on its pillar, starts at the portrait row, and stops at the pillar's bottom (`max-height`, `overflow: hidden`): five pips fit.

## Frontend

All in the TAG SYMBOLS block of `frontend/app-globals.js`:

- `TAG_SYMBOLS`: the registry, key → `{icon, tip, token, order}` for `admin` and `caster`; `TAG_SYMBOL_GENERIC` for any other key; `TAG_SYMBOLS_HIDDEN` (`season_winner`).
- `tagPipsHtml(tags)`: the only builder of tag pip markup. It drops hidden and empty keys, orders admin, caster, then the rest in the given order, escapes labels, and returns `""` for no pips. For a known key the registry's tooltip wins over the API label (so `admin` reads "Kana Cards admin").
- `playerTags(playerId)`: one player's list from the cached `GET /accolades` `tags` map (`[]` when missing). `loadAccolades()` fills it with the accolade data, once per page, and re-renders the roster when it arrives.

## Endpoints

### `GET /accolades`
Public. Alongside `current_season`, `current_season_short` and `players`, returns:

```json
{ "tags": { "1001": [{"key": "admin", "label": "Admin"}, {"key": "caster", "label": "Caster"}] } }
```

Built by `accolades.tags_by_player(db)`: the verified links, each user's `UserTag` rows joined to `TagDefinition`, plus an `admin` pseudo-tag for `users.is_admin`. Admin first, caster second, other tags by tag-definition id; `season_winner` left out; players with no symbols are absent (`{}` when none). Entries carry only `key` and `label`: no user id, username or email. The admin badge and tags are already public on the leaderboard and profile, so this exposes nothing new. A tag grant, revoke or admin change shows on the next page load.

### `GET /cards/{card_id}/image`
No longer reads tags: the route passes no `tag_keys`, and `image.generate_card_image` has no such parameter (`_apply_stickers` and the `STICKER_*` constants are removed).

## Tests

`backend/tests/test_issue_217_tag_symbols_on_cards.py`.

## Privacy note

The admin symbol makes public which league player a site-admin account belongs to, through that account's Steam-verified link. Before #217 the public leaderboards showed only that a *username* was an admin. No user id, username or email is in the payload.

Tester accounts contribute no tag pips, matching the leaderboards, which never show testers.
