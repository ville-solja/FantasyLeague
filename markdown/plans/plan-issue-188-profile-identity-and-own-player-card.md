# Plan: Profile Identity Panel and Own Player Card

## Context
Issue #188 has two parts.

**1. Profile clarity.** The Profile tab shows a **Steam** panel and a **Dota 2 Player** panel that say the same thing.
- Since #150, linking Steam sets and verifies the player id (`steam_openid` sets `user.player_id = steam32(steam64)`).
- For a Steam-linked account, the Dota 2 Player panel's OpenDota id field is disabled and repeats "Verified with Steam".
- The manual field only ever produced a *self-reported* id (#169), which other players see marked as unverified.
- The issue asks to remove manual OpenDota linking and restructure the page. A comment on the issue asks for a canvas draft of a cleaner structure.

**2. A free card of yourself.** A player who links a Steam account that matches a player in this season's pool gets that player's card, once, with a popup saying why.

**Duplicate rules today (`card_draw.py`):**
- A standard draw never gives a player the user already owns, at any rarity, until they own every player. A team draw does the same within the team.
- At most one active card per player per user (`ux_cards_owner_player_active`, #185).

The grant fits these rules if it is skipped when the user already owns a card of that player. Draws then treat the granted card as owned, so it can't lead to a duplicate later.

Decisions and assumptions:
- **Manual linking goes away where Steam is available.** With `LOGIN_METHOD` `both` or `steam_signup`, `PUT /profile/player-id` is refused and the field is gone. With `LOGIN_METHOD=password` (no Steam), the field stays as the only way to link, still marked self-reported.
- **Existing self-reported ids stay,** shown read-only with "Self-reported, link Steam to verify". Linking Steam replaces them, as today. Admin-granted tags keep working for those players.
- **The granted card is common** and gets the usual modifiers. It goes to the roster if there is room and no active card of that player, otherwise to the bench, like a draw.
- **"Once" means once per Kana Cards account and once per league player.** A grant record keyed by both stops unlinking and relinking, or linking the same Steam account to another account, from granting it again.
- **Existing Steam-linked players get it too:** the grant is checked on link, on Steam sign-up, and when the profile loads (`GET /me`). That also covers a player added to the pool after they linked.
- **No new feature doc:** the existing docs are updated (`steam-login.md`, `player-linking-and-tag-visibility.md`, `ui_description/profile.md`).

Resolves GitHub issue #188.

## User Stories

### One Clear Identity Panel on Profile
**User story**
As a player, I want my Steam link and my league player identity in one place, so that I understand what is linked and why without reading two panels that say the same thing.

**Acceptance criteria**
- Profile shows four panels: **Account** (username, password or Steam-only sign-in, sessions), **Player identity** (replaces the Steam and Dota 2 Player panels, and holds Your Tags), **Twitch** (unchanged) and **Past seasons** (unchanged, when present)
- Player identity, not linked: one sentence on what linking does (verifies your league player, shows your tags on your cards and the leaderboard, and gives you your own player card once if you play in this season), plus **Link Steam**
- Player identity, linked:
  - **Steam linked** and the matched league player's avatar, name and team, or "No league player matches this Steam account" when none exists;
  - the account's tags as chips, or "No tags";
  - **Unlink Steam** for accounts with a password, as today.
- No OpenDota account id field when `LOGIN_METHOD` is `both` or `steam_signup`; `PUT /profile/player-id` answers 410 "Link Steam to verify your player id"
- With `LOGIN_METHOD=password`, the panel keeps the id field, labelled "Self-reported"
- An existing self-reported id is shown read-only with "Self-reported, link Steam to verify"; tags still show
- The Steam id itself is never shown, as today

### Own Player Card When Steam Matches a League Player
**User story**
As a player in this season's league, I want to receive my own player card when I link my Steam account, so that the game recognises me as one of the players.

**Acceptance criteria**
- When an account's verified player id (from Steam) is an active player in the pool (`Player.is_active`), the account gets one common card of that player with the usual modifiers. It goes to the roster if there is room and no active card of that player, otherwise to the bench
- The grant runs after Link Steam, after Steam sign-up, and on `GET /me` for accounts that qualify but have no grant yet (existing linked players, or a player added to the pool later)
- A new table `own_player_card_grants` holds `user_id` (unique), `player_id` (unique), `card_id` (nullable), `outcome` (`granted` or `already_owned`) and `granted_at`. It is written with `INSERT … ON CONFLICT DO NOTHING`, and a card is created only when the insert added the row. Unlinking and relinking, or linking the same Steam account to another account, grants nothing more
- If the account already owns any card of that player, no card is created and the grant is recorded as `already_owned`
- An audit entry `own_player_card_granted` names the user, the player and the card id
- Self-reported ids never qualify; neither do demo accounts or soft (Twitch-only) accounts

### Popup Explains the Gift
**User story**
As a player who just received my own card, I want a popup that shows it and says why, so that I know it isn't a random draw.

**Acceptance criteria**
- After a grant, the next page load shows a popup with the card in the existing card viewer and the text "Your own player card. You linked Steam, and you play in this season's league, so this card of {player name} is yours." with **Nice**
- For `already_owned`: "You already have a card of {player name}, so no new card was added." with **OK**
- The popup shows once: `GET /me` returns `own_card_grant: {player_name, card_id | null, outcome}` until the player dismisses it (`POST /profile/own-card-grant/seen`), then null
- Text is set with `textContent` or `_escHtml`

### Draws Stay Duplicate-Free
**User story**
As a player, I want the granted card to count like any other card I own, so that draws don't give me the same player again.

**Acceptance criteria**
- After a grant, a standard draw and a team draw treat the granted player as owned, under the existing `_pick_player` and `_pick_player_from_team` rules
- No grant is made when the account already owns that player, so the grant itself never creates a second card of a player
- The one-active-card-per-player rule holds: if an active card of that player exists, the granted card goes to the bench

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `OwnPlayerCardGrant` (`own_player_card_grants`), created by `create_all`; seen flag (`seen_at`) |
| `backend/own_card.py` (new) | `grant_own_player_card(db, user) -> grant or None`: eligibility, conflict-safe insert, card creation with the draw's helpers (`_activate_new_card`, `_assign_modifiers`, `card_points.refresh_card_points`) |
| `backend/steam_openid.py` | Call the grant after link and after Steam sign-up |
| `backend/routers/profile.py` (`GET /me`) | Lazy grant for qualifying accounts; `own_card_grant` until seen |
| `backend/routers/profile.py` | `PUT /profile/player-id` → 410 unless `LOGIN_METHOD=password`; `POST /profile/own-card-grant/seen` |
| `frontend/index.html`, `frontend/app-profile.js`, `frontend/style.css` | Player identity panel (Steam and Dota 2 Player merged, tags moved in); the id field only in password mode; the popup using the card viewer |
| `markdown/ui_description/profile.md`, `markdown/features/reference/steam-login.md`, `markdown/features/reference/player-linking-and-tag-visibility.md`, `markdown/features/core/cards.md` | Existing docs |
| `backend/tests/test_issue_188_profile_identity_and_own_player_card.py` | Tests |

No column on an existing table, so no migration. The grant table is new.

### Step 1 — Grant
`grant_own_player_card(db, user)` returns nothing unless all of these hold:
- the user has a `steam_id`, a `player_id`, and is not demo or soft;
- the player exists and is active;
- there is no grant row for the user or the player.

Otherwise it inserts the row with `ON CONFLICT DO NOTHING` and `outcome = "already_owned"` if the user owns any card of the player, else `"granted"`. It creates the card only on `granted` and only when the insert added the row: common rarity, `_activate_new_card`, modifiers, points. Then it sets `card_id` and writes the audit entry. The caller commits.

### Step 2 — Hooks
- **Steam:** the link and sign-up paths in `steam_openid.py` call the grant after `_supersede_player_id_claims`.
- **`GET /me`:** calls the grant when the cheap check passes (Steam-linked, `player_id` set, no grant row), then returns `own_card_grant` while `seen_at` is null.
- **Dismissal:** `POST /profile/own-card-grant/seen`, logged in, with the per-user rate limit (#184 route coverage).

### Step 3 — Profile
- **Panels:** rebuild the Profile layout into the four panels.
- **Player identity:** one state machine (not linked / linked with player / linked without player / self-reported legacy / password mode), with tags inside.
- **Removal:** remove the Steam and Dota 2 Player panels.
- **Popup:** reuse the card viewer (`#revealModal`) for the card.
- **Draft:** the canvas draft from the issue comment is the reference for the layout: https://claude.ai/artifact/13ZWFUDZwAhoSaJ6MftCWM. It has five artboards: the full Profile with a linked league player, the not-linked, no-match and legacy self-reported states, and the card popup.

### Step 4 — Docs and tests
**Docs:** update the four docs listed above.

**Tests:**
- **Eligibility:** granted on link for a pool player; nothing for a self-reported id, an inactive player, a demo account or a soft account.
- **No duplicates:** `already_owned` when the account owns the player; nothing more on unlink and relink, or the same Steam account on a second account.
- **Concurrency:** two concurrent grants create one card.
- **Lazy grant:** `GET /me` grants once and returns `own_card_grant` until seen.
- **Card placement:** roster or bench placement follows `_activate_new_card`.
- **Draw rules:** the next standard draw doesn't pick the granted player while unowned players remain.
- **Player id route:** `PUT /profile/player-id` gives 410 in `both` and `steam_signup` modes and still works in `password` mode.
- **Frontend (static):**
  - no OpenDota field outside password mode;
  - the merged panel;
  - the popup texts set through `textContent`.

## Verification
- **Steam link on test:** with a Steam account that matches a pool player, Link Steam. Profile shows the Player identity panel with the matched player, and the popup shows the card once. My Team has the card. Relink: no second card.
- **Already owned:** an account that already owns its player gets the "already have" popup and no card.
- **Existing linked players:** after the deploy, a Steam-linked league player gets the card and popup on their next visit.
- **Password mode:** with `LOGIN_METHOD=password`, the id field is still there and works.
- **Tests:** `cd backend && python -m pytest tests/test_issue_188_profile_identity_and_own_player_card.py -q`, then `python -m pytest tests/ -n auto -q`.
