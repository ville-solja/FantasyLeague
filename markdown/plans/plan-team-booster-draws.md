# Plan: Team Booster Draws

## Context
Users currently draw cards from the entire player pool with no way to target a specific
team. A team booster pack lets a user spend a configurable number of Tokens (default 3)
to draw a card guaranteed to be from a chosen team's player roster. The feature lives in
the **Deck tab** as a separate "Draw Booster from Team" button and modal, distinct from
the standard draw flow. Duplicate prevention mirrors the standard draw: the user cannot
receive the same (player, rarity) combination twice unless they have already collected
every card available from that team. *Resolves GitHub issue #52.*

## User Stories

### Team Booster Draw
**User story**
As a user, I want to open a team selector in the Deck tab and draw a card from a chosen
team for 3 Tokens so that I can target the players I care about rather than relying on
random selection from the full pool.

**Acceptance criteria**
- A "Draw Booster from Team" button is visible in the Deck tab
- Clicking the button opens a team selection modal listing all teams that have at least
  one player with match data, with each team showing how many drawable (player, rarity)
  combinations remain for the current user
- Teams where the user has already collected every combination are shown greyed out
- Selecting a team and confirming spends `team_booster_cost` Tokens and draws a card
  whose player belongs to that team
- Rarity is rolled using the standard `draw_rate_*` weights — the booster only restricts
  the player pool, not the rarity outcome
- The drawn card is revealed in the existing reveal modal (same UX as standard draw)
- The "Draw Booster" button is disabled with "Not enough Tokens" if the user's balance
  is below the configured cost
- After a successful draw the team selector modal updates its remaining counts and the
  token balance refreshes

### Booster Duplicate Prevention
**User story**
As a user, I want the booster draw to avoid giving me a card I already own so that each
booster adds something new, with a fallback when I have collected the whole team.

**Acceptance criteria**
- The booster draw excludes (player, rarity) combinations the user already owns within
  the selected team
- If all combinations for the team at the rolled rarity are owned, the draw picks any
  unowned rarity for that team's players
- If the user owns every (player, rarity) combination for that team, the draw proceeds
  from the full team player list (no hard failure on collection completion)
- `POST /draw/booster/{team_id}` returns 409 only when the team has no players in the DB

### Configurable Booster Cost (Admin)
**User story**
As an admin, I want to control the booster draw token cost via the Scoring Weights panel
so that I can tune the economy without a code deploy.

**Acceptance criteria**
- A weight key `team_booster_cost` exists with a default value of `3`
- The weight is editable in the admin Scoring Weights panel
- The booster draw endpoint reads this weight at request time (not cached)
- Setting the weight to `1` makes booster draws cost the same as standard draws

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/card_draw.py` | Add `_pick_player_from_team(db, owner_id, rarity, team_id)` |
| `backend/routers/cards.py` | Add `POST /draw/booster/{team_id}` and `GET /deck/booster` endpoints |
| `backend/seed.py` | Add `team_booster_cost` to `DEFAULT_WEIGHTS` |
| `frontend/app-cards.js` | Add booster button, team selector modal, and draw flow |
| `frontend/index.html` | Add "Draw Booster from Team" button and team selector modal to Deck tab |

### Step 1 — Add `team_booster_cost` weight

In `backend/seed.py`, append to `DEFAULT_WEIGHTS`:

```python
{"key": "team_booster_cost", "label": "Team booster draw cost (Tokens)", "value": 3.0},
```

No migration needed — `seed_weights()` inserts missing keys at startup.

### Step 2 — Add `_pick_player_from_team` to `card_draw.py`

```python
def _pick_player_from_team(db, owner_id: int, rarity: str, team_id: int):
    """Pick a player from a specific team for a booster draw.

    Priority: unowned (player, rarity) combos for the team → unowned player at any
    rarity → any player on the team. Returns None only if the team has no players at all.
    """
    from sqlalchemy import func

    team_player_ids = [
        r[0] for r in
        db.query(PlayerMatchStats.player_id)
          .filter(PlayerMatchStats.team_id == team_id)
          .distinct().all()
    ]
    if not team_player_ids:
        return None

    # First preference: players the user doesn't own at this specific rarity
    owned_this_rarity = {
        r[0] for r in
        db.query(Card.player_id).filter(
            Card.owner_id == owner_id,
            Card.card_type == rarity,
            Card.player_id.in_(team_player_ids),
        ).all()
    }
    eligible = [pid for pid in team_player_ids if pid not in owned_this_rarity]

    if not eligible:
        # Fallback: any player on the team (duplicate rarity allowed)
        eligible = team_player_ids

    # Weight by inverse total ownership count for proportionality
    owned_counts = {
        r[0]: r[1] for r in
        db.query(Card.player_id, func.count(Card.id))
          .filter(Card.owner_id == owner_id, Card.player_id.in_(eligible))
          .group_by(Card.player_id).all()
    }
    max_count = max(owned_counts.values(), default=0)
    weights = [max_count - owned_counts.get(pid, 0) + 1 for pid in eligible]
    chosen_id = random.choices(eligible, weights=weights, k=1)[0]
    return db.get(Player, chosen_id)
```

### Step 3 — Add backend endpoints to `routers/cards.py`

#### `GET /deck/booster`

Returns per-team drawable card counts for the requesting user. Public; unauthenticated
callers see total possible counts (not adjusted for ownership).

```python
@router.get("/deck/booster")
def get_booster_deck(request: Request, db=Depends(get_db)):
    rarities = ["common", "rare", "epic", "legendary"]
    user_id = request.session.get("user_id") if hasattr(request, "session") else None

    teams = db.query(Team).all()
    result = []
    for team in teams:
        team_player_ids = [
            r[0] for r in
            db.query(PlayerMatchStats.player_id)
              .filter(PlayerMatchStats.team_id == team.id)
              .distinct().all()
        ]
        if not team_player_ids:
            continue
        all_combos = {(pid, r) for pid in team_player_ids for r in rarities}
        if user_id:
            owned = {
                (c.player_id, c.card_type)
                for c in db.query(Card).filter(
                    Card.owner_id == user_id,
                    Card.player_id.in_(team_player_ids),
                ).all()
            }
            remaining = len(all_combos - owned)
        else:
            remaining = len(all_combos)
        result.append({
            "team_id": team.id,
            "team_name": team.name,
            "logo_url": team.logo_url,
            "remaining": remaining,
        })
    result.sort(key=lambda t: (t["remaining"] == 0, t["team_name"] or ""))
    return result
```

#### `POST /draw/booster/{team_id}`

```python
@router.post("/draw/booster/{team_id}")
def draw_booster(team_id: int, db=Depends(get_db),
                 current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    weights = {w.key: w.value for w in db.query(Weight).all()}
    cost = int(weights.get("team_booster_cost", 3))

    if (user.tokens or 0) < cost:
        raise HTTPException(status_code=409, detail="Not enough tokens")

    rarity = _roll_rarity(db)
    player = _pick_player_from_team(db, user_id, rarity, team_id)
    if player is None:
        raise HTTPException(status_code=409,
                            detail="No players available for this team")

    card = Card(card_type=rarity, player_id=player.id, owner_id=user_id,
                league_id=None, is_active=False, generation=1)
    db.add(card)
    db.flush()

    active_count = db.query(Card).filter(
        Card.owner_id == user_id, Card.is_active == True
    ).count()
    card.is_active = active_count < ROSTER_LIMIT

    _assign_modifiers(db, card, weights)

    team_row = db.execute(text("""
        SELECT t.name, t.logo_url FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        WHERE s.player_id = :pid ORDER BY s.match_id DESC LIMIT 1
    """), {"pid": player.id}).first()

    user.tokens = (user.tokens or 0) - cost
    _audit(db, "token_booster_draw", actor_id=user_id, actor_username=user.username,
           detail=f"card_id={card.id} player={player.name} rarity={rarity} "
                  f"team_id={team_id} cost={cost}")
    db.commit()

    mods = _card_modifiers_map(db, [card.id]).get(card.id, {})
    return {
        "id": card.id,
        "card_type": card.card_type,
        "player_id": player.id,
        "player_name": player.name,
        "avatar_url": player.avatar_url,
        "team_name": team_row.name if team_row else team.name,
        "team_logo_url": team_row.logo_url if team_row else team.logo_url,
        "is_active": card.is_active,
        "tokens": user.tokens,
        "modifiers": _format_modifiers(mods),
    }
```

### Step 4 — Frontend: Deck tab booster button and modal

In `frontend/index.html`, add inside the Deck tab section:

```html
<!-- Team Booster Draw -->
<button id="boosterBtn">Draw Booster from Team</button>

<!-- Team selector modal -->
<div id="boosterModal" class="modal-overlay hidden">
  <div class="modal">
    <h2>CHOOSE A TEAM</h2>
    <div id="boosterTeamGrid"></div>
    <div id="boosterCostLabel"></div>
    <button id="boosterDrawBtn" disabled>Draw Booster</button>
    <button aria-label="Close" onclick="closeBoosterModal()">×</button>
  </div>
</div>
```

In `frontend/app-cards.js`:

- `loadBoosterTeams()` — fetches `GET /deck/booster`, renders each team as a selectable
  tile showing logo, name, and remaining count; greyed out when `remaining === 0`
- Clicking a tile sets `_selectedBoosterTeamId` and enables the Draw button
- `drawBooster()` — posts to `POST /draw/booster/{teamId}`, on success calls the existing
  `showReveal()` / reveal modal flow, then calls `loadBoosterTeams()` to refresh counts
- `openBoosterModal()` calls `loadBoosterTeams()` and shows the modal
- `closeBoosterModal()` hides the modal and clears the selection
- `#boosterBtn` is disabled and shows "Not enough Tokens" when
  `_tokenBalance < team_booster_cost` (read from config or hardcoded default 3)

The `team_booster_cost` can be surfaced via `GET /config` (see Step 5) so the frontend
knows what cost to display without hard-coding.

### Step 5 — Expose `team_booster_cost` in `/config`

Extend `GET /config` in `backend/main.py` to return the booster cost:

```python
@app.get("/config")
def get_config(db=Depends(get_db)):
    booster_row = db.query(Weight).filter_by(key="team_booster_cost").first()
    booster_cost = int(booster_row.value) if booster_row else 3
    return {
        "token_name": TOKEN_NAME,
        "initial_tokens": INITIAL_TOKENS,
        "app_version": _APP_VERSION,
        "app_release": _APP_RELEASE,
        "team_booster_cost": booster_cost,
    }
```

Store `_teamBoosterCost` in `app-globals.js` alongside other config values and populate
it in `loadConfig()`.

---

## Verification
- Open the Deck tab; confirm "Draw Booster from Team" button is present
- Click it; confirm the team selector modal opens with all teams and remaining counts
- Select a team with remaining > 0; confirm the Draw button enables
- Draw a booster; verify the revealed card's player is from the selected team
- Verify the token balance decreases by `team_booster_cost` (default 3)
- Verify the remaining count for the selected team decreases by 1 after the draw
- Teams with remaining = 0 should be greyed out and unselectable
- Attempt a booster with 0 tokens; expect the Draw Booster button to be disabled
- Change `team_booster_cost` to 1 via admin Scoring Weights; restart; verify cost is 1
- Verify `GET /config` returns the updated `team_booster_cost`
- Draw until all (player, rarity) combos are owned for a small team; next draw should
  still succeed (fallback path)
- Attempt `POST /draw/booster/{nonexistent_team_id}`; expect 404
- Verify the audit log records `token_booster_draw` with `team_id` and `cost`
