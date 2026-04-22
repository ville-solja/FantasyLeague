# 17. My Team Tab Layout

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
