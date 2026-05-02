# Profile Header Link

Converts the static username label in the page header into a clickable button that navigates directly to the Profile tab, making profile settings reachable in one click from anywhere in the app.

---

## Behaviour

When a user is logged in, their username is displayed as a ghost-style button in the top-right header alongside the Logout button. Clicking it activates the Profile tab. When logged out, the button is hidden so no empty interactive element is visible.

No backend changes are involved. The feature is purely a frontend interaction change: the `<span id="headerUserLabel">` element becomes a `<button>`, `applyAuthState()` toggles its visibility, and an `onclick` handler calls the existing `switchTab('profile')` function.

## Files changed

| File | Change |
|---|---|
| `frontend/index.html` | `#headerUserLabel` changed from `<span>` to `<button class="ghost header-profile-btn" onclick="switchTab('profile')">` |
| `frontend/style.css` | `.header-profile-btn` — display font, bold weight, `0.04em` tracking, `4px 10px` padding |
| `frontend/app-auth.js` | `applyAuthState()` toggles `userLabel.style.display` alongside `textContent` |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
