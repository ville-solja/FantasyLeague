# Plan: My Team Tab Layout

## Context

The My Team tab currently stacks the Deck panel above the Roster panel, both spanning the full page width. This means users must scroll past draw controls and deck counts to reach their roster — the most frequently consulted section. Issue #17 requests that the roster become the dominant element and that secondary controls (deck counts, draw, promo code) move to a right sidebar. Token redemption should also be in the sidebar rather than occupying prime content space.

## User Stories

### 17.1 Roster-first My Team Layout
**User story**
As a user, I want the My Team tab to show my roster as the primary content area so that I can see my active lineup and bench immediately without scrolling past deck controls.

**Acceptance criteria**
- My Roster (active cards + bench) occupies the majority of the tab's horizontal space
- Deck panel appears to the right of the roster as a sidebar, not above it
- On narrow screens (< 768 px) the sidebar stacks below the roster so the mobile experience is unaffected
- The order of content on mobile is: Roster → Sidebar (Deck + draw + promo)

---

### 17.2 Deck Sidebar with Draw and Token Redemption
**User story**
As a user, I want deck counts, the draw button, token balance, and the promo code field in a compact sidebar so these controls remain accessible without dominating the view.

**Acceptance criteria**
- Sidebar contains (top to bottom): deck rarity counts, draw button + token balance, promo code field, scoring info toggle
- Sidebar width is fixed at approximately 300 px on desktop; it does not grow with the window
- All existing IDs and onclick handlers are preserved — only layout changes, no JS logic changes
- The `ui_description/my-team.md` file is updated to reflect the new layout

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | Restructure `#tab-team` grid: reorder panels, remove full-width spans, add sidebar wrapper |
| `frontend/style.css` | Add `#tab-team .grid` override and responsive breakpoint |
| `markdown/ui_description/my-team.md` | Update layout description to reflect sidebar arrangement |

### Step 1 — Override grid layout for the My Team tab

Add a CSS rule that gives `#tab-team .grid` a two-column layout with a fixed sidebar:

```css
#tab-team .grid {
    grid-template-columns: 1fr 300px;
}

@media (max-width: 768px) {
    #tab-team .grid {
        grid-template-columns: 1fr;
    }
}
```

This overrides the generic `.grid` rule only for the My Team tab without affecting other tabs.

### Step 2 — Reorder panels in index.html

In `#tab-team`, swap the panel order so My Roster comes first (DOM order determines column order on mobile):

1. Move the My Roster `<div class="panel">` block before the Deck `<div class="panel">` block
2. Remove `style="grid-column: span 2;"` from both panels — they should each occupy one grid column

The Deck panel becomes the right column (sidebar) automatically because it is second in DOM order.

### Step 3 — Update ui_description/my-team.md

Update the file to describe:
- My Roster as the primary/left content area
- Deck panel as the right sidebar
- Mobile: sidebar stacks below roster

## Verification

- On a wide viewport (≥ 800 px): My Roster visible on the left, Deck sidebar on the right, no horizontal overflow
- On a narrow viewport (≤ 600 px): panels stack vertically, Roster first then Deck — no layout breakage
- Draw button, promo code, week selector, activate/bench actions all function identically to before
- No JS changes; verify by drawing a card and activating/benching a card after the layout change
