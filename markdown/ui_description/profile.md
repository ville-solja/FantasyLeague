# Profile tab

Visible only to logged-in users.

## Account panel

- **Username** — editable field pre-filled with the current username. Save button updates it server-side; must remain unique, ignoring letter case. A muted hint below the field lists the allowed characters (letters, digits, underscore, hyphen) and says names that look like staff or the league (admin, Kanaliiga, support…) are not available; other characters get a 422 error in the status line, and a reserved name gets "This name is reserved". Real admins see an **ADMIN** badge next to the "Username" label (`#profileAdminBadge`; outlined accent chip in display type, see Leaderboards). One rename per 7 days by default (issue #169): while the cooldown runs, a second muted line (`#profileRenameHint`) reads "You can rename again on <date>.", and saving a different name shows the server's "You can change your username again on <date> UTC" error. Saving the same name or changing only its letter case is always allowed.
- **Password** — hidden for an account without a password (created through Steam, issue #150), which shows "This account signs in with Steam and has no password." instead. Otherwise two fields (current password, new password). Requires the correct current password before accepting a change. A successful change keeps this session and logs out every other device. The fields and the **Change password** button are a form (`#changePasswordForm`): Enter in either field submits it, and password managers fill the current password and offer to update the saved login (a hidden, read-only username field holds the logged-in username; see `features/reference/password-manager-autofill.md`).
- **Log out everywhere** — button under the password form, with a muted note explaining it. After a confirmation prompt it calls `POST /logout-everywhere`, which ends every session of the account including this one, and the page returns to the logged-out state. Errors appear in the status line below the button.
- **Signed-in devices** — a small table under **Log out everywhere**, loaded from `GET /sessions` when the tab opens and again after a password change. Columns: Signed in, Last active (the current device is marked "(this device)"), and a **Sign out** button per row that calls `DELETE /sessions/{id}`. Signing out another device reloads the list and shows "Session signed out"; signing out the current device returns the page to the logged-out state. "No active sessions" when the list is empty. Errors appear in the status line below the table. Rows are built with `textContent`.

## Revoked sessions

If a session was ended elsewhere (password change on another device, log out everywhere, a **Sign out** on another device, admin force logout or admin toggle, password reset) or it expired (14 days without a visit or 30 days after login for players; 2 hours idle or 12 hours for admins), the next page load gets 401 from `GET /me`. The header then shows the logged-out state instead of the stale username, and the stored username and admin flag are cleared.

## Steam panel

Issue #150. Shown only when `LOGIN_METHOD` is `both` or `steam_signup` (`GET /config`); driven by `GET /me` `steam_linked` / `has_password` / `is_demo` (`steamUiState` in `app-auth.js`). The Steam id is never shown, only linked yes/no.

- **Reminder** (`steam_signup` mode, account with a password and no Steam link): a box with an accent border: "Link Steam now. Password sign-in will end in a later update."
- **Not linked** (never for demo accounts): a short explanation (sign in with Steam and verify your Dota player id; sign-in happens on steamcommunity.com; Kana Cards never asks for your Steam password) and a **Link Steam** button. It navigates to `GET /auth/steam/start?purpose=link`. Without a recent identity check the server sends the browser back with `steam=reauth_required`, the **Confirm your password** prompt opens, and once confirmed the browser goes to Steam; if cancelled: "Confirm your password to link Steam."
- **Linked:** "Steam linked" (display font, accent colour), "Your Dota player id is verified with Steam." and, for accounts that also have a password, an **Unlink Steam** button. Unlink asks for confirmation, then calls `POST /profile/steam/unlink` (password prompt when needed) and shows "Steam unlinked." Steam-only accounts have no Unlink button.
- After Steam, the page returns to Profile (`/#profile?steam=<key>`, stripped from the address bar) with a status message by key (`_STEAM_RETURN_MESSAGES` in `app-auth.js`): `linked` "Steam linked. Your Dota player id is now verified."; `in_use` "This Steam account is linked to another Kana Cards account"; `unlink_first` "Unlink your current Steam account first"; `not_allowed` "Demo accounts can't link Steam."; `login_required` "Log in to Kana Cards first."; `not_linked` "This account has no Steam link to confirm with."; `failed`, `cancelled`, `unavailable`, `no_session` as on the login page; `reauth_ok` "Confirmed with Steam. Repeat the action to continue."; `reauth_failed` "That Steam account is not the one linked to this account. Nothing was confirmed."
- Errors appear in the status line at the bottom of the panel.

An account without a password confirms destructive actions (Connect Twitch, merge, Disconnect, Unlink) with **Confirm with Steam** in the re-auth prompt instead of a password; Steam returns to Profile with `reauth_ok`. Connect Twitch then continues to Twitch by itself ("Confirmed with Steam. Continuing to Twitch…"); for the other actions the player repeats the action.

## Dota 2 Player panel

- Optional link between the user's account and an OpenDota account ID (the player's real league account). The panel text explains that linking makes admin-granted tags appear as card stickers and leaderboard chips.
- For a Steam-linked account the field and **Save** are disabled and "Verified with Steam." shows under them; the id comes from Steam (`PUT /profile/player-id` answers 409).
- When a valid ID is saved and the player exists in the database, the player's name is shown as a preview with a small uppercase label (`#profilePlayerSource`): "Verified with Steam" (accent colour) for a Steam-verified id, or "Self-reported" (muted) for a typed-in id. The avatar shows only for a verified id (issue #169), as other players would see it.

## Your Tags panel

- Lists the tags an admin has granted the user.
- If the user has tags but no linked player ID, a hint asks them to link it so the tags appear on their cards and the leaderboard.

## Past Seasons panel

- Hidden unless the user has archived season results; then lists them.

## Twitch panel

The panel heading is "Twitch". Its state comes from `GET /twitch/connection` (issue #160); no Twitch id is ever shown.

- **Not connected:** a short explanation (the Kana Cards panel on Twitch then uses this account; you sign in on Twitch's own page; only your Twitch user id is kept) and a **Connect Twitch** button. The button navigates to `GET /auth/twitch/start`. Without a recent password check the server sends the browser back to Profile and the existing **Confirm your password** prompt opens; once confirmed, the browser goes to Twitch. After Twitch, the page returns to Profile (`/#profile?twitch=<key>`, stripped from the address bar) with a status message by key (`app-profile.js` `_TWITCH_RETURN_MESSAGES`):
  - `connected`: "Twitch connected."
  - `merge_ready`: "Twitch connected. Your Twitch collection is waiting below."
  - `in_use`: "This Twitch account is connected to another Kana Cards account"
  - `disconnect_first`: "Disconnect your current Twitch account first"
  - `cancelled`: "Twitch sign-in was cancelled. Nothing was changed."
  - `failed`: "Twitch sign-in did not complete. Nothing was changed. Try again."
  - `no_session` / `login_required`: "Log in to Kana Cards first, then connect Twitch."
  - `unavailable`: "Connecting Twitch is not available right now."
  - `reauth_required`: opens the password prompt and, once confirmed, starts the sign-in again; if the prompt is cancelled: "Confirm your password to connect Twitch."
- **Unavailable** (any `TWITCH_OAUTH_*` setting missing): "Connecting Twitch is not available right now." and no button.
- **Connected:** "Connected to Twitch" (display font, accent colour), a note that disconnecting keeps cards and tokens, "Last Twitch activity: {date}" (from the account's last panel use, accurate to about an hour; "none yet" before any), and a **Disconnect** button. Disconnect asks for confirmation, then calls `POST /twitch/disconnect` (password prompt when needed) and shows "Twitch disconnected."
- **Merge prompt** (a Twitch panel collection is waiting): a box with an accent border: "Your Twitch collection: {cards} cards, {tokens} tokens. Add it to this account?" with **Add to my account** and **Not now**. Add calls `POST /twitch/merge/confirm` (password prompt when needed) and shows "{cards} cards and {tokens} tokens added". Not now hides the box until the next Profile visit. When the account has already used its one merge, the box says the collection stays in the Twitch panel and has no buttons.
- **Guidance** (connected, nothing waiting, merge not used): "Joined on Twitch first? In the Kana Cards Twitch panel, open Settings and choose Share your Twitch identity, then reload this page."
- Always, in small muted text: "Kana Cards never asks for your Twitch or website password inside Twitch."
- Errors appear in the status line at the bottom of the panel.
