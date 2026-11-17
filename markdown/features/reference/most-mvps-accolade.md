# Most MVPs Accolade

A fourth end-of-season player award: the player with the most MVPs in the season's scored matches. Issue #248. Plan: `markdown/plans/plan-issue-248-most-mvps-accolade.md`. The other awards and the accolade system are in [Season Winners and Holo Cards](season-winners-and-holo-cards.md).

---

## Rule

- **Winner:** the player with the most `player_match_stats.is_mvp` rows among the season's scored matches (`accolades.compute_awards`, the same match filter as the other awards, `scored_stat_sql`). MVPs on a match excluded from scoring don't count.
- **Ties and none:** every tied player gets it. When nobody has an MVP there is no award, and End Season works as before.
- **Value:** the MVP count, a whole number. Displays say "3 MVPs" or "1 MVP", never "pts" (`accoladeValueText` in `frontend/app-globals.js`).

## Record

- **Stored:** `season_accolades` rows with `kind = most_mvps`, `value` = the MVP count, no division, team or match id. No schema change: `kind` is a free string.
- **End Season:** `most_mvps` is the last entry of `accolades.AWARD_KINDS`, so `GET /admin/season/accolades-preview` returns `awards.most_mvps` (`[{player_account_id, player_name, value}]`) and `POST /admin/season/end` inserts one row per winner with source `season_end`. A row entered by hand earlier is kept (`ON CONFLICT DO NOTHING`).
- **By hand:** Admin › Player management › Add accolade offers **Most MVPs** with a player and an optional value (`POST /admin/season-accolades` accepts `kind: "most_mvps"`; it needs a player and takes no division or user). A value entered by hand must be a whole number, 1 or more (422 otherwise). It is edited and removed like any other accolade. A season that ended before this change gets the award this way.

## Where it shows

- **Symbol:** key `most_mvps`, name "Most MVPs", Lucide icon `star`, outlined plate, colour token `--accolade-mvp` (violet, `--k-rarity-epic`). It sits after Best Single Match in `ACCOLADE_KINDS` (backend and frontend, kept identical by a test).
- **End Season dialog:** a Most MVPs row with the winners and "N MVPs".
- **History:** `GET /history/seasons` adds `awards.most_mvps` (`[]` for a season without one); the season's Awards list shows the chip, the names and "N MVPs". A season without a winner has no Most MVPs row.
- **Player popup:** pips and the timeline line "S16 Most MVPs · 3 MVPs" (no suffix when the row has no value). It counts as a season award.
- **Player management:** the "Champions and accolades" table shows the value as "N MVPs".
- **Cards:** the badge `assets/accolades/Accolade_Most_MVPs.png` in the accolade grid, in the same priority tier as the other performance awards (`image._ACCOLADE_PRIORITY`, `_CARD_ACCOLADE_PRIORITY`), with the usual tooltip ("Most MVPs · S16"). Card images are drawn on request from the player's accolades, so nothing has to be regenerated after End Season.

## Placeholder badge

`Accolade_Most_MVPs.png` is a **placeholder awaiting final art**: a recoloured (violet) copy of `Accolade_Best_Single_Match.png`, same size (209×203) and mode (RGBA). Replace the file with the final badge, drawn in the style of the others, before the season 17 cards are drawn; no code change is needed.

## Tests

`backend/tests/test_issue_248_most_mvps_accolade.py`.
