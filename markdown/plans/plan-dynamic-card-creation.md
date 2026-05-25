# Plan: Dynamic Card Creation

## Context
Currently cards are pre-generated into a shared pool at ingest time (fixed counts: 1 legendary,
2 epic, 4 rare, 8 common per player) and drawn from that finite pool. This makes mid-season
player additions awkward (requiring a manual top-up action) and limits flexibility in rarity
distribution. The new model generates each card at draw time: rarity is rolled from configurable
percentage weights, the player is chosen with a proportionality bias so that new players and
under-represented players are preferred, and duplicates (same user, same player, same rarity)
are prevented. The shared pool and all pool-management admin actions are deprecated. Resolves
GitHub issue #65.

## User Stories

### Draw a Card with Weighted Rarity
**User story**
As a user, I want the rarity of each drawn card to be determined by configured drop rates so
that I have a realistic chance of high-rarity cards on every draw.

**Acceptance criteria**
- Each draw rolls a rarity from configurable percentage weights (`draw_rate_common`,
  `draw_rate_rare`, `draw_rate_epic`, `draw_rate_legendary`; defaults approximate the old
  pool ratios)
- The rolled rarity is reflected in the card shown in the reveal modal
- A card is always created — draws never fail due to pool exhaustion

### Player Proportionality on Draw
**User story**
As a user, I want the draw system to prefer players I have fewer cards of so that my collection
stays diverse and mid-season additions are accessible.

**Acceptance criteria**
- Players for whom the user already holds the rolled rarity are excluded from selection
- Among remaining eligible players, those with fewer total cards in the user's collection
  are assigned a higher selection weight
- If every active player already owns the drawn rarity, the draw proceeds with full player
  selection (no hard failure)

### No Duplicate Rarity–Player Combinations
**User story**
As a user, I want the system to prevent me from drawing an identical card (same player and
rarity) twice so that each draw adds something new to my collection.

**Acceptance criteria**
- `POST /draw` never returns a card whose `(owner_id, player_id, card_type)` combination
  already exists in the `cards` table
- If a user owns the drawn rarity for every eligible player, the uniqueness constraint is
  relaxed for that draw (fallback to allow any player, then any rarity)
- The constraint is per user — other users owning the same player/rarity does not affect
  availability

### Configurable Drop Rates
**User story**
As an admin, I want to configure the rarity drop rates via the scoring weights so that I
can tune the economy without a code deploy.

**Acceptance criteria**
- Four new weight keys exist: `draw_rate_common`, `draw_rate_rare`, `draw_rate_epic`,
  `draw_rate_legendary`
- These are seeded with sensible defaults and editable in the Scoring Weights admin panel
- The draw logic reads these values at draw time (not cached between requests)
- Weights do not need to sum to exactly 100; relative proportions are used

### Deprecate Pool Management
**User story**
As an admin, I want pre-generation and pool top-up actions to be removed so that the
system is simpler to operate.

**Acceptance criteria**
- `POST /admin/top-up-cards` is removed (returns 410 Gone or is deleted)
- Card generation is removed from the ingest pipeline — ingest creates only player records
- `GET /deck` returns a count of how many distinct (player, rarity) combinations the
  requesting user can still draw (i.e. combinations they do not yet own), replacing the
  old unowned pool count
- Existing owned cards in users' collections are unaffected by the migration

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/cards.py` | Rewrite `POST /draw` draw logic; update `GET /deck` |
| `backend/routers/admin.py` | Remove `POST /admin/top-up-cards` |
| `backend/seed.py` | Add four `draw_rate_*` weight seeds |
| `backend/migrate.py` | No new columns needed; seed migration for new weight keys |
| `frontend/app-cards.js` | `GET /deck` response shape change — update pool display |
| `markdown/features/core/cards.md` | Update Deck Structure and Drawing Cards sections |

### Step 1 — Seed new weight keys

Add four default weights to `seed.py` in the `DEFAULT_WEIGHTS` list:

```python
{"key": "draw_rate_common",     "label": "Draw rate: Common (%)",     "value": 60.0},
{"key": "draw_rate_rare",       "label": "Draw rate: Rare (%)",       "value": 25.0},
{"key": "draw_rate_epic",       "label": "Draw rate: Epic (%)",       "value": 10.0},
{"key": "draw_rate_legendary",  "label": "Draw rate: Legendary (%)",  "value": 5.0},
```

Defaults approximate the old pool ratios (8 common, 4 rare, 2 epic, 1 legendary → 53/27/13/7%).

### Step 2 — Rarity selection helper

In `backend/routers/cards.py`, add a helper that reads the four weight keys and performs a
weighted random choice:

```python
def _roll_rarity(db) -> str:
    keys = ["draw_rate_common", "draw_rate_rare", "draw_rate_epic", "draw_rate_legendary"]
    labels = ["common", "rare", "epic", "legendary"]
    weights = []
    for k in keys:
        w = db.query(Weight).filter_by(key=k).first()
        weights.append(float(w.value) if w else 1.0)
    return random.choices(labels, weights=weights, k=1)[0]
```

### Step 3 — Player selection helper

Add a helper that returns a weighted list of eligible `Player` records. Players the user
does not own for the given rarity get a higher weight; players with fewer total cards in
the user's collection are further up-weighted:

```python
def _pick_player(db, owner_id: int, rarity: str) -> Player:
    all_players = db.query(Player).all()
    # Cards already owned by this user
    owned = db.query(Card).filter_by(owner_id=owner_id).all()
    owned_by_player = {}
    for c in owned:
        owned_by_player.setdefault(c.player_id, []).append(c.card_type)

    eligible = [p for p in all_players
                if rarity not in owned_by_player.get(p.id, [])]
    if not eligible:
        eligible = all_players  # fallback: relax uniqueness constraint

    # Weight inversely by total cards owned for this player
    weights = [1.0 / (1 + len(owned_by_player.get(p.id, []))) for p in eligible]
    return random.choices(eligible, weights=weights, k=1)[0]
```

### Step 4 — Rewrite `POST /draw`

Replace the unowned-pool selection with:

1. Call `_roll_rarity(db)` to get the rarity.
2. Call `_pick_player(db, owner_id, rarity)` to get the player.
3. Create a new `Card` row: `Card(card_type=rarity, player_id=player.id, owner_id=owner_id, generation=1)`.
4. Assign modifiers as before (existing logic unchanged).
5. Deduct token, commit, return response.

Remove the old unowned-pool query entirely.

### Step 5 — Update `GET /deck`

Replace the unowned-pool count with per-user availability: count distinct
`(player_id, card_type)` combinations NOT yet owned by the requesting user,
per rarity. Requires authentication (returns the authenticated user's remaining
combinations). If the user is not authenticated, return totals across all players.

### Step 6 — Remove `POST /admin/top-up-cards`

Delete the endpoint from `backend/routers/admin.py`. Update `markdown/features/core/admin.md`
to remove the top-up entry.

### Step 7 — Remove card generation from ingest

In `backend/routers/admin.py` (the ingest endpoint), remove the call to the card generation
helper. Ingest should only create `Player`, `Team`, `Match`, and `PlayerMatchStats` records.

### Step 8 — Frontend: update deck display

In `frontend/app-cards.js`, update the handler for the `GET /deck` response to reflect the
new shape (available combinations per rarity rather than unowned pool counts). Adjust any
displayed text from "X cards remaining" to "X draws available" or similar.

## Verification
- Draw 20 cards as a single user — confirm rarity distribution is roughly 60/25/10/5 over many draws
- Confirm no `(owner, player, rarity)` duplicate is ever returned in normal operation
- Add a new player mid-season (ingest a new league) — confirm new player appears in draws without a top-up action
- Change `draw_rate_legendary` to 100 via admin panel — every card drawn should be legendary
- Confirm `GET /deck` returns a count of remaining unique draws for the logged-in user
- Confirm existing owned cards and weekly scores are unaffected by the migration
- Confirm `POST /admin/top-up-cards` returns 404 or is absent
