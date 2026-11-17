# Plan: Most MVPs Accolade

## Context
Issue #248: "Currently the MVP's are counter but at the end of season it is not one of the accolade categories." MVPs are counted per player (`player_match_stats.is_mvp`; the Players tab's MVP leaderboard and the player popup's MVPs tile), but End Season records only three player awards: Most Points, Best Average and Best Single Match (`accolades.AWARD_KINDS`, computed in `accolades.compute_awards`). This plan adds a fourth, **Most MVPs**, recorded at End Season and shown everywhere accolades show.

**Decisions** (change them in review if needed):
- **Rule:** the player with the most MVPs in the season's scored matches (the same match filter as the other awards, `scored_stat_sql`). Every tied player gets it, as for the other awards. No award when nobody has an MVP. The value is the MVP count.
- **Kind:** `most_mvps`, name "Most MVPs", Lucide icon `star`, outlined plate, colour token `--accolade-mvp`. It sits after Best Single Match in `ACCOLADE_KINDS` and has the same card priority as the other awards.
- **Card badge:** the card face shows a badge image per kind from `assets/accolades/`, and a test requires one for every kind. `Accolade_Most_MVPs.png` has to be drawn in the style of the others. Until the art arrives, the developer adds a placeholder made from an existing badge so the pipeline works; replacing the file needs no code change.
- **Season 16:** if End Season already ran for season 16, the admin adds the award by hand in Admin › Player management › Add accolade (the kind is offered there). If it hasn't run yet, End Season records it.
- **No schema change:** `season_accolades.kind` is a free string; `value` holds the count.

Resolves GitHub issue #248.

## User Stories

### Most MVPs Is Recorded at the End of the Season
**User story**
As an admin ending a season, I want the player with the most MVPs to get an accolade, so that MVPs count for something after the season.

**Acceptance criteria**
- **Preview:** the End Season preview lists **Most MVPs** with the winner or winners and their MVP count, next to the other awards.
- **Recorded:** End Season inserts one `most_mvps` row per winner in `season_accolades` (`value` = the count, `source` `season_end`); a row that already exists is kept.
- **Ties and none:** every player tied for the most MVPs gets the award. With no MVPs in the season, there is no award and End Season still works.
- **Scored matches only:** MVPs on matches excluded from scoring don't count.

### Most MVPs Shows With the Other Accolades
**User story**
As a player, I want to see the Most MVPs award on the History tab, in the player popup and on cards, so that it is as visible as the other awards.

**Acceptance criteria**
- **History:** the season's awards list **Most MVPs** with the player and "N MVPs".
- **Player popup:** the accolade timeline shows it with its icon and the count.
- **Cards:** the player's cards show the Most MVPs badge in the accolade grid, with the same priority as the other awards and a tooltip.
- **Registry:** `ACCOLADE_KINDS` in `backend/accolades.py` and `frontend/app-globals.js` list `most_mvps` identically (the parity test passes).

### An Admin Can Add Most MVPs by Hand
**User story**
As an admin, I want to add or remove a Most MVPs accolade for a past season, so that seasons ended before this change can have it.

**Acceptance criteria**
- **Add:** Admin › Player management › Add accolade offers **Most MVPs** as a kind, with a player and a value, like the other awards.
- **Remove:** it can be removed like any other accolade.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/accolades.py` | `most_mvps` in `ACCOLADE_KINDS`, `KINDS`, `AWARD_KINDS`; `compute_awards` counts MVPs |
| `backend/image.py` | `_ACCOLADE_ICON_FILES` and `_ACCOLADE_PRIORITY` entries |
| `assets/accolades/Accolade_Most_MVPs.png` | Badge image (placeholder until the art arrives) |
| `frontend/app-globals.js` | `ACCOLADE_KINDS` entry and the priority map |
| `frontend/app-history.js`, `frontend/app-admin-season.js` | Award lists gain `most_mvps` (unit "MVPs") |
| `frontend/colors_and_type.css`, `design/colors_and_type.css`, `frontend/style.css` | `--accolade-mvp` token and the pip/chip rule |
| `markdown/features/reference/most-mvps-accolade.md`, `season-winners-and-holo-cards.md` | Docs |
| `backend/tests/test_issue_248_most_mvps_accolade.py` | Tests |

No migration, no env var.

### Step 1 — Compute the award
In `_scored_rows`, also select `s.is_mvp`. In `compute_awards`, count MVPs per player and add:

```python
mvp_items = [i for i in items if i[1]["mvps"] > 0]
awards["most_mvps"] = [entry(pid, p["mvps"]) for pid, p in _ties(mvp_items, lambda i: i[1]["mvps"])]
```

`entry` rounds with `display_points`; store the count as a whole number. `record_season` already loops over `AWARD_KINDS`, so adding the kind there records it.

### Step 2 — Registry and display
Add the kind to both `ACCOLADE_KINDS` lists, the CSS token and pip rule, the History and End Season preview lists (value shown as "N MVPs", not "pts"), and the Add accolade dialog's kind choices (check where `admin_accolades.py` validates kinds).

### Step 3 — Card badge
Add the image file and the two `image.py` entries. Check whether cached card images need regenerating for the winners (follow what End Season already does for the other awards).

### Step 4 — Tests
- `compute_awards`: one winner; a tie lists both; no MVPs gives an empty list; an MVP on an excluded match doesn't count.
- `record_season` inserts `most_mvps` rows and keeps an existing one.
- Registry parity between backend and frontend; every kind has a badge file; the History and preview lists include the kind; the admin route accepts it.

## Verification
- On a copy of the season's data, the End Season preview shows Most MVPs with the same leader as the Players tab's MVP leaderboard.
- After End Season (on the copy), History, the player popup and the winner's cards show it.
- Add and remove one by hand in Admin › Player management › Add accolade.
- Replace the placeholder badge with the final art before the season 17 cards are drawn.
