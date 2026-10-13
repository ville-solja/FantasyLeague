# Plan: Panel Fits Twitch's Height

## Context
Issue #191: on the channel page the Live tab doesn't show top performers or the next match unless the panel is popped out, and the Roster tab shows about two and a half card slots without scrolling.

The cause is in `twitch-extension/extension.css`. The panel assumes a 318 × 500 frame:
```css
body.panel { height: 500px; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
```
Each view (`.view`, `position: absolute; inset: 0; overflow-y: auto`) scrolls inside that 500 px box. Twitch shows a panel in an iframe whose height comes from the version's **Panel Height** setting (up to 500 px), so a shorter iframe clips the bottom of the 500 px box. The view thinks it has room, never scrolls, and everything below the iframe's edge is unreachable. A popped-out panel gets a taller window, so everything shows.

The fix makes the panel use the height it is actually given:
- `100vh` instead of a fixed 500 px;
- views that always scroll within it;
- a visible, themed scrollbar so viewers can tell there is more;
- the Panel Height setting documented.

The dev harness gains height presets so this can't regress unnoticed. The width stays 318 px, Twitch's fixed panel width. Assumption: the version's Panel Height is currently below 500 px. Raising it to 500 helps, but the panel must also work at any allowed height (Twitch allows 100–500 px).

Resolves GitHub issue #191.

## User Stories

### Panel Uses the Height Twitch Gives It
**User story**
As a viewer, I want every part of the panel reachable on the channel page so that I don't have to pop it out to see the Live tab or my roster.

**Acceptance criteria**
- `body.panel` takes the iframe's height (`height: 100vh`; `html` and `body` without a fixed pixel height) instead of 500 px; the header and tab bar stay fixed at the top
- At panel heights of 300, 400 and 500 px and in the pop-out, the last element of every view (Live, Cards, Team draw, Roster, Card picker) can be reached by scrolling that view
- Nothing is cut off at the right edge at 318 px width; no horizontal scrolling
- Views with a pinned footer (Team draw, picker) keep the footer visible and scroll only the list above it

### Live Tab Shows Everything
**User story**
As a viewer, I want the Live tab to show latest MVPs, top performers and the next match in the panel so that I can follow the game without popping it out.

**Acceptance criteria**
- At 500 px all three sections are visible or reachable by scrolling the Live view; at 300 px they are reachable by scrolling
- The Live view keeps its scroll position when the 60 s refresh re-renders it (no jump back to the top)
- Loading and empty states still show in each section

### Roster Shows Every Slot
**User story**
As a viewer, I want to reach all my roster slots in the panel so that I can manage the whole roster from Twitch.

**Acceptance criteria**
- All `ROSTER_LIMIT` slots (and the bench, if shown) can be reached by scrolling the Roster view at 300, 400 and 500 px
- A slot's action buttons stay inside the 318 px width
- After activating, deactivating or swapping, the view keeps its scroll position

### Viewers Can See There Is More
**User story**
As a viewer, I want a visible scrollbar in the panel so that I know a view continues below the edge.

**Acceptance criteria**
- Scrollable views show a thin themed scrollbar (`scrollbar-width: thin`, `scrollbar-color`, and the `::-webkit-scrollbar` equivalents), visible on dark backgrounds, in the extension's colour tokens
- Scrolling works with mouse wheel, touch and keyboard: a view is focusable (`tabindex="0"`) or holds focusable content
- No text sits under the scrollbar

### Operators Set and Test the Panel Height
**User story**
As the operator, I want the Panel Height setting and a way to test several heights documented so that a new version doesn't ship clipped.

**Acceptance criteria**
- `markdown/features/core/twitch-extension.md`, Prerequisites table, gains a row for the version's **Panel Height**: 500, the largest Twitch allows, with the panel still working at smaller heights
- `twitch-extension/dev-harness.html` offers panel-height presets (300, 400, 500 px) and keeps the 318 px width
- "318 × 500" in the docs becomes "318 px wide, up to 500 px tall (the version's Panel Height)"
- `package.sh` output reminds the operator of the Panel Height value alongside the Asset Hosting paths

## Implementation

### Critical Files
| File | Change |
|---|---|
| `twitch-extension/extension.css` | `body.panel` height `100vh`; `html` height; themed thin scrollbars on `.view`, `.team-list` and other scroll areas; check fixed heights |
| `twitch-extension/panel.html` | `tabindex="0"` on scrollable views if they have no focusable content |
| `twitch-extension/panel.js` | Keep scroll position across the Live refresh and roster re-renders |
| `twitch-extension/dev-harness.html` | Height presets 300 / 400 / 500 |
| `twitch-extension/package.sh` | Print the Panel Height reminder |
| `markdown/features/core/twitch-extension.md`, `markdown/features/reference/twitch-extension-policy-compliance.md`, `markdown/ui_description/twitch-panel.md` | Panel Height row, "up to 500 px tall" wording, scroll behaviour |
| `backend/tests/test_issue_191_panel_fits_twitch_height.py` | Static checks on CSS, HTML and JS |

No backend change.

### Step 1 — Height
In `extension.css`, replace `height: 500px` on `body.panel` with `height: 100vh`, and give `html` `height: 100%`. Keep `overflow: hidden` on the body, so only the views scroll. Check every other fixed height in the panel rules: `.view`, `.with-pinned`, `.team-list`, the picker. Each scroll area should use `flex: 1; min-height: 0; overflow-y: auto` inside a flex parent, never a pixel height.

### Step 2 — Scrollbars
Add a thin, themed scrollbar to every scroll area:
```css
.view, .team-list { scrollbar-width: thin; scrollbar-color: var(--k-ink-500) transparent; }
.view::-webkit-scrollbar, .team-list::-webkit-scrollbar { width: 8px; }
.view::-webkit-scrollbar-thumb, .team-list::-webkit-scrollbar-thumb { background: var(--k-ink-500); border-radius: 4px; }
```
Use the extension's existing tokens. Keep the views' right padding so text isn't covered.

### Step 3 — Scroll position
In `panel.js`, save `view.scrollTop` before the Live refresh and roster re-renders replace their content, and restore it after.

### Step 4 — Harness and packaging
- **Dev harness:** add buttons that set the panel frame's height to 300, 400 or 500 px, keeping the 318 px width.
- **`package.sh`:** add "Panel Height: 500" to the console settings it prints.

### Step 5 — Tests
Static tests, following the existing extension tests (`test_twitch_review_resubmission.py`, `test_issue_180_*`):
- `body.panel` has no fixed pixel height; `.view` has `overflow-y: auto`;
- scrollbar rules exist;
- the harness has the height presets;
- the scroll position is kept in `panel.js`;
- the docs no longer say "318 × 500".

Keep the policy 4.5 viewer-text check passing. Keep `test_issue_85`'s suite-size baseline in step.

### Step 6 — Release
Package a new build. For example, `1.2.1+3`, if 1.2.1 is still in testing:
1. Move 1.2.1 back to Local Test.
2. Set **Panel Height** to 500.
3. Upload the zip.
4. Move it to Hosted Test.

## Verification
- **Dev harness:** at 300, 400 and 500 px, scroll each view to its last element:
  - Live: the next match;
  - Roster: the last slot;
  - Cards: the last collection row;
  - Team draw: the last team, with the footer visible.
- **On test, Hosted Test:** with Panel Height at 500, Live shows all three sections and Roster reaches every slot without popping out. The pop-out still works.
- **Live refresh:** wait for the 60 s refresh while scrolled down; the view stays where it was.
- **Tests:** `cd backend && python3 -m pytest tests/ -q`.
