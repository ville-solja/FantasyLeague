# Panel Fits Twitch's Height

The Twitch panel uses the height of the iframe Twitch gives it (the version's Panel Height, up to 500 px), scrolls each view within it, and shows a themed scrollbar. Fixes views clipped below the iframe's edge. Resolves GitHub issue #191.

---

## Cause

`body.panel` was fixed at `height: 500px; overflow: hidden`. In an iframe shorter than 500 px, the bottom of that box was clipped, and the views (which scroll inside the 500 px box) never scrolled to it. Popped out, the window was tall enough, so everything showed.

## Layout

`twitch-extension/extension.css`:
- `html { height: 100% }`; `body.panel { height: 100vh; overflow: hidden; display: flex; flex-direction: column }`. No fixed pixel height remains on `html` or the body.
- The header (`.p-head`) and tab bar (`.p-tabs`) are `flex: none`; `.p-main` is `flex: 1; min-height: 0` and holds the views.
- Each `.view` is `position: absolute; inset: 0; overflow-x: hidden; overflow-y: auto`, so it scrolls in whatever height is left.
- Views with a pinned footer (`.view.with-pinned`: Team draw and the bench picker) are a flex column with `overflow: hidden`; only the list scrolls (`.team-list`, and `.pin-scroll` in the picker, both `flex: 1; min-height: 0; overflow-y: auto`). The picker's "In this slot: {name}" box with **Bench it** is its pinned footer, shown only for a filled slot (`#picker-pinned`).
- Short panels (`@media (max-height: 420px)`): the list alone would get one or two rows, so the whole Team draw / picker view scrolls (`overflow-y: auto`, lists `overflow: visible`) and the footer stays visible with `position: sticky; bottom: 0`.
- Width stays 318 px (Twitch's panel width).

## Scrollbars and focus

`.view`, `.team-list` and `.pin-scroll` get `scrollbar-width: thin` and `scrollbar-color: var(--k-ink-400) transparent`, plus `::-webkit-scrollbar` (8 px), `-track` (transparent) and `-thumb` (`--k-ink-400`, `--k-ink-300` on hover) rules. The views' 12 px right padding keeps text clear of the bar.

The Live, Cards, Roster and Settings views have `tabindex="0"`, so the keyboard can scroll them; Team draw and the picker scroll through their focusable buttons.

## Scroll position

`twitch-extension/panel.js`:
- `keepScroll(viewId, render)` saves `scrollTop`, renders and restores it. `loadLive` (every `LIVE_REFRESH_MS` = 60 s, and on an MVP PubSub message) renders through it.
- `renderRoster` saves and restores `#view-roster`'s `scrollTop`.
- A hidden view loses its scroll position, so `showView` remembers the position of the tab views (Live, Cards, Roster) in `state.scrollTops` when they are hidden and restores it when they are shown again. After a change in the bench picker, the Roster tab returns where it was.

## Console setting and testing

- Set the version's **Panel Height** (Version → Asset Hosting) to 500, the largest Twitch allows. The panel still works at smaller heights. `package.sh` prints "Panel Height: 500" after the Asset Hosting paths. See the Prerequisites table in [Twitch Extension](../core/twitch-extension.md).
- `twitch-extension/dev-harness.html` has Panel Height presets (300, 400 and 500 px, and Pop-out) for the viewer frame, which stays 318 px wide.
- Static tests: `backend/tests/test_issue_191_panel_fits_twitch_height.py`. Real rendering at each height is checked by hand in the dev harness.
