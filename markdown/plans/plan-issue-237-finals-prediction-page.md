# Plan: Finals Prediction Page

## Context
Issue #237 asks for a separate page showing the upper division's final four once the last group-stage match is played. On it, users predict:
- the winner of each upper division semifinal (1st vs 4th, 2nd vs 3rd);
- the grand final.

The correct predictions are stored for a possible future "Finals prediction" accolade. The product owner's follow-ups:
1. **Automate it**, and draw it as a match tree.
2. **No wait on the fixtures site.** It must work without the fixtures site's admin filling in the playoff teams or times, since those updates are slow.
3. **Div 1 only.** Div 2's semis have already started: HOLISA vs Supercell was played.

**What the league's fixtures site has** (checked 2026-10-27, `kanaliiga-schedule.fly.dev`):
- **Playoff slots:** "1st place vs 4th place", "2nd place vs 3rd place" and "Winner of semi-final 1 vs Winner of semi-final 2". They stay placeholders until its admin fills them in by hand, and so do the dates.
- **Standings:** published at `/api/standings`, synced automatically from results, with the tiebreak order points → wins → head-to-head. A tie still level after that is marked `shared`; Elisa Oyj and Hoxhunt Fortum are in that state now.
- **Group stage:** the published `fixtures.json` (our `SCHEDULE_FIXTURES_URL`) has the 28 upper group fixtures and no playoffs.

**What we have ourselves:**
- **Results:** every Div 1 league match is ingested (`matches`: teams, `league_id`, `start_time`; `team_insights.team_divisions` gives each team's division).
- **Group series:** `schedule.resolve_series_result` resolves a group series from its games.
- **Live games:** the live poll (`steam_live`, `LiveMatch`) sees a league game about a minute after it starts.
- **Format:** last season's final was a best of three (2–1), and the group stage is a single round robin of best-of-two series.

So everything the page needs can come from our own data. **The bracket, the lock and the results never wait for the fixtures site.**

**Decisions** (change them in review if needed):
- **Div 1 only.** One bracket per season (division `div1` stored, for a future Div 2).
- **Our own standings:**
  - Div 1 teams play a single round robin (8 teams, 28 series). A series is the pair's group series as the Schedule resolves it today; without the feed, it's the pair's first two games in the Div 1 league.
  - Points: win 2, draw 1 (1–1), loss 0.
  - Tiebreaks, in the fixtures site's order: points, then series wins, then head-to-head (points in the series between the tied teams, as a mini-table for three or more), otherwise **shared**.
- **Bracket set automatically:** when all 28 group series have a result and seeds 1–4 are clear (no shared tie across 1–4 or across the 4th/5th cut):
  - semi-final 1 is seed 1 vs seed 4, and semi-final 2 is seed 2 vs seed 3;
  - the bracket is stored, and predictions open.
- **Unresolved tie:** if a shared tie touches seeds 1–4 after the last group series, a Kana Cards admin orders the tied teams in Admin › Season › Finals (one step, audited). The page says "Seeding waits for a tiebreak decision".
  - If the fixtures site has filled in its semi slots by then, its order is offered as the suggestion. It's only ever a hint.
- **Projected before that:** while group series remain, the tree shows "1st place · now OP Platinum" and so on from our live standings, with "tie" for shared ranks. No picks yet.
- **Lock (all three picks together):**
  - at the first semi game seen live (a `LiveMatch` in the Div 1 league between a semi's two teams), or ingested, whichever comes first;
  - at an admin **Close now**;
  - at a start time, if the fixtures feed ever carries one. That's optional, and an earlier time wins.
- **Late detection is safe:** every save is kept as a new row, and the prediction that counts is the last one saved before the lock time. When the lock is only learned from an ingested game (`start_time`), saves made after that start are ignored automatically. Nobody can predict mid-game even if the live poll missed the start.
- **Results from our matches:**
  - a semi is won by the first team to two game wins in Div 1 league matches between its two teams after the bracket was set;
  - the grand final is between the two semi winners, decided the same way.
  - An admin can **Set result** for a series (audited), which wins over the matches, for a forfeit or a game we can't ingest.
- **Bracket picks:** one winner per semi, and a grand-final pick that must be one of the user's two semi picks. A missing pick or one outside the bracket is refused.
- **Who can predict:** logged-in website users, one prediction per season. Logged-out visitors see the tree and "Log in to predict".
- **Privacy:** no one sees anyone else's picks. After the lock, each series shows the share of picks per team.
- **Kept for the accolade:**
  - when the final is decided, each user's effective prediction gets `correct_picks` (0–3);
  - brackets and predictions keep their season label and survive `POST /admin/season/reset`.
  - The accolade gets its own issue.
- **No rewards** (tokens or points) for correct picks.
- **Page:** a **Finals** tab between Schedule and How to Play, shown from when the bracket is projected (all Div 1 teams have played at least one group series) until the season ends. It holds one match tree: semi-final 1 and 2 → grand final.
- **Cross-check, optional and admin-only:** Admin › Season › Finals compares our seeds with the fixtures site's standings when it's reachable, and flags a difference. Nothing depends on it.
- **Style: Kana Cards only.** The screenshots supplied data, not looks. The tab uses the app's design system (`colors_and_type.css` tokens, `.claude/skills/README.md` "States and emphasis"):
  - match cards are `.panel` surfaces, with Big Shoulders caps for team names and labels;
  - a picked team uses the shared selected state: a 1.5–2 px `--accent` border, inverted on hover or focus;
  - a series winner is a bold `.mark-winner` name under a "Winner" label;
  - teams show their logo or the two-letter monogram, as on the Teams tab;
  - it's dark only, like the app. Nothing is copied from the fixtures site's styling.
- **No new env var.**

Resolves GitHub issue #237.

## User Stories

### The Div 1 Bracket Builds Itself From League Results
**User story**
As a visitor, I want the Finals page to show the Div 1 match tree from the league's results as soon as the group stage ends, so that I can follow the finals without waiting for anyone to update a schedule.

**Acceptance criteria**
- **Standings:**
  - our Div 1 standings come from ingested league matches, with points 2/1/0 for series won, drawn and lost;
  - tiebreaks are series wins, then head-to-head points among the tied teams, otherwise shared.
  - A test reproduces the fixtures site's 2026-10-27 table: OP Platinum 12, Reaktor 9, Elisa Oyj and Hoxhunt Fortum shared at 7.
- **Projected:** while group series remain, the tree shows "1st place · now <team>" and so on, "tie" for shared ranks, and "N/28 group series played". No pick controls show.
- **Set:** once all 28 group series have results and seeds 1–4 are clear, the bracket (semi-final 1: seed 1 vs seed 4; semi-final 2: seed 2 vs seed 3) is stored within one refresh, without any admin or fixtures-site step.
- **Tie at the cut:** a shared tie touching seeds 1–4 after the last series holds the bracket. The page says "Seeding waits for a tiebreak decision" until an admin orders the tied teams.
- **Tree:** semi-final 1 and 2 lead into the grand final. Each match shows team logos and names (or slot names), the series score once games are in, and "Live" while a game of it is in the live list. At desktop width it's drawn with connector lines. At phone width it's a vertical list with no sideways scroll.

### Users Predict the Semifinals and Grand Final
**User story**
As a logged-in player, I want to pick both Div 1 semifinal winners and the grand final once the final four is set, so that I can test my read of the playoffs.

**Acceptance criteria**
- **Open:** pick controls appear when the bracket is set, with "Predictions close when the first semi-final game starts".
- **Picking:**
  - one team per semi;
  - the grand final offers only the user's two semi picks;
  - **Save predictions** stores all three, and missing picks are refused (`422`);
  - picks use `aria-pressed`, with "Your pick: <team>" in text.
- **Valid picks only:** a team not in that series, or a final pick that isn't one of the user's semi picks, is refused (`422`).
- **Lock:** the first semi game seen live or ingested, or an admin Close now, locks all three. A save after the lock is refused (`409`), and the page shows the picks as locked.
- **Late lock is safe:** saves are kept as revisions. If the lock time is learned later from an ingested game's start, the prediction that counts is the last revision saved before that start, and the page shows that one.
- **Logged out:** the tree shows with "Log in to predict".

### Results and Correct Picks Come From Our Matches
**User story**
As a player who predicted, I want my picks marked right or wrong as the games are played, and my score kept, so that I see how I did and it can count toward a later accolade.

**Acceptance criteria**
- **Results:**
  - a semi is won by the first team to two game wins in Div 1 league matches between its teams after the bracket was set;
  - the grand final is between the semi winners, decided the same way;
  - an admin-set result wins over the matches.
- **After lock:** each series shows the share of picks per team and the prediction count. No individual picks are shown.
- **Marks:** own picks show as correct or wrong. After the final, the page shows "You got N of 3" and how many users got all three.
- **Stored:** when the final is decided, each effective prediction gets `correct_picks` (0–3). A corrected result recomputes it. Brackets and predictions keep their season label and survive `POST /admin/season/reset`.

### Admin Steps In Only for Ties and Exceptions
**User story**
As a Kana Cards admin, I want to resolve a tie the rules can't break, and to correct a result or close predictions when needed, so that the finals never wait on the fixtures site.

**Acceptance criteria**
- **Status:** Admin › Season › Finals shows our Div 1 standings with tiebreak notes, "N/28 played", the bracket state (projected, waiting for tiebreak, set, locked, decided), the lock time and its source (live, ingested, admin), and each series' result and source.
- **Tiebreak:** with a shared tie touching seeds 1–4, the admin orders the tied teams. The fixtures site's order is offered as a suggestion when it has one. The bracket is set, and `admin_finals_tiebreak` is audited.
- **Overrides:** **Pause predictions**, **Close now** and **Set result** (a winner from the series' two teams), audited as `admin_finals_paused`, `admin_finals_closed` and `admin_finals_result_set`.
- **Cross-check:** when the fixtures site's standings are reachable and their seeds 1–4 differ from ours, the card flags it. Nothing else uses them.
- **Admin only:** these endpoints refuse non-admins (`403`).

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `FinalsBracket`, `FinalsPrediction` (new tables, no migration) |
| `backend/finals.py` (new) | Div 1 standings and tiebreaks from our matches; bracket state; seeding and tie hold; lock detection (live, ingested, admin, optional feed time); semi and final results; effective prediction before the lock; `correct_picks`; optional fixtures-site cross-check |
| `backend/routers/finals.py` (new) | `GET /finals`, `PUT /finals/prediction` |
| `backend/routers/admin_finals.py` (new) | `GET /admin/finals`, `PUT /admin/finals/tiebreak`, `POST /admin/finals/pause`, `POST /admin/finals/close`, `PUT /admin/finals/result` |
| `backend/main.py` | Mount both routers; the lock check in the background loop next to the live poll; `GET /config` gains `finals_available` |
| `frontend/index.html`, `frontend/app-finals.js` (new), `frontend/style.css` | Finals tab: match tree, pick controls, states (CSS tokens only, before GUIDED TOUR) |
| `frontend/app-admin-season.js` | Finals card: standings, tiebreak, overrides |
| `markdown/features/core/finals-predictions.md`, `markdown/ui_description/finals.md`, `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_237_finals_prediction_page.py` | Tests |

No migration (new tables only), no new env var.

### Step 1 — Models

```python
class FinalsBracket(Base):            # one per season and division; written when the seeds are set
    __tablename__ = "finals_brackets"
    __table_args__ = (UniqueConstraint("season_label", "division", name="uq_finals_bracket_season_div"),)
    id, season_label, division,                      # "div1"
    seed1_team_id, seed2_team_id, seed3_team_id, seed4_team_id,
    seed_names_json,                                 # names kept for later seasons
    set_at, seed_source,                             # "standings" | "admin_tiebreak"
    group_end_at,                                    # last group game's start; playoff games come after it
    locked_at, lock_source,                          # "live" | "ingested" | "admin" | "feed_time"
    paused,
    sf1_winner, sf2_winner, final_winner,            # team ids
    result_sources_json                              # per series: "matches" | "admin"

class FinalsPrediction(Base):         # append-only: one row per save
    __tablename__ = "finals_predictions"
    id, bracket_id, user_id, sf1_pick, sf2_pick, final_pick, saved_at,
    correct_picks                                    # set on the effective row when the final is decided
```

The effective prediction is a user's latest row with `saved_at < locked_at` (or the latest, while open).

### Step 2 — Standings (`finals.py`)
- **Inputs:** the Div 1 teams (`team_divisions`), each pair's group series result (the Schedule's resolution, else the pair's first two Div 1 games), and the played count out of 28.
- **Order:** points 2/1/0, then series wins, then a head-to-head mini-table among the tied teams, otherwise shared.
- **Seeds:** seeds 1–4 are clear when no shared group spans 1–4 or the 4/5 cut.

### Step 3 — State, lock and results
- **State:** `bracket_state(db)` returns projected, waiting for tiebreak, set, locked or decided.
- **Lock:** the lock check (also in the background loop) looks for a `LiveMatch` in a Div 1 league between a semi's teams, or an ingested match between them after the last group game's start (`group_end_at`; built that way so a bracket stored late still counts semi games already played). It sets `locked_at` to the earliest of `LiveMatch.first_seen_at`, the ingested match's `start_time`, or the admin's time.
- **Results:** the first team to two wins per series. The final is played between the semi winners.

### Step 4 — Endpoints

```
GET  /finals                    public: state, standings summary (played/28), tree (seeds or projected
                                names, ties, live flags, scores), lock; own effective prediction (logged in),
                                count, shares after the lock, results and own marks
PUT  /finals/prediction         logged in: {sf1_pick, sf2_pick, final_pick}; rate-limited; appends a row
GET  /admin/finals              admin: standings with tiebreak notes, state, sources, cross-check flag
PUT  /admin/finals/tiebreak     admin: {order: [team ids of the shared group]}
POST /admin/finals/pause        admin (toggle)
POST /admin/finals/close        admin
PUT  /admin/finals/result       admin: {series: "sf1"|"sf2"|"final", winner}
```

### Step 5 — Frontend
- **Finals tab:** one Div 1 tree (two semi cards and a final card, SVG connectors at desktop width, stacked on phones), pick buttons while open, and the projected, waiting, open, locked and decided states. It's styled with the Kana Cards design system only: picks join the shared selected-state selector list in `style.css`, and winners use `.mark-winner`.
- **Admin:** the Finals card in Admin › Season.

### Step 6 — Tests
- **Standings:** the 2026-10-27 table, with Elisa Oyj and Hoxhunt Fortum shared; a wins tiebreak; a two-team and a three-team head-to-head; the first-two-games fallback.
- **Seeds and states:** projected → set at 28/28; a tie at the cut holds the bracket; admin tiebreak.
- **Lock sources:** live, ingested and admin; a save after a late-learned lock is ignored.
- **Picks:** validation; the logged-out read; shares hidden before the lock.
- **Results:** results from matches; admin override; `correct_picks` and a recompute.
- **Other:** season reset keeps the tables; admin-only endpoints; the cross-check flag; tab visibility; frontend checks (tokens, phone stacking, `aria-pressed`).

## Verification
- **Now:** the Finals tab shows the projected Div 1 tree: 1st · now OP Platinum, 2nd · now Reaktor, and "tie" on 3rd and 4th, with 24/28 (or 25–27/28 as this week's games come in).
- **After the last group series is ingested:** the bracket sets itself within one refresh, or shows "waiting for a tiebreak decision" if Elisa Oyj and Hoxhunt Fortum are still level, and an admin resolves it. Predictions open with no fixtures-site change.
- **First semi game:** picks lock as soon as the game appears in the live list. With the live poll off, they lock when the game is ingested, and later saves are ignored.
- **Results:** after the semis and the final are ingested, the winners are marked, "You got N of 3" shows, and `correct_picks` is stored.
- **Season reset on a copy:** the bracket and predictions are kept.
