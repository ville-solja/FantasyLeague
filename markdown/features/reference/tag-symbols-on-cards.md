# Tag Symbols on Cards

User tags and admin status show as symbols instead of tiny stickers baked into the card image (issue #217). Plan: `markdown/plans/plan-issue-217-tag-symbols-on-cards.md`.

**Since #228 the symbols are off the card face:** the card viewer lists the tags in a Tags section under the card, and the player popup header keeps the pips. See [Card Visuals Rollback](card-visuals-rollback.md).

---

## Symbols

| Key | Icon | Tooltip | Colour token | Order |
|---|---|---|---|---|
| `admin` (the linked user is a site admin) | `shield` | Kana Cards admin | `--tag-admin` | 1 |
| `caster` | `mic` | Caster | `--tag-caster` | 2 |
| any other tag | `tag` | the tag's label | `--tag-generic` | 3+ (tag-definition order) |
| `season_winner` | not shown | covered by the Fantasy Winner accolade pip | — | — |

- **Who gets them:** only a player's Steam-verified linked user (`player_links.verified_links`: `steam_id` and `player_id` on a full, non-demo account) contributes. A typed-in or stale `player_id`, a demo account or a Twitch-only account adds nothing. When more than one account is verifiably linked to the same player, their tags are merged without duplicates.
- **Shared look:** each symbol is a `.card-tag-pip` with the accolade pip's shape and size (sized in em), focusable (`tabindex="0"`), with the same text as `aria-label` and as `data-tip`. The shared tooltip (`showAccoladeTip`, issue 50/208) opens on hover, focus or tap and closes on Escape, blur or a tap elsewhere.
- **Colours:** `--tag-admin`, `--tag-caster` and `--tag-generic` alias the role badge tokens (`--badge-admin`, `--badge-caster`, `--badge-tag`), in both `frontend/colors_and_type.css` and `design/colors_and_type.css`. Every kind has its own icon, so colour is never the only difference.
- **No stickers:** card images no longer composite tag stickers. The PNGs in `assets/stickers/` stay in the repo, unused.

## Where they show

| View | Code | Container |
|---|---|---|
| Card viewer and draw reveal | `_renderCardAccolades` in `frontend/app-cards.js` | `#revealTags`: the Tags section from `tagDetailsHtml`, one line per tag with its symbol and text (issue #228) |
| Player popup header | `renderPlayerAccolades` in `frontend/app-player-popup.js` | `#playerModalPips`, tag pips before the accolade pips |
| Team popup roster | `frontend/app-team-popup.js` | tag pips before the accolade pips in each row |

No card face shows tag pips (My Team roster and bench, the collection, the draw reveal and the card viewer): #228 removed the `.card-tag-pips` overlay and its CSS.

## Frontend

All in the TAG SYMBOLS block of `frontend/app-globals.js`:

- `TAG_SYMBOLS`: the registry, key → `{icon, tip, token, order}` for `admin` and `caster`; `TAG_SYMBOL_GENERIC` for any other key; `TAG_SYMBOLS_HIDDEN` (`season_winner`).
- `tagPipsHtml(tags)`: the only builder of tag pip markup. It drops hidden and empty keys, orders admin, caster, then the rest in the given order, escapes labels, and returns `""` for no pips. For a known key the registry's tooltip wins over the API label (so `admin` reads "Kana Cards admin").
- `tagDetailsHtml(tags)` (issue #228): the card viewer's Tags section. One line per tag with its symbol (decorative, `aria-hidden`) and text: "Kana Cards admin", "Caster", then other tags by label. It drops `season_winner` and returns `""` when nothing is left.
- `playerTags(playerId)`: one player's list from the cached `GET /accolades` `tags` map (`[]` when missing). `loadAccolades()` fills it with the accolade data, once per page.

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
