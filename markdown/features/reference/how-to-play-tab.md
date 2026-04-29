# How to Play Tab

A static informational tab visible to all users that explains the fantasy league rules, the scoring formula, card modifiers, and the Twitch extension MVP flow. Scoring weight values are loaded live from `GET /weights` so the displayed numbers stay accurate when an admin adjusts weights.

---

## Sections

### Getting Started
Explains the core user loop:
- Draw a card (costs 1 token) → drawn from the shared seasonal deck
- Activate up to 5 cards as your roster; the rest go to the bench
- Roster locks each week — locked cards earn fantasy points from matches played that week
- How to earn more tokens: +1 at each weekly lock, Twitch extension viewer drops, admin promo codes

### Twitch & MVP
Explains the broadcaster and viewer flows:
- Broadcasters install the Kanaliiga Twitch extension — no URL configuration required
- Quick Actions (Live Config view in Twitch Stream Manager) → Select match MVP → series → match → player → confirm
- Token drop fires automatically on confirmation to eligible linked viewers (once per match)
- The confirmed MVP receives a configurable fantasy point bonus for that specific match
- Viewers link their Fantasy account: Profile tab → Generate Twitch Code → enter code in the Twitch panel

### Scoring & Modifiers
Live weight tables loaded from `GET /weights`:
- **Stat weights table** — seven stats (Kills, Assists, Deaths, GPM, Observer Wards, Sentry Wards, Tower Damage) with current point-per-unit values
- **Rarity bonus table** — flat % multiplier applied to the card's total score, by rarity (Common through Legendary)
- **Modifier table** — how many per-stat modifiers each rarity receives at draw time, and the bonus % each applies
- **MVP bonus** — the current `mvp_bonus_pct` value shown inline

---

## Implementation

The tab is entirely frontend. No new backend endpoints are introduced.

| Surface | Change |
|---|---|
| `frontend/index.html` | New tab button `#tab-btn-howtoplay`; new content div `#tab-howtoplay` |
| `frontend/app.js` | `loadHowToPlay()` fetches `GET /weights` and populates three `<tbody>` elements and one inline span |

`switchTab('howtoplay')` calls `loadHowToPlay()`. The tab button has no auth-state visibility logic — it is always shown.

### Graceful fallback
If `GET /weights` fails, the stat/rarity/modifier tables are empty but all surrounding explanatory text remains visible. No error banner is shown for this failure.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
