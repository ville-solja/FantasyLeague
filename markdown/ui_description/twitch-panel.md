# Twitch panel (viewer)

The Kana Cards panel extension below the stream (`twitch-extension/panel.html`, `panel.js`), 318 × 500 px. A complete game on Twitch: it never mentions, links to or asks for a login on the website (Twitch policy 4.5, issue #157). Styled with the Kanaliiga design system: Big Shoulders uppercase display type, Inter body, orange accent on near-black, 4 px buttons, 6 px boxes, no text under 11 px, no emoji. Feature details: `markdown/features/reference/twitch-extension-policy-compliance.md`.

## Header

- "KANA CARDS" wordmark.
- Once joined: the token count ("5 TOKENS") and a Settings (gear) button.

## Tabs

**Live**, **Cards**, **Roster**; the active tab has an orange label and a 2 px orange underline. The panel opens on Live for every viewer. A short message ("MVP: Savu", "+1 token from the MVP drop") appears at the top for a few seconds when something happens.

## Join box

Shown at the top of Live, and in place of the Cards and Roster content, until the viewer joins.
- **Logged in to Twitch:** "Join Kana Cards", a one-line description, the **Join Kana Cards** button and the consent line "Uses your Twitch login. We store your Twitch id and game progress; leave any time in Settings." Pressing it opens Twitch's identity-share dialog and joins either way. An error line appears under the button when joining fails.
- **Logged out of Twitch:** "Log in to Twitch to join" instead of the button.

## Live tab

Three sections, each with an eyebrow heading:
- **Latest MVPs:** up to 3 recent series ("Team A vs Team B") with one entry per game: "G1 MVP Savu", "G2 (live)" or "G2 no MVP yet".
- **Top performers:** the 3 best fantasy scores of the latest games, ranked, with points.
- **Next match:** the next scheduled series, its local start time and week label.

Refreshes every 60 seconds and at once when the broadcaster confirms an MVP. Empty or unreachable sections show a short neutral line ("No games scored yet.", "No match scheduled.", "Live results are unavailable right now.").

## Cards tab

- **Draw · 1** (disabled without tokens, with a note on how tokens are earned) and **Team draw · 3**.
- **Card reveal** after a draw: the card art in its rarity treatment (tinted art, rarity border, glow on the art only, player initials), rarity, player name, team, and "Added to your roster" or "Added to your bench".
- **Collection:** a count ("22 cards"), rarity filter chips with counts (All, Leg, Epic, Rare, Com), and a five-per-row grid of 48 × 66 card art with names, rarest first then by name. Scrolls inside the panel.

## Team draw view

- **Back** and the "Team draw" heading, then "Pick a team. You get one of its players you don't own yet. Costs 3 tokens."
- A scrolling two-column list of 44 px team rows: logo (or a 28 × 28 monogram chip), team name, and "N left" or "Complete" (dimmed, disabled). Available teams first, alphabetically; Complete teams last. The selected row has an orange border and accent-ghost background (`aria-pressed`).
- Pinned at the bottom: **Draw from {team} · 3**, disabled until a team is picked or while the player has fewer than 3 tokens ("You need 3 tokens for a team draw"). A draw returns to the Cards tab with the reveal.

## Roster tab

- The editable week's label, the lock countdown ("Locks in 2d 4h"), and "{week} so far: 12.3 pts" while a week is in progress.
- Five numbered slots. An empty slot shows "Empty slot" and **+ Add a card**; a filled slot shows the card art, player, team, the week's points and **Change**.
- A confirmation line after a change ("Savu in, Pikkis to the bench.").
- The bench count ("18 cards on the bench").
- **Locked:** "Roster locked for this week" and no buttons (when no editable week exists and a locked week is in progress).
- No drag-and-drop.

## Bench picker (per slot)

- **Back**, and "Pick a card for slot N" or "Replace in slot N".
- For a filled slot: "In this slot: {name}" with **Bench it**.
- Rarity filter chips with counts, and **Sort** by **Points** (season points, default) or **Rarity**.
- One row per bench card: art, name, team, rarity, season points. Tapping a row places it in the empty slot or swaps it with the slot's card, then returns to the Roster tab.

## Settings

- **Share your Twitch identity** with a short explanation (hidden once shared).
- **Leave Kana Cards**: the first press changes it to "Press again to leave"; the second deletes the soft account and its game data (a website account (connected with Twitch sign-in, or linked earlier by code) is only disconnected; the text says so). The panel then returns to the not-joined Live tab.
- Privacy note: what is stored and why; "Kana Cards never asks for a password."
