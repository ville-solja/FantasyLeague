# Plan: How to Play Tab

## Context

New users and casual participants have no in-app reference for how the fantasy league works. The scoring formula, card modifiers, rarity bonuses, and the Twitch MVP flow are opaque without reading external documentation. A static "How to Play" tab removes that friction by placing all essential rules one click away from any screen. The tab is purely frontend — no backend endpoints are needed, and the content is baked into the HTML.

The tab covers three audiences: general users (roster + cards), streamers (Twitch extension + MVP selection), and curious users who want to understand the exact scoring formula. The scoring section reads current weight values live from `GET /weights` so it stays accurate when an admin adjusts weights.

---

## User Stories

### How to Play Tab
**User story**
As a new user, I want a tab that explains how the fantasy app works so that I can get started without reading external documentation.

**Acceptance criteria**
- A "How to Play" tab is visible to all users (logged in and logged out) in the main navigation
- Tab contains three clearly separated sections: Getting Started, Twitch & MVP, and Scoring & Modifiers
- Getting Started section explains: draw a card using a token, activate up to 5 cards into the roster, roster locks weekly, points accumulate from locked rosters
- Getting Started section explains how to obtain more tokens: week lock bonus, Twitch extension drops, promo codes
- Twitch & MVP section explains the broadcaster MVP selection flow and that the selected MVP receives a point bonus for that match
- Scoring & Modifiers section lists the scoring stats and reads live weight values from the server to show current multipliers
- Scoring section explains card rarity bonuses and card modifier bonuses using live weight values
- Tab renders correctly with no active session (weights endpoint is public)

### Streamer MVP Instructions
**User story**
As a Kanaliiga streamer, I want the How to Play tab to explain the Twitch extension MVP flow so that I can set it up and use it without reading separate documentation.

**Acceptance criteria**
- The Twitch & MVP section explains: install the extension, use Quick Actions to select a series → match → player
- Explains that token drops fire automatically on MVP confirmation (once per match)
- Explains that the MVP selection also grants a fantasy score bonus to that player's match
- The section is visible to all users (not restricted to admins or streamers)

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `frontend/index.html` | Add tab button and `#tab-howtoplay` content div |
| `frontend/app.js` | Add `loadHowToPlay()` function; call from `switchTab('howtoplay')` handler; fetch weights for live scoring display |

No backend changes. No new models or endpoints. No migration needed.

---

### Step 1 — Add tab button in `frontend/index.html`

Add the tab button to the nav bar alongside the other tabs. The button should be visible to all users (no hide/show logic):

```html
<button class="tab" id="tab-btn-howtoplay" onclick="switchTab('howtoplay')">How to Play</button>
```

Place it after the Schedule tab and before the Admin tab.

---

### Step 2 — Add tab content div in `frontend/index.html`

Add a new `<div id="tab-howtoplay" class="tab-content">` after the `#tab-schedule` div. The div contains three sections with static HTML:

**Section 1 — Getting Started**
- How cards work (draw, rarity, deck)
- Activating a roster (up to 5 cards, bench for the rest)
- Weekly lock: roster freezes each week, locked cards earn points from matches that week
- How to get tokens: +1 at each week lock, Twitch extension drops, promo codes from admins

**Section 2 — Twitch & MVP**
- Broadcasters install the Kanaliiga Twitch extension; no URL configuration needed
- Quick Actions panel → Select match MVP → series → match → player
- Token drop fires automatically on confirmation (once per match, up to N random linked viewers)
- MVP player receives a bonus on their fantasy points for that specific match
- Viewers link their Fantasy account via Profile tab → "Generate Twitch Code" → enter code in panel

**Section 3 — Scoring & Modifiers**
- Scoring formula: each stat multiplied by its weight, summed
- Stat weights loaded live from `GET /weights` and rendered as a table (stat name, current value)
- Rarity bonus: a flat multiplier on total score, shown from live weights (`rarity_common` through `rarity_legendary`)
- Card modifier bonus: at draw time, Rare/Epic/Legendary cards receive modifiers that boost individual stats
- MVP bonus: if a broadcaster names a player the match MVP, their score for that match receives an additional multiplier (`mvp_bonus_pct` weight)

---

### Step 3 — Add `loadHowToPlay()` in `frontend/app.js`

```js
async function loadHowToPlay() {
  const res = await fetch('/weights');
  if (!res.ok) return;
  const weights = await res.json();
  const byKey = Object.fromEntries(weights.map(w => [w.key, w]));

  // Populate scoring stats table
  const statsKeys = ['kills','assists','deaths','gold_per_min','obs_placed','sen_placed','tower_damage'];
  const statsLabels = {
    kills: 'Kills', assists: 'Assists', deaths: 'Deaths',
    gold_per_min: 'Gold per minute', obs_placed: 'Observer wards',
    sen_placed: 'Sentry wards', tower_damage: 'Tower damage',
  };
  const tbody = document.getElementById('howtoplay-stats-tbody');
  if (tbody) {
    tbody.innerHTML = statsKeys.map(k => {
      const w = byKey[k];
      return `<tr><td>${statsLabels[k]}</td><td>${w ? w.value : '—'}</td></tr>`;
    }).join('');
  }

  // Populate rarity bonus table
  const rarityKeys = ['rarity_common','rarity_rare','rarity_epic','rarity_legendary'];
  const rarityTbody = document.getElementById('howtoplay-rarity-tbody');
  if (rarityTbody) {
    rarityTbody.innerHTML = rarityKeys.map(k => {
      const w = byKey[k];
      const label = k.replace('rarity_', '').replace(/^\w/, c => c.toUpperCase());
      return `<tr><td>${label}</td><td>+${w ? w.value : 0}%</td></tr>`;
    }).join('');
  }

  // Populate modifier count table
  const modKeys = ['modifier_count_common','modifier_count_rare','modifier_count_epic','modifier_count_legendary'];
  const modTbody = document.getElementById('howtoplay-mods-tbody');
  if (modTbody) {
    const bonusPct = byKey['modifier_bonus_pct']?.value ?? 10;
    modTbody.innerHTML = modKeys.map(k => {
      const w = byKey[k];
      const label = k.replace('modifier_count_', '').replace(/^\w/, c => c.toUpperCase());
      const count = w ? w.value : 0;
      return `<tr><td>${label}</td><td>${count} modifier${count !== 1 ? 's' : ''} (+${bonusPct}% each)</td></tr>`;
    }).join('');
  }

  // MVP bonus
  const mvpEl = document.getElementById('howtoplay-mvp-bonus');
  if (mvpEl) {
    const mvpPct = byKey['mvp_bonus_pct']?.value ?? 10;
    mvpEl.textContent = `+${mvpPct}%`;
  }
}
```

Wire into `switchTab`:
```js
if (name === "howtoplay") { loadHowToPlay(); }
```

The tab button needs no auth-state logic — it is always visible regardless of login state.

---

### Step 4 — Weights section graceful fallback

If `GET /weights` fails (network error, server down), the tables remain empty but the surrounding explanatory text is still useful. The fallback is acceptable — do not show an error message for a weights fetch failure in this context.

---

## Verification

- Navigate to How to Play tab while logged out — tab is visible and renders all three sections.
- Navigate while logged in as a regular user — identical result.
- Scoring table shows correct live values (verify one weight matches `GET /weights` response).
- Rarity bonus table shows 0% for Common, and positive values for Rare/Epic/Legendary.
- Modifier table shows 0 modifiers for Common, increasing counts for higher rarities with the bonus % shown.
- MVP bonus inline value matches `mvp_bonus_pct` weight.
- Change a weight value as admin, reload the tab — updated value is reflected without a page reload.
- Tab button persists in nav when switching between tabs (not hidden on auth state change).
- On narrow screen (< 768 px) sections stack vertically and are readable without horizontal scroll.
