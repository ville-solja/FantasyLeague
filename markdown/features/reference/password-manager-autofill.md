# Password Manager Autofill

Makes the app's password forms recognisable to password managers (Bitwarden, 1Password, browser managers), so they fill the login and offer to save or update passwords in the right places. For every player who logs in with a username and password. Resolves issue #158.

*(see `markdown/plans/plan-issue-158-password-manager-autofill.md`; related: `core/auth.md`)*

---

## Why autofill broke

The login popup's fields had no `<form>`, `name` or `autocomplete` hints. Since #117 the page also contains the admin re-login popup (`#reauthModal`). Its `#reauthPassword` was the only field marked `autocomplete="current-password"`, and it had no username next to it. Password managers rank fields by these hints, so the hidden re-login field looked more like the login password than the real one.

## Form conventions

All five forms are in `frontend/index.html`. Field ids are unchanged, so the JS still reads values by id.

| Form | Fields and `autocomplete` tokens | Submit runs |
|---|---|---|
| Login (`#loginForm` in `#loginModal`, `autocomplete="on"`) | `#loginUsername` `username` (`autocapitalize="none"`, `spellcheck="false"`); `#loginPassword` `current-password` | `login()` |
| Registration (`#registerForm` in `#registerModal`) | `#regUsername` `username` (`autocapitalize="none"`, `spellcheck="false"`); `#regEmail` `email`; `#regPassword` `new-password` | `register()` |
| Password reset (`#resetPasswordForm` in `#resetPasswordModal`) | helper `#resetUsername` `username`; `#resetToken` `one-time-code` (`autocapitalize="none"`, `spellcheck="false"`); `#resetNewPassword` `new-password` | `submitResetPassword()` |
| Profile change password (`#changePasswordForm` on the Profile tab) | helper `#pwUsername` `username`; `#pwCurrent` `current-password`; `#pwNew` `new-password` | `changePassword()` |
| Admin re-login (the **Confirm your password** popup: `#reauthForm` in `#reauthModal`) | helper `#reauthUsername` `username`; `#reauthPassword` `current-password` | `submitReauth()` |

- **Forms:** every form is `method="post"` with no `action`, and `novalidate`, so the existing JS validation messages stay in charge (the browser's own bubbles would otherwise block `type="email"`). If the JS listener ever failed to attach, a native submit would POST to the page, never put the password in a URL.
- **Buttons:** each form has one `type="submit"` button with no `onclick`. Every other button inside a form (Forgot password, Create new account, Back to login, Cancel) is `type="button"`, so it never submits.
- **Submission:** each form is wired once at script load with `addEventListener("submit", e => { e.preventDefault(); fn(); })`: `#loginForm`, `#registerForm` and `#resetPasswordForm` in `app-auth.js`, `#changePasswordForm` in `app-profile.js`, `#reauthForm` in `app-admin.js`. Enter in a field submits the form, so the old `onkeydown` Enter handlers were removed from these five forms (the forgot-password popup keeps its own Enter handler) and each function runs once per submit. The `oninput` handlers on the registration fields are kept.
- **Unchanged behaviour:** requests, validation messages and field clearing are as before. A failed login keeps both fields; a successful one hides the popup and clears the password.

## Username helpers

Lone password fields are paired with a hidden username so a manager stores and updates the password under the right login, and doesn't treat the re-login field as a separate login:

```html
<input class="visually-hidden" type="text" name="username" autocomplete="username" tabindex="-1" aria-hidden="true" readonly />
```

- `#resetUsername` is set in `showResetPassword()` from `#forgotUsername` if it holds a value, otherwise from the username of the last successful `submitForgotPassword()` (which clears `#forgotUsername`). It is empty when the reset link is opened from the email.
- `#pwUsername` is set to `activeUsername` in `loadProfile()` and after a username change in `saveUsername()`.
- `#reauthUsername` is set to `activeUsername` in `_promptReauth()` before the popup opens.

`.visually-hidden` in `style.css` is clip-based (1 px, `position: absolute`, `clip` and `clip-path`), not `display: none`, which some managers ignore. The modal focus trap in `app-init.js` (`_getFocusableIn`) skips inputs with `tabindex="-1"`, so focus never lands on a helper. `.modal form, #changePasswordForm { margin: 0; }` keeps the layout unchanged.

## Tests

`backend/tests/test_issue_158_password_manager_autofill.py` parses `index.html` with `html.parser` and checks the form structure, tokens, helpers, button types, submit wiring and CSS. Checking that Bitwarden actually fills the forms is manual (see the plan's Verification section).

No endpoint, env var or database change.
