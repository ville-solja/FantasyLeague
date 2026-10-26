# Card Visuals Rollback

Returns the cards to the original illustrated art used when accolades were introduced, and moves the accolade and tag symbols off the card face into the card viewer, with their details. Players see clean cards; the symbols are one tap away. Plan: `markdown/plans/plan-issue-228-card-visuals-rollback.md` (issue #228). The rolled-back design is recorded in [Card Formatting](card-formatting.md).

---

## Card art

- **Templates:** `assets/Card_Template_{Common,Rare,Epic,Legendary}.png` are restored byte for byte from before layout A (`da89798^`). `Card_Template_Holo.png` and `backend/scripts/make_card_templates.py` are removed.
- **Renderer:** `backend/image.py` is the pre-#218 file, unchanged: a 350 px portrait circle centred at (298, 375), a 104 px team-logo circle at (444, 258), the name at y 90, the team at y 155 and modifier lines from y 620 in 50 px steps, with an 8 px offset for epic and legendary. With no logo, the #107 black circular placeholder fills the logo circle. Details: [Card Image Generation](card-image-generation.md).
- **Holo:** with no Holo template in the repo, a Holo legendary uses the Legendary template with the generated iridescent sheen (`_holo_sheen`, #53); the missing file is logged once per process.
- **Size:** the PNG stays 597 × 845, so the roster, the reveal and the #205 draw animation keep their sizes.
- **Where it shows:** every view that shows the card PNG (`cardImageUrl` → `GET /cards/{card_id}/image`): My Team roster and bench (the collection), the draw reveal and the card viewer; the Weekly Report opens its roster cards in the card viewer. The Twitch panel draws its own card art and loads no card PNG, so it is unaffected. Images are sent with `Cache-Control: no-store`, so the old art shows on the next load.
- **Rank medal:** stays off the PNG (#221 website badge only).

## Symbols on the card

- **No pips on card faces:** neither accolade nor tag pips (#217) show on any card face (My Team roster and bench, the collection, the draw reveal, the card viewer). `_cardSlotHTML` in `app-roster.js` renders the image, the points and the substitution label only.
- **Removed code:** `cardPipsHtml`, `#revealPips`, the `.card-pips` and `.card-tag-pips` CSS with #218's container-unit sizing (`--card-u`, `container-type`), and `_rerenderRosterPips` (the roster no longer re-renders when `GET /accolades` arrives, since its cards show nothing from it).
- **Elsewhere:** the player popup header keeps its tag and accolade pips, and the team popup roster its tag and accolade pips; the Players list, the Teams tab and the Hall of fame keep their accolade pips and chips. `accoladePipsHtml` and `tagPipsHtml` stay for those views.

## Tags and accolades in the card viewer

> **Accolades moved by #230.** The card viewer keeps only the Tags section: `_renderRevealTags` fills `#revealTags`, and `#revealAccolades`, `_renderCardAccolades` and `accoladeDetailsHtml` are gone. The accolade detail lines (`accoladeDetailLine`, `accoladePlayedLine`) now build the player popup's Accolades timeline, and the name under the card carries a "Stats and accolades" hint. See [Accolades and Rank in the Player Popup](player-popup-accolades-and-rank.md). The text below describes the #228 design.

The card viewer (`#revealModal`) has two sections under the card, in place of the old chip row: `#revealTags` and then `#revealAccolades` (`section.reveal-details`, `hidden` until filled). `_renderCardAccolades` in `app-cards.js` fills them from the cached `GET /accolades` data (`playerTags`, `playerAccolades`); there is no new endpoint.

- **Tags** (`tagDetailsHtml(tags)` in the TAG SYMBOLS block of `app-globals.js`): one line per tag with its symbol and text, in `TAG_SYMBOLS` order: "Kana Cards admin", "Caster", then other tags by label. `season_winner` is never shown. Steam-verified links only, keys and labels only (#217 rules).
- **Accolades** (`accoladeDetailsHtml(accolades)` in the ACCOLADES block): one line per title, newest season first and champions first within a season:
  - champions name the team: "S15 Div 1 Champion · with Team Name";
  - point-based accolades show their value: "S15 Most Points · 812.3 pts" (Best Average, Best Single Match and Fantasy Winner the same way; a Fantasy Winner without a value has no suffix);
  - Played is one last line, "Played 7 seasons · S4–S16", counted from Season 4 (`ACCOLADE_PLAYED_FROM`, mirroring `accolades.FIRST_COUNTED_SEASON`, #212), with the seasons, newest first, in a `<details>` disclosure.
- **Look:** each line starts with its kind's pip (`accolade-pip--{plate} accolade-pip--{key}` or `card-tag-pip--{variant}`), so the symbol and plate colour match the pips elsewhere. The symbol is `aria-hidden` and the text carries the meaning. Styles: `.reveal-details`, `.card-details-*`, `.card-detail*` in `style.css` (tokens only, at most 280 px wide, lines wrap).
- **Empty:** a helper with nothing to show returns `""`, and the section stays `hidden`, so it leaves no space.
- **Draw reveal:** during a draw both sections stay hidden while the card flies in and flips; `_finishRevealEntering` shows the non-empty ones when the flip has finished (they fade in with the other details). Under reduced motion they show as the reveal fades in.

## Tests

`backend/tests/test_issue_228_card_visuals_rollback.py` pins the restored files by SHA-256, the pre-#218 geometry, the Holo fallback, the removed files and code, both helpers, the card viewer sections (Node harnesses, including the #205 draw harness) and the CSS. `test_issue_218_card_formatting.py` is deleted; the #107 tests are back to their pre-#218 assertions.
