# Plan: Demo Mode Badge Position

## Context
With `DEMO_MODE=true` the app shows a "DEMO MODE" notice as a full-width strip fixed to the top of the window (`.demo-mode-badge`, `z-index: 10000`). It sits over the header and the tab bar. The notice should stay visible on every page so nobody mistakes a demo for the real league, but in the bottom-right corner, where it covers nothing people need to read or click. The faint build version badge (`.version-badge`, bottom 6px, right 10px) already lives there, so the demo notice stacks just above it. Only the position and shape change; the text, the `GET /config` `demo_mode` flag and the toggle in `loadConfig()` stay as they are. Resolves GitHub issue #173.

## User Stories

### Demo Notice Out of the Way
**User story**
As anyone using a demo deployment, I want the "DEMO MODE" notice in the bottom-right corner so that I always know it is a demo without the notice covering the header or tabs.

**Acceptance criteria**
- With `demo_mode` true, the notice reads "DEMO MODE" and is fixed to the bottom-right corner of the window, directly above the version badge, on every tab and at every window width
- It no longer spans the top of the page: the header, tab bar and their buttons are fully visible and clickable
- It never takes clicks (`pointer-events: none`) and can't be selected, so nothing under it is blocked
- It stays above page content and open modals, as before
- On a phone-width window (360px) it fits on one line inside the window, with a gap from the right and bottom edges, and does not overlap the version badge
- With `demo_mode` false or unset, the notice is not shown

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/style.css` | `.demo-mode-badge`: from a full-width top strip to a compact bottom-right chip above `.version-badge` |
| `markdown/features/reference/demo-mode.md` | Describe the new position |
| `markdown/stories/admin.md` | New story under Demo Mode |
| `backend/tests/test_issue_173_demo_mode_badge_position.py` | Static CSS and markup checks |

### Step 1 — Restyle the badge
Replace the top-strip rules with a corner chip, using the design tokens already used nearby:

```css
.demo-mode-badge {
  position: fixed;
  right: 10px;
  bottom: 28px;            /* above .version-badge (bottom: 6px) */
  background: #b8390e;
  color: #fff;
  font-family: var(--font-display, "Big Shoulders Text", sans-serif);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: var(--r-xs);
  white-space: nowrap;
  z-index: 10000;
  pointer-events: none;
  user-select: none;
}
```

The markup (`#demo-mode-badge` in `index.html`) and the toggle in `app-globals.js` don't change.

### Step 2 — Docs and tests
- `demo-mode.md`: "a small fixed notice in the bottom-right corner, above the version badge" instead of "fixed banner".
- Static test: the `.demo-mode-badge` rule has `bottom` and `right`, no `top` or `left`, keeps `pointer-events: none` and `z-index` ≥ the version badge's, and uses `var(--r-xs)` (the brand radius rule in `test_issue_144_guided_tour.py`).

## Verification
- `cd backend && python -m pytest tests/test_issue_173_demo_mode_badge_position.py`
- Run the app with `DEMO_MODE=true`: the notice sits bottom right above the version badge, the header and tabs are uncovered, and clicks pass through it. Check at 360px and desktop widths, and with a modal and the guided tour open.
- With `DEMO_MODE` unset the notice is hidden.
