# Twitch Integration

### MVP Selection and Token Drop
**User story**
As a broadcaster, I want to select the MVP of a completed match from the Quick Actions panel so that tokens are automatically dropped to viewers who are watching.

**Acceptance criteria**
- Broadcaster opens Quick Actions (Live Config view in Twitch Stream Manager) and clicks "Select match MVP"
- Flow: select series (team1 vs team2) → select match (Match 1, Match 2…) → select player from the match roster
- Confirming MVP saves the selection and fires a one-time token drop to the presence pool
- Drop fires only on the **first** confirmation for a given match — re-confirming a different player for the same match does not re-drop
- Up to `TWITCH_DROP_MAX` (default 20) randomly selected linked viewers from the pool receive +1 token
- Broadcaster sees confirmation: MVP player name + count of viewers who received tokens

---

### Viewer Panel
**User story**
As a viewer, I want to open the Twitch panel during a Kanaliiga stream so I can see my token balance, the current MVP, and be eligible for token drops.

**Acceptance criteria**
- Panel fetches the EBS URL from `Twitch.ext.configuration.global.content` at startup — no viewer-side or broadcaster-side URL configuration needed
- Unlinked viewers see the account linking instructions (enter 6-char code from the Fantasy Profile tab)
- Linked viewers see their token balance and linked username
- MVP announcements arrive via PubSub and display as a temporary banner
- Token drop winner announcements also display via PubSub and refresh the token count
- If the EBS URL is missing or unreachable, the panel shows a clear error rather than a blank state

---

### Account Linking
**User story**
As a Fantasy League user, I want to link my Twitch account so I am eligible for token drops while watching the stream.

**Acceptance criteria**
- User navigates to the Fantasy Profile tab and clicks "Generate Twitch Code"
- A 6-character alphanumeric code is displayed with a 10-minute countdown
- User enters the code in the Twitch extension panel and clicks Link
- Backend validates the code, stores the Twitch opaque user ID on the user record, and confirms the link
- Once linked, the panel shows token balance and the user is eligible for future drops

---

### Broadcaster Extension Installation
**User story**
As a broadcaster for Kanaliiga, I want to install the Twitch extension and start using it immediately — without manually configuring any backend URLs.

**Acceptance criteria**
- Extension works immediately after install — EBS URL is pre-configured globally by the Kanaliiga developer, no per-channel action required
- Quick Actions (Live Config view) are visible in the Twitch Stream Manager dashboard after install

---

### Operator EBS URL Configuration
**User story**
As the Kanaliiga developer, I want to set the EBS URL once in the Twitch developer console so that all channel installs of the extension automatically point to the correct backend.

**Acceptance criteria**
- Required developer console settings are documented with a prerequisite checklist
- Running `bash twitch-extension/set-ebs-url.sh <url>` sets the global Configuration Service segment
- The extension reads `Twitch.ext.configuration.global.content` at startup — URL change takes effect immediately on next panel load
- `.env` requires only `TWITCH_EXTENSION_CLIENT_ID`, `TWITCH_EXTENSION_SECRET`, and `TWITCH_DROP_MAX`

---

### MVP Fantasy Score Bonus
**User story**
As a fantasy league player, I want the designated MVP of a match to earn an extra percentage on their fantasy score for that match so that the broadcast MVP appointment has real in-game value.

**Acceptance criteria**
- When a broadcaster confirms an MVP via the Twitch extension, that player's `fantasy_points` for that specific match is multiplied by `(1 + mvp_bonus_pct / 100)`
- If the broadcaster later changes the MVP to a different player for the same match, the old player's bonus is removed and the new player receives it
- The bonus is reflected immediately in roster point totals, leaderboard standings, and the player match history
- An MVP match is visually distinguishable from a regular match in the player detail modal

---

### Configurable MVP Bonus Weight
**User story**
As an admin, I want to configure the MVP fantasy bonus percentage from the admin weights panel so I can tune its value without code changes.

**Acceptance criteria**
- A weight key `mvp_bonus_pct` (label: "MVP bonus (%)") is present in the admin weights panel with a default of `10.0`
- Changing the value and running `POST /recalculate` re-applies the updated bonus to all MVP-flagged matches
- `mvp_bonus_pct = 0` effectively disables the bonus without removing the MVP flag from past matches
