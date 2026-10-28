# Finals Predictions

A **Finals** tab that draws the Div 1 playoff match tree from our own league results, and lets logged-in users predict both semi-finals and the grand final. It never waits for the league's fixtures site: the standings, the bracket, the lock and the results all come from ingested matches. Issue #237; plan: `markdown/plans/plan-issue-237-finals-prediction-page.md`. Code: `backend/finals.py` (logic), `backend/routers/finals.py`, `backend/routers/admin_finals.py`, `frontend/app-finals.js`, the Season Finals panel (Admin › Settings › Season) in `frontend/app-admin-season.js`.

---

## Standings and seeding

- **Inputs:** the Div 1 teams (`team_insights.team_divisions`: the division of most of a team's league matches; a league whose name contains "Lower" is Div 2) and the Div 1 league matches between two Div 1 teams. Matches in Div 2 leagues, or against a team that is mostly Div 2, never count.
- **Group series:** for each pair, the series the Schedule resolved for it (read from the Schedule's cached data, never fetched for this), otherwise the pair's first two Div 1 league games by `start_time`. A series counts once both games have a result. A third game between the pair (a playoff) is not part of the group table.
- **Points:** series win 2, draw (1–1) 1, loss 0. The total is n·(n−1)/2 series for n Div 1 teams (28 for 8).
- **Tiebreaks**, in the fixtures site's order: points, then series wins, then a head-to-head mini-table (points from only the series among the tied teams). When the mini-table splits off some teams, the rest are compared again among themselves. Teams still level are **shared** (same rank). Each row carries a note: `series wins`, `head-to-head` or `shared`.
- **Bracket set:** when every group series has a result and no shared rank touches seeds 1–4 (inside the top four or across the 4th/5th cut), the next refresh stores the bracket (`seed_source = "standings"`): semi-final 1 is seed 1 vs seed 4, semi-final 2 is seed 2 vs seed 3.
- **Tie at the cut:** a shared rank touching seeds 1–4 holds the bracket in `waiting_for_tiebreak` until an admin orders the tied teams (`seed_source = "admin_tiebreak"`).
- **Refresh:** `finals.refresh(db)` runs in the live-poll loop right after each live poll (`main._run_finals_check`, best effort), on every `PUT /finals/prediction` and admin call, and on `GET /finals` at most once per 30 seconds (see Caching). The live thread runs only with `STEAM_API_KEY` set and outside `DEMO_MODE`; otherwise the bracket refreshes on page and admin requests only, and the lock may then be learned late, which the revision rule covers. Only one bracket exists per season label and division (`uq_finals_bracket_season_div`).

## States

| State | When | Page |
|---|---|---|
| `projected` | Group series remain | "1st place · now OP Platinum" and so on, "tie: …" for a shared rank, "N/28 group series played"; no picks |
| `waiting_for_tiebreak` | All series played, shared rank touches seeds 1–4 | "Seeding waits for a tiebreak decision" |
| `set` | Bracket stored, not locked | Pick controls, "Predictions close when the first semi-final game starts" (or "Predictions are paused") |
| `locked` | `locked_at` set | "Predictions closed"; shares per team and the prediction count |
| `decided` | The grand final has a winner | Winners, own marks, "You got N of 3", how many users got all three |

## Lock

All three picks lock together at the earliest of:

- `live`: a `LiveMatch` in a Div 1 league between a semi's two teams, first seen after the group stage (`first_seen_at`);
- `ingested`: an ingested Div 1 league match between a semi's two teams after the group stage (`start_time`);
- `feed_time`: a start time the fixtures feed gives a semi pairing, once it has passed (optional; the feed has no playoff fixtures today);
- `admin`: **Close now**, or **Set result** while predictions are still open (the current time; an earlier lock is kept).

The lock only ever moves earlier. "After the group stage" means after the last group game's start (`group_end_at`, stored on the bracket), so a bracket stored late still counts every semi game.

**Late detection is safe:** every save is a new `finals_predictions` row. A user's effective prediction is the latest row with `saved_at < locked_at` (the latest row while open). When the lock is learned late from an ingested game, saves made after that game's start are ignored automatically.

## Results

- A series is won by the first team to two game wins in Div 1 league matches between its two teams after the group stage (`source = "matches"`).
- The grand final is between the two semi winners, decided the same way.
- **Set result** (admin) wins over the matches (`source = "admin"`) and is never recomputed. Setting a result while predictions are open also locks them at that moment, so nobody can save after a result is known. If a corrected semi result changes the final's teams, an admin final result for a team no longer in it is cleared.
- When the final is decided, each effective prediction gets `correct_picks` (0–3); superseded rows and rows saved after the lock stay `NULL`. A corrected result recomputes them; an undecided final clears them.

## Predictions

- **Who:** logged-in website users (Twitch soft accounts never sign in on the website). One effective prediction per user and season.
- **Picks:** one team per semi, and a grand-final pick that must be one of the user's two semi picks.
- **Privacy:** no endpoint returns anyone else's picks. After the lock, `GET /finals` gives per series only the share of effective picks per team and the count.
- **Rewards:** none. The stored `correct_picks` are for a later Finals prediction accolade (its own issue).
- **Kept:** `finals_brackets` and `finals_predictions` keep their season label and are not touched by `POST /admin/season/reset`. Team names are copied into `seed_names_json`, because a reset deletes the teams.

## Endpoints

### `GET /finals`
Public; reads the session if there is one. Returns `state`, `season_label`, `division` (`div1`), `played`, `total`, `notice`, `tree` (three series `sf1`, `sf2`, `final`, each with `label`, `teams`, `score` once games are in, `live`, `winner`), `open`, `can_predict`, `paused`, `locked_at`, `logged_in`, plus:
- `prediction`: the caller's effective picks with `marks` per series (`true`, `false`, or `null` while undecided); `null` when logged out or none;
- `results` (locked and decided): `{series: {count, shares: [{team_id, pct}]}}`;
- `summary` (decided): `{correct, of: 3, perfect_count, prediction_count}`.

Before the bracket is set, the semi teams are slots: `{slot: "1st place", now: "<team>" | null, tie, tied: [names]}`.

### `PUT /finals/prediction`
Logged in (`401` otherwise); rate-limited to 10 saves a minute per user (`RATE_LIMIT_FINALS_PREDICTION` in `routers/finals.py`, a constant, not an env var) and behind the usual Origin check. Body `{sf1_pick, sf2_pick, final_pick}` (team ids, all required). Appends a row and returns `{prediction}`. Saving the same three picks as the latest save adds no row.
- `422`: a missing pick, a semi pick outside that semi, or a final pick that isn't one of the two semi picks;
- `409`: the bracket isn't set yet (`projected`, `waiting_for_tiebreak`), predictions are paused, or they are locked;
- `429`: the user already has `finals.MAX_REVISIONS` (20) saves for this bracket; the last save still counts. Besides the route limit, this keeps the table small.

### Admin (`require_admin`, `403` "Admin access required" otherwise)
| Method and path | Body | Does | Audit action |
|---|---|---|---|
| `GET /admin/finals` | | Standings with tiebreak notes, played/total, state, the tied teams and the fixtures site's order as a `suggestion`, the bracket (seed source, lock time and source, paused, prediction count, each series with winner and result source) and `cross_check` | |
| `PUT /admin/finals/tiebreak` (recent re-auth) | `{order: [team ids]}` | Only in `waiting_for_tiebreak` (`409`); `order` must hold exactly the tied teams once (`422`); stores the bracket | `admin_finals_tiebreak` |
| `POST /admin/finals/pause` | | Toggles `paused` (saves answer `409` while paused); `409` without a bracket | `admin_finals_paused` |
| `POST /admin/finals/close` (recent re-auth) | | Locks now (`lock_source = "admin"`), keeping an earlier lock; `409` without a bracket | `admin_finals_closed` |
| `PUT /admin/finals/result` (recent re-auth) | `{series: "sf1" \| "sf2" \| "final", winner}` | Sets the winner and locks predictions if still open (`422` if not one of the series' two teams; `409` for the final before both semis have winners) | `admin_finals_result_set` |

### `GET /config`
`finals_available`: true once every Div 1 team has played at least one group series (or a bracket exists for the season), until the season label is archived by End Season. Cached for 60 seconds per process, so page loads don't recompute the standings.

## Fixtures-site cross-check (optional)

`GET /admin/finals` reads the fixtures site's standings at `standings` next to `SCHEDULE_FIXTURES_URL` (for `…/api/fixtures.json`, that's `…/api/standings`), with a 4-second timeout, no redirects and at most 256 KB read (a larger body counts as unreadable); the result, including a failure, is cached for 5 minutes. The JSON is read leniently (a list of rows, or `upper` / `div1` / `standings` keys; team in `team`, `name` or `team_name`; `position` or `rank`; `shared`). It is used for two hints only:
- `cross_check.differs`: the site's seeds 1–4 differ from ours (in order once the bracket is set, as a set before);
- `suggestion`: the tied teams in the site's order, when it ranks them apart.

Unset, unreachable or unreadable gives `reachable: false` and nothing else changes. Nothing else reads the fixtures site.

## Caching and limits

`GET /finals` and `GET /config` are public and run on page views, so they don't recompute everything on every request (all caches are per process, in `finals.py`):
- **`GET /finals`:** the shared part (state, tree, shares, summary) comes from a refresh at most 30 seconds old (`PUBLIC_CACHE_SECONDS`). The caller's own prediction, marks and "You got N of 3" are read fresh on every request. Saves and admin actions always refresh first, so a lock learned in the meantime still applies, and the revision rule (the last save before the lock counts) covers the rest. Admin actions clear the caches.
- **`finals_available`:** 60 seconds (`AVAILABILITY_CACHE_SECONDS`).
- **Fixtures-site standings:** 5 minutes (`SITE_CACHE_SECONDS`).
- **`correct_picks`** is recomputed only when the lock time or a series winner changes, not on every refresh.
- **Re-auth:** Resolve tie, Close now and Set result need a recent password (or Steam) re-entry (`require_recent_reauth`); the admin card sends them through `adminFetch`, which shows the prompt. Pause predictions doesn't need one.

## Data model

- `finals_brackets`: `season_label`, `division`, `seed1_team_id` … `seed4_team_id`, `seed_names_json`, `set_at`, `group_end_at`, `seed_source`, `locked_at`, `lock_source`, `paused`, `sf1_winner`, `sf2_winner`, `final_winner`, `result_sources_json`. Unique on (`season_label`, `division`).
- `finals_predictions`: `bracket_id`, `user_id`, `sf1_pick`, `sf2_pick`, `final_pick`, `saved_at`, `correct_picks`. Append-only.

New tables, so no migration. No new environment variable.
