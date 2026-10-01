# Profile tab

Visible only to logged-in users.

## Account panel

- **Username** — editable field pre-filled with the current username. Save button updates it server-side; must remain unique. A muted hint below the field lists the allowed characters (letters, digits, underscore, hyphen); other characters get a 422 error in the status line.
- **Password** — two fields (current password, new password). Requires the correct current password before accepting a change. A successful change keeps this session and logs out every other device.
- **Log out everywhere** — button under the password form, with a muted note explaining it. After a confirmation prompt it calls `POST /logout-everywhere`, which ends every session of the account including this one, and the page returns to the logged-out state. Errors appear in the status line below the button.
- **Signed-in devices** — a small table under **Log out everywhere**, loaded from `GET /sessions` when the tab opens and again after a password change. Columns: Signed in, Last active (the current device is marked "(this device)"), and a **Sign out** button per row that calls `DELETE /sessions/{id}`. Signing out another device reloads the list and shows "Session signed out"; signing out the current device returns the page to the logged-out state. "No active sessions" when the list is empty. Errors appear in the status line below the table. Rows are built with `textContent`.

## Revoked sessions

If a session was ended elsewhere (password change on another device, log out everywhere, a **Sign out** on another device, admin force logout or admin toggle, password reset) or it expired (14 days without a visit or 30 days after login for players; 2 hours idle or 12 hours for admins), the next page load gets 401 from `GET /me`. The header then shows the logged-out state instead of the stale username, and the stored username and admin flag are cleared.

## Dota 2 Player panel

- Optional link between the user's account and an OpenDota account ID (the player's real league account). The panel text explains that linking makes admin-granted tags appear as card stickers and leaderboard chips.
- When a valid ID is saved and the player exists in the database, the player's name and avatar are shown as a preview.

## Your Tags panel

- Lists the tags an admin has granted the user.
- If the user has tags but no linked player ID, a hint asks them to link it so the tags appear on their cards and the leaderboard.

## Past Seasons panel

- Hidden unless the user has archived season results; then lists them.

## Twitch Account panel

- **Linked:** "Twitch account linked" and a note that the user can win token drops when a streamer confirms a match MVP while they watch.
- **Not linked:** a note and a **Generate Twitch Code** button (`POST /twitch/link-code`). The 6-character code appears with its expiry, to be entered in the extension panel on a Twitch stream.
