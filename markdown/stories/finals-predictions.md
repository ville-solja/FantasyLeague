# Finals Predictions (#237)

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

### Users Predict the Semi-finals and Grand Final
**User story**
As a logged-in player, I want to pick both Div 1 semi-final winners and the grand final once the final four is set, so that I can test my read of the playoffs.

**Acceptance criteria**
- **Open:** pick controls appear when the bracket is set, with "Predictions close when the first semi-final game starts".
- **Picking:**
  - one team per semi;
  - the grand final offers only the user's two semi picks;
  - **Save predictions** stores all three, and missing picks are refused (`422`);
  - picks use `aria-pressed`, with "Your pick: <team>" in text.
- **Valid picks only:** a team not in that series, or a final pick that isn't one of the user's semi picks, is refused (`422`).
- **Lock:** the first semi game seen live or ingested, a fixtures-feed start time once it has passed, or an admin Close now, locks all three. A save after the lock, while paused or before the bracket is set is refused (`409`), and the page shows the picks as locked.
- **Late lock is safe:** saves are kept as revisions. If the lock time is learned later from an ingested game's start, the prediction that counts is the last revision saved before that start, and the page shows that one.
- **Logged out:** the tree shows with "Log in to predict".

### Results and Correct Picks Come From Our Matches
**User story**
As a player who predicted, I want my picks marked right or wrong as the games are played, and my score kept, so that I see how I did and it can count toward a later accolade.

**Acceptance criteria**
- **Results:**
  - a semi is won by the first team to two game wins in Div 1 league matches between its teams after the group stage (after the last group game's start);
  - the grand final is between the semi winners, decided the same way;
  - an admin-set result wins over the matches.
- **After lock:** each series shows the share of picks per team and the prediction count. No individual picks are shown.
- **Marks:** own picks show as correct or wrong. After the final, the page shows "You got N of 3" and how many users got all three.
- **Stored:** when the final is decided, each effective prediction gets `correct_picks` (0–3). A corrected result recomputes it. Brackets and predictions keep their season label and survive `POST /admin/season/reset`.

### Admin Steps In Only for Ties and Exceptions
**User story**
As a Kana Cards admin, I want to resolve a tie the rules can't break, and to correct a result or close predictions when needed, so that the finals never wait on the fixtures site.

**Acceptance criteria**
- **Status:** Admin › Settings › Season › Season Finals shows our Div 1 standings with tiebreak notes, "N/28 played", the bracket state (projected, waiting for tiebreak, set, locked, decided), the lock time and its source (live, ingested, admin, or a fixtures-feed start time), and each series' result and source.
- **Tiebreak:** with a shared tie touching seeds 1–4, the admin orders the tied teams. The fixtures site's order is offered as a suggestion when it has one. The bracket is set, and `admin_finals_tiebreak` is audited.
- **Overrides:** **Pause predictions**, **Close now** and **Set result** (a winner from the series' two teams), audited as `admin_finals_paused`, `admin_finals_closed` and `admin_finals_result_set`.
- **Cross-check:** when the fixtures site's standings are reachable and their seeds 1–4 differ from ours, the Season Finals panel flags it. Nothing else uses them.
- **Admin only:** these endpoints refuse non-admins (`403`).
