# Plan: Twitch Integration

## Context

The Twitch extension already exists and is largely functional: `extension.js` reads the EBS URL from the Twitch Configuration Service global segment, `panel.html` shows viewer status and handles account linking, and `live_config.html` has the full MVP selection flow. The core remaining problem is that the EBS URL configuration process is confusing — it conflates the responsibilities of the **Kanaliiga developer** (who registers the extension and sets the global EBS URL once) with the **broadcaster** (who just installs the extension and starts using it). Broadcasters should not need to configure anything at all. This plan clarifies roles, revises the stories, and ensures the developer console prerequisites are documented prominently so first-time setup succeeds.

---

## User Stories

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
- If the EBS cannot be reached, the panel shows a clear error rather than a blank state

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
- The extension works immediately after install — EBS URL is pre-configured globally by the Kanaliiga developer and requires no per-channel action
- Quick Actions (Live Config view) are visible in the Twitch Stream Manager dashboard after install
- The Fantasy app documents where to find and install the extension

---

### 13.5 Operator EBS URL Configuration
**User story**
As the Kanaliiga developer, I want to set the EBS URL once in the Twitch developer console so that all channel installs of the extension automatically point to the correct backend — without requiring streamers to configure anything.

**Acceptance criteria**
- The required developer console settings are documented clearly in the feature doc (see critical settings below)
- Running `bash twitch-extension/set-ebs-url.sh <url>` sets the global Configuration Service segment, which propagates to all installs
- The extension reads the URL from `Twitch.ext.configuration.global.content` — no rebuild or re-upload required after a URL change
- The `.env` requires only `TWITCH_EXTENSION_CLIENT_ID`, `TWITCH_EXTENSION_SECRET`, and `TWITCH_DROP_MAX`
- Documentation explicitly calls out the three common mistakes (wrong secret field, non-empty channel segment version, Configuration Service not activated)

---

## Critical Developer Console Settings

These must be configured in the [Twitch dev console](https://dev.twitch.tv/console/extensions) before the integration works. They are easy to get wrong and should be the first thing documented.

| Setting | Where | Required value |
|---|---|---|
| Configuration method | Extension Settings → "Select how you will configure your extension" | **Extension Configuration Service** — must be saved explicitly |
| Developer Writable Channel Segment Version | Extension Settings → same section | **Leave empty** — this is not where the EBS URL goes; filling it in gates the extension per-channel |
| Extension status | Extension Settings | **Local Test** or higher before the Configuration Service API will accept writes |
| Client ID | Extension Settings → top-right | Used as `TWITCH_EXTENSION_CLIENT_ID` in `.env` and in `set-ebs-url.sh` |
| Extension Secret | Extension Settings → "Extension Secrets" table → **Key column** | Used as `TWITCH_EXTENSION_SECRET`. **Not** the "Twitch API Client Secret" shown mid-page |

---

## Implementation

The majority of the implementation already exists. This plan documents what remains and what needs updating.

### Critical Files

| File | Change |
|---|---|
| `markdown/features/core/twitch-extension.md` | Rewrite Deployment section to lead with the critical settings table; clarify operator vs broadcaster responsibilities |
| `markdown/stories/13-twitch.md` | Replace with revised stories 13.1–13.5 from this plan |
| `twitch-extension/panel.html` | Verify error state when EBS URL is missing from config (show message, not blank) |
| `twitch-extension/extension.js` | Verify `_cfgReady` timeout: if config segment never arrives, surface a clear error rather than silently hanging |

---

### Step 1 — Verify panel error state

`panel.html` currently falls back to `showBanner(el("banner"), "Could not reach FantasyLeague server.", true)` when the `/twitch/status` call fails. If the EBS URL is missing from the config segment entirely, `ext.ebsUrl` is `null` and `onReady()` never fires — the panel appears blank.

Add a timeout in `extension.js`: if `_cfgReady` is still false after 8 seconds, show a fallback message: `"Extension not configured — contact the broadcaster."` This prevents silent failure for viewers if the operator has not yet run `set-ebs-url.sh`.

---

### Step 2 — Update the feature doc deployment section

Restructure `markdown/features/core/twitch-extension.md` so the Deployment section leads with the **critical console settings table** (from this plan), then lists the numbered steps. The current prose buries the key pitfalls (wrong secret, non-empty channel segment) in `>Note` callouts mid-section. Move them to the top as a prerequisite checklist.

---

### Step 3 — Update stories

Replace `markdown/stories/13-twitch.md` with stories 13.1–13.5 from this plan. Stories 13.1 and 13.2 are revised for clarity; 13.3 is unchanged; 13.4 and 13.5 are new explicit stories for the broadcaster and operator setup paths respectively.

---

## Verification

- Run `set-ebs-url.sh --debug` and confirm the global config segment is written (HTTP 204)
- Open the dev harness (`/twitch-ext/dev-harness.html`) and confirm the panel loads status from the EBS URL read from the simulated config
- Install the extension in developer test mode on a test channel; confirm Quick Actions appear in Stream Manager without any per-channel EBS configuration
- Test the MVP flow end-to-end: select series → match → player → confirm; verify token drop fires and panel banner appears
- Re-confirm the same match with a different player; verify token drop does NOT re-fire
- Simulate a missing config segment: clear the global config and reload the panel; confirm the error message appears after ≤8 seconds rather than a blank panel
