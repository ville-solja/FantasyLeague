# Plan: Password Manager Autofill

## Context
Players report that Bitwarden no longer fills the login (#158: "Previously filling out values from bitwarden used to work, but now it does not seem to anymore").

The login popup (`#loginModal` in `frontend/index.html`) has bare inputs:
- no surrounding `<form>`,
- no `name` attributes,
- no `autocomplete` hints (`#loginUsername` type `text`, `#loginPassword` type `password`),
- a plain button with `onclick="login()"`.

Its markup hasn't changed since login was first built (`8950ac0`). What changed is the rest of the page. Commit `e5c8f54` (#117, server-side sessions) added the admin re-login popup (`#reauthModal`) with `#reauthPassword`. That field is the **only** password field in the document marked `autocomplete="current-password"`, and it has no username field next to it. Password managers rank fields by these hints and by their form, so the hidden re-login field now looks more like "the login password" than the real one. Registration, password reset and the profile's change-password fields are also loose inputs without hints, so a manager can't tell a new password from a current one either.

The fix follows the HTML autofill conventions that Bitwarden, 1Password, Chrome and Firefox all use:
- each credential flow is its own `<form>`,
- every field has a `name` and the right `autocomplete` token (`username`, `current-password`, `new-password`, `email`, `one-time-code`),
- submission goes through the form, so managers also offer to save or update passwords.

**Assumptions:**
- The exact trigger can't be reproduced without the reporter's browser and Bitwarden version. The fix targets the structural causes and is checked by hand with Bitwarden in Chrome and Firefox.
- Field ids stay the same, so `app-auth.js`, `app-profile.js` and `app-admin.js` keep reading values by id. Only the submit wiring changes, from `onclick` / Enter-key handlers to the form's `submit` event with `preventDefault()`. No page reloads, and the API is unchanged.
- Steam-only login (#150, milestone S17) will remove most of these forms later. Until then players need working autofill, and the fix is small.
- No backend, API, env var or migration changes.

Resolves GitHub issue #158.

## User Stories

### Password Manager Fills the Login
**User story**
As a player who uses a password manager, I want it to fill my username and password in the login popup so that I can log in without typing them.

**Acceptance criteria**
- `#loginUsername` and `#loginPassword` sit inside one `<form id="loginForm" autocomplete="on">` in `#loginModal`.
- `#loginUsername` has `name="username"`, `autocomplete="username"`, `autocapitalize="none"` and `spellcheck="false"`.
- `#loginPassword` has `name="password"` and `autocomplete="current-password"`.
- The Login button is `type="submit"`. Pressing Enter in either field submits the form once, so the old `onkeydown` Enter handlers are removed.
- The form's submit handler calls `preventDefault()` and then `login()`. The page doesn't reload, and the request is the same `POST /login` as before.
- "Forgot password" and "Create new account" are `type="button"`, so they never submit the login form.
- **Failure path:** a failed login still shows the error in `#loginStatus`, keeps the typed username and password (as today; neither field is cleared on failure), and doesn't reload the page.

### Only the Login Looks Like a Login
**User story**
As a player, I want my password manager to treat each password field correctly so that it fills the login and offers to save new passwords in the right places.

**Acceptance criteria**
- **Registration** (`#registerModal`): one `<form id="registerForm">`. Fields: `#regUsername` with `autocomplete="username"`, `#regEmail` with `type="email"` and `autocomplete="email"`, `#regPassword` with `autocomplete="new-password"`. Create account is `type="submit"`; Back to login is `type="button"`.
- **Password reset** (`#resetPasswordModal`): one `<form>`. Fields:
  - `#resetToken` with `autocomplete="one-time-code"`,
  - `#resetNewPassword` with `autocomplete="new-password"`,
  - a visually hidden, read-only username field with `autocomplete="username"`, so managers store the new password under the right login. It's prefilled from the username entered on the forgot-password step when known, and empty otherwise (for example when the reset link is opened from the email).
- **Profile change password**: one `<form>`. Fields: `#pwCurrent` with `autocomplete="current-password"`, `#pwNew` with `autocomplete="new-password"`, and a visually hidden, read-only username field with `autocomplete="username"` holding the logged-in username.
- **Admin re-login** (`#reauthModal`): one `<form>`. `#reauthPassword` keeps `autocomplete="current-password"` and gains a visually hidden, read-only username field (`autocomplete="username"`, the logged-in username), so it pairs with the same saved login and isn't mistaken for a separate login.
- **Every password input** in `index.html` is inside a `<form>` and has an `autocomplete` value of `current-password` or `new-password`. No password input lacks one. A static test checks this, which is the failure path.
- **Hidden helper fields** are visually hidden with a class (not `display:none`, which some managers ignore). They aren't focusable (`tabindex="-1"`) and are `aria-hidden="true"`, so keyboard and screen-reader users don't meet them.

### No Change for Everyone Else
**User story**
As a player who types my password, I want the login and the other forms to behave exactly as before so that the fix doesn't break anything.

**Acceptance criteria**
- Every form submits through its existing function (`login()`, `register()`, `submitResetPassword()`, `changePassword()`, `submitReauth()`). Each fires once per submit, with no page reload or URL change, and none of them sends a password in the URL.
- The visible layout of the popups and the profile page is unchanged.
- After a successful login, the password field is cleared as today (the username stays, as before). Password managers that watch the submit event get the chance to offer saving or updating.
- **Failure path:** a form submit that fails validation, such as an empty username, shows the same error as today.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/index.html` | Wrap the login, register, reset, change-password and reauth fields in `<form>` elements with `name` and `autocomplete` attributes; submit buttons `type="submit"`, others `type="button"`; hidden username helpers; remove Enter-key `onkeydown` handlers |
| `frontend/app-auth.js` | Submit listeners for `#loginForm`, `#registerForm` and the reset form (`preventDefault()`, then the existing function); prefill the reset form's username |
| `frontend/app-profile.js` | Submit listener for the change-password form; set the hidden username |
| `frontend/app-admin.js` | Submit listener for the reauth form; set the hidden username |
| `frontend/style.css` | `.visually-hidden` helper, if none exists (check first); forms add no margins of their own (`form { margin: 0 }` inside modals) |
| `markdown/features/core/auth.md` | Autofill conventions section |
| `markdown/features/reference/password-manager-autofill.md` | Feature doc (stub at planning) |
| `markdown/ui_description/profile.md` | Change-password form note |
| `backend/tests/test_issue_158_password_manager_autofill.py` | Static checks on `index.html` and the JS wiring |
| `backend/tests/test_issue_85_split_admin_router.py` | Suite-size tripwire bump |

### Step 1 — Login form
```html
<form id="loginForm" autocomplete="on" novalidate>
  <input id="loginUsername" name="username" type="text" autocomplete="username"
         autocapitalize="none" spellcheck="false" placeholder="Username" ... />
  <input id="loginPassword" name="password" type="password" autocomplete="current-password"
         placeholder="Password" ... />
  <button type="submit" ...>Login</button>
  <button type="button" class="secondary" onclick="showForgotPassword()">Forgot password</button>
</form>
```

In `app-auth.js`, wire the form once at load:

```js
document.getElementById("loginForm").addEventListener("submit", e => { e.preventDefault(); login(); });
```

`novalidate` keeps the existing JS validation messages in charge. Keep the ids and styles unchanged.

### Step 2 — Register, reset, change password, reauth
- **Same pattern for each:** a form element, `name` and `autocomplete` on every field, a submit button, and a listener calling the existing function.
- **Hidden username helpers:** `<input class="visually-hidden" type="text" name="username" autocomplete="username" tabindex="-1" aria-hidden="true" readonly>`.
  - **Reset form:** set from the forgot-password username when the user came through that step.
  - **Change-password and reauth forms:** set from `activeUsername` when the form or popup opens.
- **Enter-key handlers:** remove the `onkeydown="if(event.key==='Enter') …"` handlers on those fields, since the form submit now covers Enter.

### Step 3 — Styles
- **Visually hidden helper:** add `.visually-hidden` (clip-based, as `.recap-sr`), unless an equivalent exists.
- **Layout:** make sure `<form>` doesn't change the spacing in the popups or the profile page (`margin: 0`; inherit the width rules).

### Step 4 — Tests and docs
`backend/tests/test_issue_158_password_manager_autofill.py`, as static checks:
- **Login form:**
  - `#loginUsername` and `#loginPassword` are inside `#loginForm`, with the stated `name` and `autocomplete` values,
  - the Login button is `type="submit"`, and Forgot password and Create account are `type="button"`.
- **Every password input:**
  - is inside a `<form>`,
  - has an `autocomplete` of `current-password` or `new-password`,
  - has an `autocomplete="username"` field in the same form.
- **Field tokens:**
  - registration: `username`, `email`, `new-password`,
  - reset: `one-time-code`, `new-password`,
  - profile: `current-password`, `new-password`.
- **Hidden helpers:** `class="visually-hidden"`, `tabindex="-1"`, `aria-hidden="true"`, `readonly`.
- **JS wiring:**
  - each form has a `submit` listener calling `preventDefault()` and the existing function,
  - no Enter-key `onkeydown` handler remains on those fields,
  - no `<form>` has `method="get"` or an `action` that would put a password in a URL.

Then update `core/auth.md`, `ui_description/profile.md`, the stub, the stories, and bump the suite-size tripwire.

## Verification
- **Bitwarden in Chrome and Firefox, on the logged-out page:**
  - open Login: the inline menu or the autofill shortcut fills username and password into the login popup, not the hidden re-login field,
  - log in with the filled values.
- **Saving new passwords:** register a new account and check that Bitwarden offers to save it. Change the password on Profile and check that it offers to update the saved login.
- **Re-login popup:** as an admin, trigger a re-login (for example, start a database backup). Bitwarden fills the password into it.
- **Without a manager:** typing and pressing Enter submits each form once, errors show as before, there's no page reload, and the URL never gains a query string.
- **Chrome DevTools:** the "Password field is not contained in a form" warnings are gone.
- `cd backend && python3 -m pytest tests/ -q` passes.
