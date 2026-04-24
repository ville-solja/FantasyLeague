# 13. Twitch Integration

### 13.1 MVP Selection and Token Drop
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

### 13.2 Viewer Panel
**User story**
As a viewer, I want to open the Twitch panel during a Kanaliiga stream so I can see my token balance, the current MVP, and be eligible for token drops.

**Acceptance criteria**
- Panel fetches the EBS URL from `Twitch.ext.configuration.global.content` at startup — no viewer-side or broadcaster-side URL configuration needed
- Unlinked viewers see the account linking instructions (enter 6-char code from the Fantasy Profile tab)
- Linked viewers see their token balance and linked username
- MVP announcements arrive via PubSub and display as a temporary banner
- Token drop winner announcements also display via PubSub and refresh the token count
- If the EBS URL is missing from config or the EBS cannot be reached, the panel shows a clear error message rather than a blank state (timeout ≤8 seconds)

---

### 13.3 Account Linking
**User story**
As a Fantasy League user, I want to link my Twitch account so I am eligible for token drops while watching the stream.

**Acceptance criteria**
- User navigates to the Fantasy Profile tab and clicks "Generate Twitch Code"
- A 6-character alphanumeric code is displayed with a 10-minute countdown
- User enters the code in the Twitch extension panel and clicks Link
- Backend validates the code, stores the Twitch opaque user ID on the user record, and confirms the link
- Once linked, the panel shows token balance and the user is eligible for future drops

---

### 13.4 Broadcaster Extension Installation
**User story**
As a broadcaster for Kanaliiga, I want to install the Twitch extension and start using it immediately — without manually configuring any backend URLs.

**Acceptance criteria**
- Broadcaster installs the Kanaliiga FantasyLeague extension from the Twitch extension directory (or developer test install)
- Extension works immediately after install — EBS URL is pre-configured globally by the Kanaliiga developer, no per-channel action required
- Quick Actions (Live Config view) are visible in the Twitch Stream Manager dashboard after install
- The Fantasy app documents where to find and install the extension

---

### 13.5 Operator EBS URL Configuration
**User story**
As the Kanaliiga developer, I want to set the EBS URL once in the Twitch developer console so that all channel installs of the extension automatically point to the correct backend.

**Acceptance criteria**
- Required developer console settings are documented with a prerequisite checklist (Configuration Service enabled, channel segment version empty, correct secret field, extension in Local Test or higher)
- Running `bash twitch-extension/set-ebs-url.sh <url>` sets the global Configuration Service segment, which propagates to all installs without a rebuild
- The extension reads `Twitch.ext.configuration.global.content` at startup — URL change takes effect immediately on next panel load
- `.env` requires only `TWITCH_EXTENSION_CLIENT_ID`, `TWITCH_EXTENSION_SECRET`, and `TWITCH_DROP_MAX`
