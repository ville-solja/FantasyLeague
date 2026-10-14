# Profile tab

Visible only to logged-in users.

Four panels (issue #188): **Player identity** across the full width at the top, then **Account** and **Twitch** side by side, then **Past Seasons** (only when present). The layout follows the canvas draft linked in `markdown/plans/plan-issue-188-profile-identity-and-own-player-card.md`.

## Account panel

- **Username** — editable field pre-filled with the current username. Save button updates it server-side; must remain unique, ignoring letter case. A muted hint below the field lists the allowed characters (letters, digits, underscore, hyphen) and says names that look like staff or the league (admin, Kanaliiga, support…) are not available; other characters get a 422 error in the status line, and a reserved name gets "This name is reserved". Real admins see an **ADMIN** badge next to the "Username" label (`#profileAdminBadge`; outlined accent chip in display type, see Leaderboards). One rename per 7 days by default (issue #169): while the cooldown runs, a second muted line (`#profileRenameHint`) reads "You can rename again on <date>.", and saving a different name shows the server's "You can change your username again on <date> UTC" error. Saving the same name or changing only its letter case is always allowed.
- **Password** — hidden for an account without a password (created through Steam, issue #150), which shows "This account signs in with Steam and has no password." instead. Otherwise two fields (current password, new password). Requires the correct current password before accepting a change. A successful change keeps this session and logs out every other device. The fields and the **Change password** button are a form (`#changePasswordForm`): Enter in either field submits it, and password managers fill the current password and offer to update the saved login (a hidden, read-only username field holds the logged-in username; see `features/reference/password-manager-autofill.md`).
- **Log out everywhere** — button under the password form, with a muted note explaining it. After a confirmation prompt it calls `POST /logout-everywhere`, which ends every session of the account including this one, and the page returns to the logged-out state. Errors appear in the status line below the button.
- **Signed-in devices** — a small table under **Log out everywhere**, loaded from `GET /sessions` when the tab opens and again after a password change. Columns: Signed in, Last active (the current device is marked "(this device)"), and a **Sign out** button per row that calls `DELETE /sessions/{id}`. Signing out another device reloads the list and shows "Session signed out"; signing out the current device returns the page to the logged-out state. "No active sessions" when the list is empty. Errors appear in the status line below the table. Rows are built with `textContent`.

## Revoked sessions

If a session was ended elsewhere (password change on another device, log out everywhere, a **Sign out** on another device, admin force logout or admin toggle, password reset) or it expired (14 days without a visit or 30 days after login for players; 2 hours idle or 12 hours for admins), the next page load gets 401 from `GET /me`. The header then shows the logged-out state instead of the stale username, and the stored username and admin flag are cleared.

## Player identity panel

Issue #188 (replaces the Steam, Dota 2 Player and Your Tags panels). Spans the full width (`.profile-identity`, `grid-column: 1 / -1`); on narrow screens the tags column moves under the main column. Driven by `GET /config` `login_method`, `GET /me` `steam_linked` / `has_password` / `is_demo` (`steamUiState` in `app-auth.js`) and `GET /profile/{id}`; `playerIdentityState()` in `app-profile.js` picks one state. The Steam id is never shown, only linked yes/no.

| State | When | Main column |
|---|---|---|
| Not linked | Steam modes, no Steam link, no player id | "Link your Steam account to verify which league player you are: your tags then show on your cards and next to your name on the leaderboard, and if you play in this season's league you get your own player card, once." **Link Steam** (never for demo accounts) and the muted note "You sign in on steamcommunity.com. Kana Cards never asks for your Steam password." |
| Linked | Steam modes, Steam linked, the player is in the database | Heading badge "Steam linked" (display font, accent colour, check icon). The matched player: avatar, name with the label "Verified with Steam", and team (`player_team_name`). **Unlink Steam** for accounts that also have a password. |
| Linked, no match | Steam modes, Steam linked, no player with that id | "Steam linked" badge, a box "No league player matches this Steam account" with "That's normal if you don't play in the league. If you do, your player appears here once an admin adds you to this season's players." **Unlink Steam** as above. |
| Self-reported (legacy) | Steam modes, no Steam link, a typed-in id from before | The player's name (if known) labelled "Self-reported" without avatar, read-only, with "Self-reported, link Steam to verify" and **Link Steam**. No id field. |
| Password mode | `LOGIN_METHOD=password` | The label "OpenDota account id" with "Self-reported", the id field and **Save** (`PUT /profile/player-id`), a note that tags then appear on cards and the leaderboard. A saved id in the database shows the player's name labelled "Self-reported" (no avatar). No Steam controls. |

- **Reminder** (`steam_signup` mode, account with a password and no Steam link): a box with an accent border at the top of the main column: "Link Steam now. Password sign-in will end in a later update."
- **Link Steam** navigates to `GET /auth/steam/start?purpose=link`. Without a recent identity check the server sends the browser back with `steam=reauth_required`, the **Confirm your password** prompt opens, and once confirmed the browser goes to Steam; if cancelled: "Confirm your password to link Steam."
- **Unlink Steam** asks for confirmation, then calls `POST /profile/steam/unlink` (password prompt when needed), shows "Steam unlinked." and redraws the panel. The player id stays, so the panel then shows it as self-reported. Steam-only accounts have no Unlink button.
- After Steam, the page returns to Profile (`/#profile?steam=<key>`, stripped from the address bar) with a status message by key (`_STEAM_RETURN_MESSAGES` in `app-auth.js`): `linked` "Steam linked. Your league player is now verified."; `in_use` "This Steam account is linked to another Kana Cards account"; `unlink_first` "Unlink your current Steam account first"; `not_allowed` "Demo accounts can't link Steam."; `login_required` "Log in to Kana Cards first."; `not_linked` "This account has no Steam link to confirm with."; `failed`, `cancelled`, `unavailable`, `no_session` as on the login page; `reauth_ok` "Confirmed with Steam. Repeat the action to continue."; `reauth_failed` "That Steam account is not the one linked to this account. Nothing was confirmed."
- **Your Tags** (right column): the tags an admin has granted, as chips (`.tag-chip`, label escaped with `_escHtml`), or "No tags". If the user has tags but no linked player, a hint asks them to link their player so the tags appear on their cards and the leaderboard. Tags show in every state.
- Errors appear in the status lines at the bottom of the main column.

An account without a password confirms destructive actions (Connect Twitch, merge, Disconnect, Unlink) with **Confirm with Steam** in the re-auth prompt instead of a password; Steam returns to Profile with `reauth_ok`. Connect Twitch then continues to Twitch by itself ("Confirmed with Steam. Continuing to Twitch…"); for the other actions the player repeats the action.

## Own player card popup

Issue #188. Opens on the page load after a grant (any tab, after `GET /me`, and right after Steam sign-up) while `GET /me` returns `own_card_grant`. Shown once per page load; text is set with `textContent`.

- **Granted:** the card viewer (`#revealModal`) shows the card (common), with the footer "Your own player card. You linked Steam, and you play in this season's league, so this card of {player name} is yours." and the action button **Nice**.
- **Already owned:** a small notice (`#ownCardNoticeModal`, eyebrow "Player identity", title "Your own player card"): "You already have a card of {player name}, so no new card was added." with **OK**.
- Closing either one (button, X, Escape or a backdrop click) calls `POST /profile/own-card-grant/seen`, so it doesn't come back.

## Past Seasons panel

- Hidden unless the user has archived season results; then lists them.

## Twitch panel

The panel heading is "Twitch". Its state comes from `GET /twitch/connection` (issue #160); no Twitch id is ever shown.

- **Not connected:** a short explanation (the Kana Cards panel on Twitch then uses this account; you sign in on Twitch's own page; only your Twitch user id is kept) and a **Connect Twitch** button. The button navigates to `GET /auth/twitch/start`. Without a recent password check the server sends the browser back to Profile and the existing **Confirm your password** prompt opens; once confirmed, the browser goes to Twitch. After Twitch, the page returns to Profile (`/#profile?twitch=<key>`, stripped from the address bar) with a status message by key (`app-profile.js` `_TWITCH_RETURN_MESSAGES`):
  - `connected`: "Twitch connected."
  - `connected_bonus`: "Twitch connected. You received N Twitch starter tokens." (issue #187; N is `twitch_connect_bonus_tokens` from `GET /config`, or "Twitch connected. You received your Twitch starter tokens." when that isn't a positive number; the Twitch starter bonus is paid once per Twitch account and once per website account when no panel collection is waiting)
  - `merge_ready`: "Twitch connected. Your Twitch collection is waiting below."
  - `in_use`: "This Twitch account is connected to another Kana Cards account"
  - `disconnect_first`: "Disconnect your current Twitch account first"
  - `cancelled`: "Twitch sign-in was cancelled. Nothing was changed."
  - `failed`: "Twitch sign-in did not complete. Nothing was changed. Try again."
  - `no_session` / `login_required`: "Log in to Kana Cards first, then connect Twitch."
  - `unavailable`: "Connecting Twitch is not available right now."
  - `reauth_required`: opens the password prompt and, once confirmed, starts the sign-in again; if the prompt is cancelled: "Confirm your password to connect Twitch."
- **Twitch's own error return:** when Twitch refuses the sign-in itself, it sends the browser to a registered redirect URL (often the site root) with `?error=<code>&state=…`. On load, `handleTwitchErrorReturn()` removes `error`, `error_description`, `error_uri` and `state` from the address bar (other parameters stay) and, for a logged-in player, opens Profile with a message in the Twitch section: `redirect_mismatch` → "Twitch sign-in failed: this site's Twitch redirect URL isn't registered with Twitch. Tell the league admins."; `access_denied` → the `cancelled` message; any other code → "Twitch sign-in did not complete. Nothing was changed. Try again. ({code})". Only the code (lowercase letters and `_`, else `unknown`) is shown, never Twitch's description. Logged out, the parameters are removed and no login prompt opens.
- **Unavailable** (any `TWITCH_OAUTH_*` setting missing): "Connecting Twitch is not available right now." and no button.
- **Connected:** "Connected to Twitch" (display font, accent colour), a note that disconnecting keeps cards and tokens, "Last Twitch activity: {date}" (from the account's last panel use, accurate to about an hour; "none yet" before any), and a **Disconnect** button. Disconnect asks for confirmation, then calls `POST /twitch/disconnect` (password prompt when needed) and shows "Twitch disconnected."
- **Merge prompt** (a Twitch panel collection is waiting): a box with an accent border: "Your Twitch collection: {cards} cards, {tokens} tokens. Add it to this account?" with **Add to my account** and **Not now**. Add calls `POST /twitch/merge/confirm` (password prompt when needed) and shows "{cards} cards and {tokens} tokens added". When the account already received the Twitch starter bonus, the merge takes it back (issue #187): from the collection's tokens first (`{tokens}` is what the collection adds), then from the account's own balance when the collection's starter was spent. The prompt adds "Adding it removes N tokens from your balance: this account already received the Twitch starter bonus, and the collection's starter tokens were spent." when the balance would go down, otherwise "(N Twitch starter tokens stay behind: this account already received the Twitch starter bonus.)". After the merge the message adds ". M tokens were removed from your balance: this account already received the Twitch starter bonus." or the same stay-behind note. Not now hides the box until the next Profile visit. When the account has already used its one merge, the box says the collection stays in the Twitch panel and has no buttons.
- **Guidance** (connected, nothing waiting, merge not used): "Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose Share your Twitch identity, then reload this page."
- Always, in small muted text: "Kana Cards never asks for your Twitch or website password inside Twitch."
- Errors appear in the status line at the bottom of the panel.
