# Plan: Draw Panel Redesign

## Context

The "Deck" panel on the My Team tab was designed when cards were drawn from a static pre-seeded pool, where the count of remaining cards was the meaningful number. Since the transition to dynamic card generation at draw time, the count is no longer relevant to the user — what matters is the probability of landing each rarity. This plan renames the section to "Draw" and replaces the per-rarity count numbers with normalised drop percentages sourced from the `draw_rate_*` weights in the database. Resolves GitHub issue #73.

---

## User Stories

### View Drop Percentages in the Draw Panel
**User story**
As a player, I want to see the drop chance for each rarity in the Draw panel so that I know what I am likely to get when I spend a token.

**Acceptance criteria**
- The panel heading reads "Draw" instead of "Deck"
- Each rarity card template displays its drop percentage (e.g. "60%") instead of a card count
- Percentages are normalised from the live `draw_rate_*` weights so they always sum to 100%
- Percentages update if an admin changes the draw rate weights (on next page load)
- The "X draws available" status line and the draw/booster buttons are unchanged

### Expose Draw Rates via the Config Endpoint
**User story**
As a frontend client, I want the `/config` endpoint to include the current draw rate percentages so that I do not have to parse the full weights list client-side.

**Acceptance criteria**
- `GET /config` returns a `draw_rates` object with keys `common`, `rare`, `epic`, `legendary`
- Each value is a float representing the normalised percentage (rounds to 1 decimal place)
- If all four `draw_rate_*` weights are missing from the database the endpoint falls back to the seeded defaults (60/25/10/5)

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/main.py` | Add `draw_rates` to `GET /config` response |
| `frontend/index.html` | Rename "Deck" → "Draw"; replace `id="deck-{r}"` count divs with percentage divs |
| `frontend/app-cards.js` | Update `loadDeck()` to read `draw_rates` from `/config` and render percentages; keep status line from `/deck` |

### Step 1 — Add `draw_rates` to `GET /config`

In `backend/main.py`, update `get_config`:

```python
@app.get("/config")
def get_config(db=Depends(get_db)):
    booster_row = db.query(Weight).filter_by(key="team_booster_cost").first()
    booster_cost = int(booster_row.value) if booster_row else 3

    rate_keys = ["draw_rate_common", "draw_rate_rare", "draw_rate_epic", "draw_rate_legendary"]
    defaults  = {"draw_rate_common": 60.0, "draw_rate_rare": 25.0,
                 "draw_rate_epic": 10.0, "draw_rate_legendary": 5.0}
    raw = {}
    for key in rate_keys:
        row = db.query(Weight).filter_by(key=key).first()
        raw[key] = float(row.value) if row else defaults[key]
    total = sum(raw.values()) or 1.0
    draw_rates = {
        "common":    round(raw["draw_rate_common"]    / total * 100, 1),
        "rare":      round(raw["draw_rate_rare"]      / total * 100, 1),
        "epic":      round(raw["draw_rate_epic"]      / total * 100, 1),
        "legendary": round(raw["draw_rate_legendary"] / total * 100, 1),
    }

    return {
        "token_name":      TOKEN_NAME,
        "initial_tokens":  INITIAL_TOKENS,
        "app_version":     _APP_VERSION,
        "app_release":     _APP_RELEASE,
        "team_booster_cost": booster_cost,
        "draw_rates":      draw_rates,
    }
```

### Step 2 — Update the HTML panel

In `frontend/index.html`, change the panel heading and replace the `count` divs:

```html
<div class="panel">
  <h2>Draw</h2>
  <div class="rarity-grid">
    <div class="rarity-card-box">
      <img src="/assets/Card_Template_Common.png" alt="Common" class="rarity-card-thumb" />
      <div class="count" id="deck-common">—</div>
    </div>
    <div class="rarity-card-box">
      <img src="/assets/Card_Template_Rare.png" alt="Rare" class="rarity-card-thumb" />
      <div class="count" id="deck-rare">—</div>
    </div>
    <div class="rarity-card-box">
      <img src="/assets/Card_Template_Epic.png" alt="Epic" class="rarity-card-thumb" />
      <div class="count" id="deck-epic">—</div>
    </div>
    <div class="rarity-card-box">
      <img src="/assets/Card_Template_Legendary.png" alt="Legendary" class="rarity-card-thumb" />
      <div class="count" id="deck-legendary">—</div>
    </div>
  </div>
  ...
</div>
```

The `id` values (`deck-common` etc.) are kept so `app-cards.js` can target them without refactoring references throughout the file. Only the content written into them changes.

### Step 3 — Update `loadDeck()` in `app-cards.js`

The current `loadDeck()` fetches `GET /deck` and writes counts into the boxes. Change it to fetch `GET /config` for the drop rates and write percentages, while still fetching `GET /deck` for the status line total:

```javascript
async function loadDeck() {
  try {
    const [deckRes, cfgRes] = await Promise.all([
      fetch(`${API}/deck`),
      fetch(`${API}/config`),
    ]);
    const deck = await deckRes.json();
    const cfg  = await cfgRes.json();

    const rates = cfg.draw_rates || { common: 60, rare: 25, epic: 10, legendary: 5 };
    for (const r of DRAW_RARITY_KEYS) {
      document.getElementById(`deck-${r}`).textContent = `${rates[r]}%`;
    }

    const total = Object.values(deck).reduce((s, n) => s + n, 0);
    setStatus("deckStatus", total > 0 ? `${total} draws available` : "No draws available");
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}
```

---

## Verification

- Panel heading shows "Draw" not "Deck"
- Each rarity box shows a percentage (e.g. "60%", "25%", "10%", "5%") not a count
- The four percentages sum to 100 (given the default weights)
- The status line still shows the correct available-draw count
- Draw and Booster buttons still work unchanged
- Changing draw rate weights in the admin Scoring Weights panel and refreshing the page updates the displayed percentages
- `GET /config` response includes `draw_rates` object with `common`, `rare`, `epic`, `legendary` keys
