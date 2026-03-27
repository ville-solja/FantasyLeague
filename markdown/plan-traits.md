# Plan: Card Traits

## Context

Cards represent players with modifiers — traits are those modifiers. A player profile shows who someone is; a card shows what they're worth to **you**, shaped by the traits rolled onto that card at draw time.

Traits make the same player feel different across two users' collections: one user's Mirobg might be a Glass Cannon that scores huge when he carries, another's might be a Support Anchor that rewards warding. This creates draft strategy and card rarity feels earned rather than just cosmetic.

---

## Design Principles

- **Simple traits** are transparent: "+25% kills" reads instantly
- **Medium traits** are event-based: trigger off something that happens in a match
- **Complex traits** are trade-offs: one thing goes up, another goes down — risk for reward
- **Pinnacle traits** are all-or-nothing or matchup-aware — high variance, Legendary only
- Traits are assigned at draw time and are **immutable** on the card after draw
- No trait should require data that can't be derived from OpenDota match responses
- **Every numeric value in a trait effect is a configurable parameter**, editable by admins at runtime without code changes — same model as base scoring weights

---

## Trait Tiers

### Tier 1 — Simple (all rarities)

Pure weight multipliers. No new data required — everything works with current stats.

Values shown are **defaults**; all are stored as `trait_params` rows and editable via the admin panel.

| Key | Name | Effect | Params (default) |
|---|---|---|---|
| `precise` | **Precision** | Kill weight scaled | `kill_multiplier` = 1.25 |
| `warden` | **Warden** | Ward weight scaled (obs + sen) | `ward_multiplier` = 1.35 |
| `wrecker` | **Wrecker** | Tower damage weight scaled | `tower_multiplier` = 1.4 |
| `efficient` | **Efficient** | GPM weight scaled | `gpm_multiplier` = 1.25 |
| `playmaker` | **Playmaker** | Assist weight scaled | `assist_multiplier` = 1.3 |
| `resilient` | **Resilient** | Death penalty reduced | `death_reduction` = 0.4 (multiplied against death weight) |
| `all_rounder` | **All-Rounder** | All weights scaled | `all_multiplier` = 1.1 |
| `last_rites` | **Last Rites** | Kill weight up, death penalty up | `kill_multiplier` = 1.4, `death_multiplier` = 1.3 |

`last_rites` is the entry-level trade-off: slightly more dangerous version of Precision that bites you on bad games.

---

### Tier 2 — Medium (Rare+)

Conditional bonuses triggered by match events. Require 2–3 new fields ingested from OpenDota (see Data Requirements section).

Values shown are **defaults**; all numeric parameters are stored as `trait_params` rows.

| Key | Name | Trigger | Params (default) |
|---|---|---|---|
| `first_blood` | **First Blood** | Player claims first blood | `bonus_pts` = 20 |
| `deathless` | **Untouchable** | Player finishes with 0 deaths | `bonus_pts` = 25 |
| `triple_kill` | **Triple Threat** | Player gets a triple kill or better | `bonus_pts` = 20 |
| `rampage` | **Rampage** | Player gets a rampage (5 kills without dying) | `bonus_pts` = 60 |
| `hero_main` | **Hero Main** | Player plays their most-frequent hero in this league | `all_multiplier` = 1.35 |
| `versatile` | **Versatile** | Player plays a different hero than their previous match | `bonus_pts` = 15 |
| `shutdown` | **Shutdown** | Player kills an opponent with ≥3 kills at time of death | `bonus_per_shutdown` = 8, `kill_streak_threshold` = 3 |
| `comeback` | **Comeback** | Player's team wins while net worth was behind at midpoint | `all_multiplier` = 1.5 |

**Notes:**
- `hero_main` uses only heroes played within the current league, not all-time, to reward consistent picks in this specific meta
- `comeback` requires storing net worth at match midpoint — this may be simplified to "team was losing at some point" if granular data is unavailable
- `shutdown` requires `kill_log` from OpenDota which is richer match data — lower priority
- `kill_streak_threshold` on `shutdown` being configurable means the admin can tighten or loosen what counts as a shutdown target

---

### Tier 3 — Complex / Trade-off (Epic+)

These are the strategically interesting traits. High upside paired with meaningful downside. The user knows the risk when they see the trait on the card.

Values shown are **defaults**; every multiplier is a configurable `trait_params` row. This is especially important here — the balance of trade-offs (how much you gain vs. lose) can be tuned post-launch without touching code.

| Key | Name | Effect | Params (default) |
|---|---|---|---|
| `glass_cannon` | **Glass Cannon** | Kill weight up, death penalty up | `kill_multiplier` = 2.0, `death_multiplier` = 2.5 |
| `reckless` | **Reckless** | Kill weight up, assist weight down — go for blood, not teamplay | `kill_multiplier` = 1.75, `assist_multiplier` = 0.3 |
| `support_anchor` | **Support Anchor** | Ward weight up, kills and GPM suppressed | `ward_multiplier` = 2.5, `kill_multiplier` = 0.0, `gpm_multiplier` = 0.5 |
| `gold_hungry` | **Gold Hungry** | GPM weight up, assist weight suppressed — farms instead of helping | `gpm_multiplier` = 2.0, `assist_multiplier` = 0.25 |
| `pact_of_blood` | **Pact of Blood** | Kill and death weights both amplified — pure variance | `kill_multiplier` = 2.0, `death_multiplier` = 2.0 |
| `feast_or_famine` | **Feast or Famine** | 0 deaths → all scoring scaled up; any death → scaled down | `success_multiplier` = 1.5, `fail_multiplier` = 0.6 |
| `siege_master` | **Siege Master** | Tower damage weight greatly up, kills zeroed — purely objective | `tower_multiplier` = 3.0, `kill_multiplier` = 0.0 |
| `shadow_carry` | **Shadow Carry** | GPM and kills up, assists and wards zeroed — hard carry, zero teamwork | `gpm_multiplier` = 1.5, `kill_multiplier` = 1.5, `assist_multiplier` = 0.0, `ward_multiplier` = 0.0 |
| `vision_lord` | **Vision Lord** | Ward weight greatly up, kills/GPM/deaths all zeroed — the ultimate ward bot | `ward_multiplier` = 3.0, `kill_multiplier` = 0.0, `gpm_multiplier` = 0.0, `death_multiplier` = 0.0 |

`vision_lord` and `siege_master` are niche but create interesting fantasy decisions — a "useless" player by kill stats might suddenly be a very desirable card for someone with these traits stacked.

---

### Tier 4 — Pinnacle (Legendary only)

High-stakes, match-outcome-aware, or cross-match aggregated. These are the traits that make a Legendary feel genuinely different from an Epic.

Values shown are **defaults**; all numeric parameters are configurable `trait_params` rows.

| Key | Name | Effect | Params (default) |
|---|---|---|---|
| `win_or_nothing` | **Win or Nothing** | Win → all scoring scaled up; loss → zeroed | `win_multiplier` = 2.0, `loss_multiplier` = 0.0 |
| `underdog` | **Underdog** | Kill weight scales with opposing team's win-rate advantage | `base_multiplier` = 1.0, `scale_factor` = 0.5 (per win-rate percentile gap) |
| `momentum` | **Momentum** | Each above-average match grows the multiplier; resets on below-average | `step` = 0.10 (multiplier increment per streak match), `max_multiplier` = 2.0 |
| `clutch_factor` | **Clutch Factor** | Team wins AND player tops team kill chart → flat bonus | `bonus_pts` = 80 |
| `on_tilt` | **On Tilt** | Normally suppressed; deathless match primes the next match for a spike | `normal_multiplier` = 0.5, `primed_multiplier` = 3.0 |

**`win_or_nothing`** is the clearest implementation path today — we already have `radiant_win` and `team_id` per match. Making `loss_multiplier` configurable (rather than hardcoded to 0) means it could be softened to 0.25 for a less punishing variant without any code change.

**`underdog`** requires team win-rate tracking within the league — derivable from current match data, just needs a helper query. `scale_factor` controls how steeply the bonus grows with rank discrepancy.

**`momentum`** and **`on_tilt`** require cross-match state per card — a `CardTraitState` table, or computed on each full scoring pass. `max_multiplier` on Momentum prevents runaway accumulation.

---

## Trait Compatibility Rules

Some trait combinations are redundant, overpowered, or contradictory. At assignment time, enforce:

| Rule | Reason |
|---|---|
| Max one trade-off trait (Tier 3) per card | Two trade-off traits can compound to absurd levels |
| `support_anchor` and `glass_cannon` are mutually exclusive | Directly contradictory stat directions |
| `vision_lord` and `shadow_carry` are mutually exclusive | Same — both zero out the other's core stat |
| `feast_or_famine` and `win_or_nothing` should not co-exist | Both are binary match-outcome gates — too many conditions |
| `hero_main` and `versatile` are mutually exclusive | Direct contradiction |

---

## Trait Assignment by Rarity

| Rarity | # Traits | Pool |
|---|---|---|
| Common | 1 | Tier 1 only |
| Rare | 1 | Tier 1–2 (70/30 split) |
| Epic | 2 | Tier 1–3, subject to compatibility rules |
| Legendary | 2–3 | Any tier; guaranteed one Tier 3 or 4 |

Assignment is random within the tier pool at draw time, seeded by card ID so re-draws of the same card always produce the same traits (deterministic per card, not per draw event).

---

## Data Requirements

### New fields on `PlayerMatchStats`

Required for Tier 2+ traits:

| Field | Type | OpenDota key | Used by |
|---|---|---|---|
| `hero_id` | Integer | `hero_id` | `hero_main`, `versatile` |
| `firstblood_claimed` | Boolean | `firstblood_claimed` | `first_blood` |
| `multi_kills` | Integer | max key in `multi_kills` dict (e.g. 5 = rampage) | `rampage`, `triple_kill` |
| `net_worth` | Integer | `net_worth` | `comeback` (future) |

Migration: `ALTER TABLE player_match_stats ADD COLUMN ...` in the lifespan startup block (existing pattern).

Re-ingestion: existing rows will have NULLs for new fields. A one-time backfill endpoint (admin only) can re-fetch match data to populate them. Until backfilled, Tier 2 traits that require these fields score as 0 bonus (graceful degradation).

### New fields on `PlayerMatchStats` for per-player win/loss

Needed for `win_or_nothing`, `clutch_factor`:

| Field | Type | Derivation |
|---|---|---|
| `won` | Boolean | Join `Match` on `match_id`, check `radiant_win == (team_id == radiant_team_id)` |

This can be a computed column derived at query time rather than stored — avoids stale data.

---

## Schema Changes

### New table: `traits`

```python
class Trait(Base):
    __tablename__ = "traits"
    key         = Column(String, primary_key=True)  # e.g. "glass_cannon"
    name        = Column(String)                     # Display name
    description = Column(String)                     # Tooltip shown in UI
    tier        = Column(Integer)                    # 1–4
    min_rarity  = Column(String)                     # "common", "rare", "epic", "legendary"
```

Seeded at startup via `seed_traits()` from a static definition dict (same pattern as `seed_weights()`).

### New table: `trait_params`

Mirrors the existing `weights` table pattern. One row per configurable parameter per trait.

```python
class TraitParam(Base):
    __tablename__ = "trait_params"
    trait_key = Column(String, ForeignKey("traits.key"), primary_key=True)
    param_key = Column(String, primary_key=True)  # e.g. "kill_multiplier", "bonus_pts"
    label     = Column(String)                     # Human-readable, shown in admin UI
    value     = Column(Float)
```

Composite primary key on `(trait_key, param_key)`. Seeded at startup via `seed_traits()` from a static definition dict — if a row already exists, its value is left untouched (same pattern as `seed_weights()`).

Example seed rows:

| trait_key | param_key | label | value |
|---|---|---|---|
| `glass_cannon` | `kill_multiplier` | Kill weight multiplier | 2.0 |
| `glass_cannon` | `death_multiplier` | Death weight multiplier | 2.5 |
| `first_blood` | `bonus_pts` | Flat bonus points | 20.0 |
| `feat_or_famine` | `success_multiplier` | Multiplier on deathless match | 1.5 |
| `feast_or_famine` | `fail_multiplier` | Multiplier on match with deaths | 0.6 |
| `win_or_nothing` | `win_multiplier` | Multiplier on winning match | 2.0 |
| `win_or_nothing` | `loss_multiplier` | Multiplier on losing match | 0.0 |
| `momentum` | `step` | Multiplier increment per streak match | 0.10 |
| `momentum` | `max_multiplier` | Multiplier cap | 2.0 |

### New table: `card_traits`

```python
class CardTrait(Base):
    __tablename__ = "card_traits"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    card_id   = Column(Integer, ForeignKey("cards.id"))
    trait_key = Column(String, ForeignKey("traits.key"))
```

One row per trait per card. At most 3 rows per card.

---

## Scoring Changes

### `scoring.py`

Current function: `fantasy_score(p, weights)` — one-line weighted sum.

Proposed extension — trait params passed in alongside weights so the function remains pure (no DB access):

```python
def apply_weight_traits(traits, trait_params, weights, stats):
    """Return a modified weights dict after applying all weight-modifier traits.
    trait_params: {trait_key: {param_key: value}}
    """
    w = dict(weights)
    for trait in traits:
        params = trait_params.get(trait, {})
        w = _trait_weight_modifiers[trait](w, stats, params)  # dispatch table
    return w

def apply_bonus_traits(traits, trait_params, stats, base_score):
    """Return flat bonus points from conditional traits."""
    total = 0
    for trait in traits:
        if trait in _trait_bonus:
            params = trait_params.get(trait, {})
            total += _trait_bonus[trait](stats, base_score, params)
    return total

def fantasy_score(p, weights, traits=None, trait_params=None):
    if not traits:
        return sum(weights.get(k, 0) * p.get(k, 0) for k in weights)
    tp = trait_params or {}
    effective_weights = apply_weight_traits(traits, tp, weights, p)
    base = sum(effective_weights.get(k, 0) * p.get(k, 0) for k in effective_weights)
    bonus = apply_bonus_traits(traits, tp, p, base)
    return base + bonus
```

Backwards compatible: `traits=None` preserves existing behaviour exactly.

`trait_params` has the shape `{trait_key: {param_key: value}}` — pre-loaded at the call site (ingest or recalculate), not fetched inside the scoring function. Each dispatch function receives its own params dict so it can read `params["kill_multiplier"]` etc.

### Loading trait params at call sites

At ingest time and on `POST /recalculate`, load all trait params once before the loop:

```python
raw = db.query(TraitParam).all()
trait_params = {}
for row in raw:
    trait_params.setdefault(row.trait_key, {})[row.param_key] = row.value
```

Pass `trait_params` into `fantasy_score` alongside the base `weights`.

### Recalculation

`POST /recalculate` needs to:
1. Load base `weights` (existing)
2. Load `trait_params` (new)
3. Load card → trait mapping (`card_traits` join)
4. For each `PlayerMatchStats`, find the owning card's traits, call `fantasy_score(stats, weights, traits, trait_params)`

Because trait params are loaded once and passed through, changing a param value and running recalculate immediately reflects the new numbers — identical to how adjusting a base weight and recalculating works today.

---

## Admin API — Trait Parameters

Mirrors the existing `GET /weights` + `PUT /weights/{key}` pattern exactly.

### `GET /trait-params`
Returns all trait params grouped by trait, for the admin panel.
```json
[
  {
    "trait_key": "glass_cannon",
    "trait_name": "Glass Cannon",
    "tier": 3,
    "params": [
      { "param_key": "kill_multiplier", "label": "Kill weight multiplier", "value": 2.0 },
      { "param_key": "death_multiplier", "label": "Death weight multiplier", "value": 2.5 }
    ]
  },
  ...
]
```

### `PUT /trait-params/{trait_key}/{param_key}` (admin)
Body: `{ "value": 1.8 }`
Returns: `{ "trait_key": "glass_cannon", "param_key": "kill_multiplier", "value": 1.8 }`

After updating a param, the admin runs `POST /recalculate` to re-score all historical matches with the new values — the same workflow as adjusting base scoring weights.

---

## Frontend Changes

### Admin tab — Trait Parameters panel

New panel in the Admin tab, below the existing Scoring Weights panel. Groups params under their trait name with tier and description as context:

```
┌─ Trait Parameters ──────────────────────────────────────┐
│  [Refresh]                                              │
│                                                         │
│  Glass Cannon  (Epic+, Tier 3)                          │
│  Kill weight multiplier    [ 2.0 ] [Save]               │
│  Death weight multiplier   [ 2.5 ] [Save]               │
│                                                         │
│  First Blood  (Rare+, Tier 2)                           │
│  Flat bonus points         [20.0 ] [Save]               │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

The grouping by trait with name/tier shown makes it clear what each number does — unlike the base weights table which is a flat list.

### Card reveal modal

Currently shows: rarity, avatar, player name, team name, destination.

Add: trait badges below the player name — one pill per trait with name and a short tooltip.

### My Team — roster cards

Each row should show trait badges alongside rarity. Clicking a trait shows its full description.

### Players tab

Player profile popup: no traits shown here (traits are per-card, not per-player). The distinction between player and card is preserved.

---

## Open Questions (for collaboration)

1. **Retroactive scoring**: Should traits apply to all past matches on the card, or only from the draw date forward? Retroactive is simpler to implement but feels odd narratively.

2. **Trait re-rolls**: Should there be an admin-grantable "re-roll" mechanic for traits on a card? Could be a future draw-sink.

3. **Trait visibility before draw**: Should the card back hint at possible trait tier (e.g. Epic cards show "2 traits" without revealing which)? Currently the reveal modal is the first reveal.

4. **Hero Main league scope**: Use hero frequency within this league only, or all-time OpenDota history? League-only is more contextual but requires more data to be meaningful early in the season.

5. **Win or Nothing edge case**: What happens if the match data doesn't have a winner recorded (abandoned/remade match)? Currently some matches have `radiant_win = NULL`.

6. **Trait balance**: The current scoring weights are small decimals (e.g. kills = 3.0, tower_damage = 0.002). Trade-off multipliers need playtesting against real match data to ensure Glass Cannon cards aren't always dominant.

7. **New data backfill**: Should `hero_id` / `firstblood_claimed` / `multi_kills` be fetched in a background re-ingest pass, or only populated for new matches going forward?

---

## Implementation Order

**Phase 1** — Foundation (no new ingest data needed)
- Schema: `traits`, `trait_params`, `card_traits` tables
- `seed_traits()` seeds trait definitions and default `trait_params` rows; existing param values left untouched on re-seed
- `scoring.py` extended with trait dispatch, `trait_params` dict passed through
- Assignment logic in `seed.py` (random by rarity, compatibility checks)
- `GET /trait-params` and `PUT /trait-params/{trait_key}/{param_key}` endpoints
- Admin UI: Trait Parameters panel
- `POST /recalculate` updated to load trait params and card→trait mapping
- Card reveal modal shows traits

**Phase 2** — Match event traits (new ingest fields)
- Add `hero_id`, `firstblood_claimed`, `multi_kills` to `PlayerMatchStats`
- Migration + optional backfill endpoint
- Tier 2 trait implementations added to dispatch tables
- `hero_main` requires hero frequency helper query

**Phase 3** — Pinnacle traits
- `win_or_nothing` — derivable from current data, implement first
- `underdog` — team win-rate query
- `momentum` / `on_tilt` — `CardTraitState` table for cross-match multiplier state

---

## Critical Files

- `backend/models.py` — add `Trait`, `TraitParam`, `CardTrait`, (later) `CardTraitState`; add fields to `PlayerMatchStats`
- `backend/scoring.py` — extend `fantasy_score(p, weights, traits, trait_params)`, add trait dispatch tables
- `backend/seed.py` — `seed_traits()` seeds both `traits` and `trait_params`; trait assignment in `seed_cards()`
- `backend/ingest.py` — store new fields from OpenDota player data; load `trait_params` before scoring loop
- `backend/main.py` — `GET /trait-params`, `PUT /trait-params/{trait_key}/{param_key}`; expose traits on card endpoints; update `/recalculate`
- `frontend/index.html` — Trait Parameters panel in Admin tab; trait badges in reveal modal and roster rows
- `frontend/app.js` — `loadTraitParams()`, `saveTraitParam()`, render traits, tooltip on hover
- `frontend/style.css` — trait badge styles (distinct from rarity badges)
