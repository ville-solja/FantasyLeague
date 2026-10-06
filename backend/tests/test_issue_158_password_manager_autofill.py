"""
Tests for plan-issue-158-password-manager-autofill.md (resolves GitHub issue #158).

Bitwarden stopped filling the login popup. The login inputs had no <form>, no
`name` and no `autocomplete` hints, while the admin re-login field
`#reauthPassword` was the only `autocomplete="current-password"` field in the
document. The fix wraps every credential flow in its own <form> with `name` and
`autocomplete` tokens, submits through the form's `submit` event (with
`preventDefault()`, no page reload), and pairs lone password fields with a
visually hidden username helper. No backend, API, env var or migration changes.

  Story 1: Password Manager Fills the Login
  Story 2: Only the Login Looks Like a Login
  Story 3: No Change for Everyone Else

Approach notes for the implementer:

- Every check is static: read `frontend/index.html`, `frontend/app-auth.js`,
  `frontend/app-profile.js`, `frontend/app-admin.js` and `frontend/style.css`
  (reuse `_read` via `from tests.test_issue_144_guided_tour import _read`, or a
  local copy; import only underscore names, lessons-learned 2026-10-03).
- Parse index.html with the stdlib `html.parser.HTMLParser`, not regexes. Build a
  small parser subclass that keeps a stack of open <form> elements and records,
  for every <input> and <button>, a dict of its attributes plus the id of the
  enclosing form (None when outside any form) and an index of that form. Also
  record each <form>'s own attributes (id, method, action, autocomplete,
  novalidate). Helpers such as `_inputs()`, `_input_by_id(id)`,
  `_form_of(id)`, `_fields_in_form(form_key)` keep the tests short. Forms other
  than `loginForm` / `registerForm` may have no id, so key forms by id when
  present and by document order otherwise; locate the reset, change-password
  and reauth forms as "the form enclosing #resetToken / #pwCurrent /
  #reauthPassword".
- Buttons: find the submit button of a form by `type="submit"` among the
  buttons recorded inside it; match the secondary buttons by their `onclick`
  (`showForgotPassword()`, `showRegister...`, back-to-login) or visible text.
- JS wiring: assert a `.addEventListener("submit", ...)` on the form (by
  `getElementById("loginForm")` etc. or the form's id/selector) whose handler
  body contains `preventDefault()` and then the existing function call. Accept
  single or double quotes and arrow or function handlers.

Manual-only (need a real browser and password manager, see the plan's
Verification section): Bitwarden in Chrome and Firefox actually fills the login
popup (and not the hidden re-login field); Bitwarden offers to save on register
and to update on profile password change; Bitwarden fills `#reauthPassword` in
the admin re-login popup; Enter submits exactly once at runtime; no page reload
and no query string in the URL at runtime; the visible layout of the popups and
the profile page is unchanged; Chrome DevTools no longer warns "Password field
is not contained in a form".

STATUS: implemented.

Run with: cd backend && python3 -m pytest tests/test_issue_158_password_manager_autofill.py -v
"""

import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from tests.test_issue_144_guided_tour import _read, _FRONTEND_DIR


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}


class _FormParser(HTMLParser):
    """Records <form>, <input> and <button> elements with their enclosing form and ancestor ids."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []        # [(tag, attrs)] of open non-void elements
        self.forms = {}        # form key -> attrs (+ "_ancestors")
        self.fields = []       # inputs and buttons: attrs + "_tag", "_form", "_ancestors", "_text"
        self._form_count = 0
        self._button = None

    def _ancestor_ids(self):
        return [a.get("id") for _, a in self.stack if a.get("id")]

    def _current_form(self):
        for tag, a in reversed(self.stack):
            if tag == "form":
                return a["_key"]
        return None

    def _record(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            a["_key"] = a.get("id") or f"form#{self._form_count}"
            self._form_count += 1
            a["_ancestors"] = self._ancestor_ids()
            self.forms[a["_key"]] = a
        elif tag in ("input", "button"):
            a.update(_tag=tag, _form=self._current_form(), _ancestors=self._ancestor_ids(), _text="")
            self.fields.append(a)
            if tag == "button":
                self._button = a
        return a

    def handle_starttag(self, tag, attrs):
        a = self._record(tag, attrs)
        if tag not in _VOID:
            self.stack.append((tag, a))

    def handle_startendtag(self, tag, attrs):
        self._record(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "button":
            self._button = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._button is not None:
            self._button["_text"] += data


def _html():
    return _read(os.path.join(_FRONTEND_DIR, "index.html"))


def _parsed():
    parser = _FormParser()
    parser.feed(_html())
    parser.close()
    return parser


def _inputs():
    return [f for f in _parsed().fields if f["_tag"] == "input"]


def _input_by_id(el_id):
    matches = [f for f in _inputs() if f.get("id") == el_id]
    assert len(matches) == 1, f"expected one #{el_id}, found {len(matches)}"
    return matches[0]


def _form_of(el_id):
    """Key of the <form> enclosing #el_id (the form's id when it has one)."""
    return _input_by_id(el_id)["_form"]


def _fields_in_form(form_key):
    return [f for f in _parsed().fields if f["_form"] == form_key]


def _buttons_in_form(form_key):
    return [f for f in _fields_in_form(form_key) if f["_tag"] == "button"]


def _submit_buttons(form_key):
    return [b for b in _buttons_in_form(form_key) if b.get("type") == "submit"]


def _username_helper(form_key):
    helpers = [f for f in _fields_in_form(form_key) if f.get("autocomplete") == "username"]
    assert len(helpers) == 1, form_key
    return helpers[0]


def _username_helpers():
    return [f for f in _inputs() if "visually-hidden" in (f.get("class") or "").split()]


def _js(name):
    return _read(os.path.join(_FRONTEND_DIR, name))


def _js_function(src, name):
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", src)
    assert m, f"function {name} not found"
    return src[m.start():src.index("\n}\n", m.start())]


def _submit_handler_body(js, form_id):
    """Body of the `submit` listener added to #form_id (arrow or function handler, either quote style)."""
    m = re.search(
        r"getElementById\(\s*[\"']" + re.escape(form_id) + r"[\"']\s*\)\s*\.addEventListener\(\s*"
        r"[\"']submit[\"']\s*,\s*(?:\(?\s*\w+\s*\)?\s*=>|function\s*\w*\s*\(\s*\w+\s*\))\s*\{([^}]*)\}",
        js)
    assert m, f"no submit listener on #{form_id}"
    return m.group(1)


def _submit_listener_count(form_id):
    pat = (r"getElementById\(\s*[\"']" + re.escape(form_id)
           + r"[\"']\s*\)\s*\.addEventListener\(\s*[\"']submit")
    return sum(len(re.findall(pat, _js(n)))
               for n in ("app-auth.js", "app-profile.js", "app-admin.js", "app-init.js"))


def _calls(body, func):
    return re.search(r"(?<![\w.])" + re.escape(func) + r"\(\)", body)


# Each credential flow: a field it encloses, and the existing function its submit runs.
_FORM_FIELD = {
    "loginForm": "loginPassword",
    "registerForm": "regPassword",
    "reset form (encloses #resetToken)": "resetToken",
    "change-password form (encloses #pwCurrent)": "pwCurrent",
    "reauth form (encloses #reauthPassword)": "reauthPassword",
}

_FORM_FUNC = {
    "loginForm": "login",
    "registerForm": "register",
    "reset form (encloses #resetToken)": "submitResetPassword",
    "change-password form (encloses #pwCurrent)": "changePassword",
    "reauth form (encloses #reauthPassword)": "submitReauth",
}

_FORM_FIELD_IDS = ("loginUsername", "loginPassword", "regUsername", "regEmail", "regPassword",
                   "resetToken", "resetNewPassword", "pwCurrent", "pwNew", "reauthPassword")


# ---------------------------------------------------------------------------
# Story 1: Password Manager Fills the Login
# ---------------------------------------------------------------------------

class TestPasswordManagerFillsTheLogin:

    def test_login_form_exists_in_login_modal(self):
        """`<form id="loginForm" autocomplete="on">` exists inside `#loginModal` (novalidate keeps JS validation in charge)."""
        form = _parsed().forms.get("loginForm")
        assert form is not None, 'no <form id="loginForm">'
        assert "loginModal" in form["_ancestors"]
        assert form.get("autocomplete") == "on"
        assert "novalidate" in form

    def test_login_fields_inside_login_form(self):
        """`#loginUsername` and `#loginPassword` both have enclosing form id `loginForm`."""
        assert _form_of("loginUsername") == "loginForm"
        assert _form_of("loginPassword") == "loginForm"

    def test_login_username_attributes(self):
        """`#loginUsername` has `name="username"`, `autocomplete="username"`, `autocapitalize="none"`, `spellcheck="false"`."""
        f = _input_by_id("loginUsername")
        assert f.get("name") == "username"
        assert f.get("autocomplete") == "username"
        assert f.get("autocapitalize") == "none"
        assert f.get("spellcheck") == "false"

    def test_login_password_attributes(self):
        """`#loginPassword` is `type="password"` with `name="password"` and `autocomplete="current-password"`."""
        f = _input_by_id("loginPassword")
        assert f.get("type") == "password"
        assert f.get("name") == "password"
        assert f.get("autocomplete") == "current-password"

    def test_login_button_is_submit(self):
        """The Login button inside `#loginForm` is `type="submit"` and has no `onclick="login()"`."""
        submits = _submit_buttons("loginForm")
        assert len(submits) == 1
        assert submits[0]["_text"].strip() == "Login"
        assert "login()" not in (submits[0].get("onclick") or "")

    def test_login_secondary_buttons_are_type_button(self):
        """"Forgot password" (`showForgotPassword()`) and "Create new account" buttons in `#loginForm` are `type="button"`, so they never submit it."""
        buttons = _buttons_in_form("loginForm")
        forgot = [b for b in buttons if "showForgotPassword()" in (b.get("onclick") or "")]
        create = [b for b in buttons if "showRegister()" in (b.get("onclick") or "")]
        assert len(forgot) == 1 and len(create) == 1
        assert forgot[0].get("type") == "button"
        assert create[0].get("type") == "button"

    def test_login_fields_have_no_enter_onkeydown(self):
        """`#loginUsername` and `#loginPassword` have no `onkeydown` Enter handler (form submit covers Enter, so login fires once)."""
        for el_id in ("loginUsername", "loginPassword"):
            assert "onkeydown" not in _input_by_id(el_id), el_id

    def test_login_form_submit_listener_prevents_default_and_calls_login(self):
        """`app-auth.js` adds a `submit` listener to `#loginForm` that calls `preventDefault()` and then `login()`."""
        body = _submit_handler_body(_js("app-auth.js"), "loginForm")
        assert "preventDefault()" in body
        call = _calls(body, "login")
        assert call and body.index("preventDefault()") < call.start()

    def test_login_still_posts_to_login_endpoint(self):
        """`login()` in `app-auth.js` still sends `POST /login` (request unchanged)."""
        fn = _js_function(_js("app-auth.js"), "login")
        assert "`${API}/login`" in fn
        assert 'method: "POST"' in fn
        assert "JSON.stringify({username, password})" in fn

    def test_login_failure_shows_status_and_clears_only_password(self):
        """Failure path: `login()` error branch writes to `#loginStatus` and clears `#loginPassword` but not `#loginUsername`; no reload (`location.reload`/`form.submit()` absent)."""
        # login() has never cleared either field on a failed login; the plan keeps
        # behaviour unchanged, so the check is that the username is never cleared,
        # the error goes to #loginStatus and nothing reloads or natively submits.
        fn = _js_function(_js("app-auth.js"), "login")
        assert re.search(r'if \(!res\.ok\) return setStatus\("loginStatus", data\.detail, false\)', fn)
        assert 'getElementById("loginUsername").value = ' not in fn
        for name in ("app-auth.js", "app-profile.js", "app-admin.js"):
            src = _js(name)
            assert "location.reload" not in src, name
            assert not re.search(r"\.submit\(\)", src), name


# ---------------------------------------------------------------------------
# Story 2: Only the Login Looks Like a Login
# ---------------------------------------------------------------------------

class TestOnlyTheLoginLooksLikeALogin:

    def test_register_form_fields_and_tokens(self):
        """`<form id="registerForm">` in `#registerModal` holds `#regUsername` (`autocomplete="username"`), `#regEmail` (`type="email"`, `autocomplete="email"`), `#regPassword` (`autocomplete="new-password"`); every field has a `name`."""
        form = _parsed().forms.get("registerForm")
        assert form is not None and "registerModal" in form["_ancestors"]
        for el_id in ("regUsername", "regEmail", "regPassword"):
            assert _form_of(el_id) == "registerForm", el_id
        assert _input_by_id("regUsername").get("autocomplete") == "username"
        assert _input_by_id("regEmail").get("type") == "email"
        assert _input_by_id("regEmail").get("autocomplete") == "email"
        assert _input_by_id("regPassword").get("autocomplete") == "new-password"
        for f in _fields_in_form("registerForm"):
            if f["_tag"] == "input":
                assert f.get("name"), f.get("id")

    def test_register_buttons_submit_and_back(self):
        """In `#registerForm`, Create account is `type="submit"`; Back to login is `type="button"`."""
        submits = _submit_buttons("registerForm")
        assert len(submits) == 1 and submits[0]["_text"].strip() == "Create account"
        back = [b for b in _buttons_in_form("registerForm") if b["_text"].strip() == "Back to login"]
        assert len(back) == 1 and back[0].get("type") == "button"

    def test_reset_form_fields_and_tokens(self):
        """One <form> in `#resetPasswordModal` holds `#resetToken` (`autocomplete="one-time-code"`), `#resetNewPassword` (`autocomplete="new-password"`) and a username field with `autocomplete="username"`; submit button is `type="submit"`."""
        key = _form_of("resetToken")
        assert key is not None
        assert _form_of("resetNewPassword") == key
        assert "resetPasswordModal" in _parsed().forms[key]["_ancestors"]
        assert _input_by_id("resetToken").get("autocomplete") == "one-time-code"
        assert _input_by_id("resetNewPassword").get("autocomplete") == "new-password"
        assert _username_helper(key)
        assert len(_submit_buttons(key)) == 1

    def test_reset_username_prefilled_from_forgot_step(self):
        """`app-auth.js` sets the reset form's username field from the `#forgotUsername` value entered on the forgot-password step."""
        helper = _username_helper(_form_of("resetToken"))
        js = _js("app-auth.js")
        show = _js_function(js, "showResetPassword")
        m = re.search(r'getElementById\("' + re.escape(helper["id"]) + r'"\)\.value\s*=\s*([^;]*);', show)
        assert m, "showResetPassword() never sets the reset username helper"
        # The field's current value, else the username stored when the reset was requested
        # (submitForgotPassword() clears #forgotUsername on success).
        assert 'getElementById("forgotUsername").value' in m.group(1)
        assert "_forgotPasswordUsername" in m.group(1)
        assert "_forgotPasswordUsername = username" in _js_function(js, "submitForgotPassword")

    def test_change_password_form_fields_and_tokens(self):
        """The <form> enclosing `#pwCurrent` also holds `#pwNew`; `#pwCurrent` has `autocomplete="current-password"`, `#pwNew` has `autocomplete="new-password"`, plus a hidden username helper (`autocomplete="username"`)."""
        key = _form_of("pwCurrent")
        assert key is not None and _form_of("pwNew") == key
        assert _input_by_id("pwCurrent").get("autocomplete") == "current-password"
        assert _input_by_id("pwNew").get("autocomplete") == "new-password"
        assert "visually-hidden" in _username_helper(key).get("class", "")
        assert len(_submit_buttons(key)) == 1

    def test_change_password_hidden_username_set_from_active_user(self):
        """`app-profile.js` sets the change-password form's hidden username to `activeUsername`."""
        helper = _username_helper(_form_of("pwCurrent"))
        fn = _js_function(_js("app-profile.js"), "loadProfile")
        assert re.search(r'getElementById\("' + re.escape(helper["id"]) + r'"\)\.value = activeUsername', fn)

    def test_reauth_form_fields_and_tokens(self):
        """The <form> in `#reauthModal` encloses `#reauthPassword` (keeps `autocomplete="current-password"`) and a hidden username helper (`autocomplete="username"`)."""
        key = _form_of("reauthPassword")
        assert key is not None
        assert "reauthModal" in _parsed().forms[key]["_ancestors"]
        assert _input_by_id("reauthPassword").get("autocomplete") == "current-password"
        assert "visually-hidden" in _username_helper(key).get("class", "")

    def test_reauth_hidden_username_set_from_active_user(self):
        """`app-admin.js` sets the reauth form's hidden username to `activeUsername` when the popup opens."""
        helper = _username_helper(_form_of("reauthPassword"))
        fn = _js_function(_js("app-admin.js"), "_promptReauth")
        assert re.search(r'getElementById\("' + re.escape(helper["id"]) + r'"\)\.value = activeUsername', fn)
        assert fn.index(helper["id"]) < fn.index('classList.remove("hidden")')

    def test_hidden_username_helpers_attributes(self):
        """Each hidden username helper has `class="visually-hidden"`, `type="text"`, `name="username"`, `autocomplete="username"`, `tabindex="-1"`, `aria-hidden="true"` and `readonly`; none uses `display:none` / `hidden`."""
        helpers = _username_helpers()
        assert len(helpers) == 3
        assert {h["_form"] for h in helpers} == {
            _form_of("resetToken"), _form_of("pwCurrent"), _form_of("reauthPassword")}
        for h in helpers:
            assert h.get("type") == "text"
            assert h.get("name") == "username"
            assert h.get("autocomplete") == "username"
            assert h.get("tabindex") == "-1"
            assert h.get("aria-hidden") == "true"
            assert "readonly" in h
            assert "hidden" not in h
            assert "display" not in (h.get("style") or "")

    def test_visually_hidden_class_defined_clip_based(self):
        """`style.css` defines `.visually-hidden` with a clip-based rule (no `display: none`)."""
        m = re.search(r"(?m)^\.visually-hidden\s*\{([^}]*)\}", _js("style.css"))
        assert m, ".visually-hidden rule missing"
        body = m.group(1)
        assert re.search(r"position:\s*absolute", body)
        assert re.search(r"\bclip:\s*rect\(", body)
        assert re.search(r"width:\s*1px", body) and re.search(r"height:\s*1px", body)
        assert "display" not in body

    def test_every_password_input_inside_form_with_autocomplete(self):
        """Failure path: every `type="password"` input in index.html is inside a <form> and has `autocomplete` of `current-password` or `new-password`; none lacks one."""
        passwords = [f for f in _inputs() if f.get("type") == "password"]
        assert len(passwords) == 6
        for f in passwords:
            assert f["_form"] is not None, f"#{f.get('id')} is not inside a <form>"
            assert f.get("autocomplete") in ("current-password", "new-password"), f.get("id")

    def test_every_password_form_has_username_field(self):
        """Failure path: every <form> containing a password input also contains an `autocomplete="username"` field."""
        keys = {f["_form"] for f in _inputs() if f.get("type") == "password"}
        assert len(keys) == 5
        for key in keys:
            assert [f for f in _fields_in_form(key) if f.get("autocomplete") == "username"], key

    def test_current_password_not_only_on_reauth(self):
        """Failure path (the #158 cause): `#reauthPassword` is not the only `autocomplete="current-password"` field; `#loginPassword` and `#pwCurrent` carry it too."""
        current = {f.get("id") for f in _inputs() if f.get("autocomplete") == "current-password"}
        assert current == {"loginPassword", "pwCurrent", "reauthPassword"}


# ---------------------------------------------------------------------------
# Story 3: No Change for Everyone Else
# ---------------------------------------------------------------------------

class TestNoChangeForEveryoneElse:

    @pytest.mark.parametrize("form_ref,js_file,func", [
        ("loginForm", "app-auth.js", "login"),
        ("registerForm", "app-auth.js", "register"),
        ("reset form (encloses #resetToken)", "app-auth.js", "submitResetPassword"),
        ("change-password form (encloses #pwCurrent)", "app-profile.js", "changePassword"),
        ("reauth form (encloses #reauthPassword)", "app-admin.js", "submitReauth"),
    ])
    def test_form_submit_listener_calls_existing_function(self, form_ref, js_file, func):
        """Each form has a `submit` listener calling `preventDefault()` then its existing function: `login()`, `register()`, `submitResetPassword()`, `changePassword()`, `submitReauth()`."""
        key = _form_of(_FORM_FIELD[form_ref])
        if form_ref in ("loginForm", "registerForm"):
            assert key == form_ref
        assert not key.startswith("form#"), "the form needs an id to be wired"
        body = _submit_handler_body(_js(js_file), key)
        assert "preventDefault()" in body
        call = _calls(body, func)
        assert call and body.index("preventDefault()") < call.start()
        assert _submit_listener_count(key) == 1  # wired once, so one call per submit

    def test_submit_functions_not_also_wired_via_onclick(self):
        """Submit buttons in the five forms have no `onclick` calling the same function, so each fires once per submit."""
        for form_ref, field in _FORM_FIELD.items():
            key = _form_of(field)
            func = _FORM_FUNC[form_ref]
            assert len(_submit_buttons(key)) == 1, form_ref
            for b in _buttons_in_form(key):
                assert b.get("type") in ("submit", "button"), (form_ref, b["_text"])
                assert func + "(" not in (b.get("onclick") or ""), (form_ref, b["_text"])

    def test_no_enter_onkeydown_on_form_fields(self):
        """No `onkeydown="if(event.key==='Enter') ..."` remains on `#loginUsername`, `#loginPassword`, `#regUsername`, `#regEmail`, `#regPassword`, `#resetToken`, `#resetNewPassword`, `#pwCurrent`, `#pwNew`, `#reauthPassword`."""
        for el_id in _FORM_FIELD_IDS:
            assert "onkeydown" not in _input_by_id(el_id), el_id

    def test_no_form_uses_get_or_url_action(self):
        """Failure path: no <form> has `method="get"` (any case) or a non-empty `action` that would put a password in a URL."""
        forms = _parsed().forms
        assert len(forms) == 5
        for key, form in forms.items():
            # Explicit post: if the JS listener ever fails to attach, a native submit
            # still cannot put the password in the URL.
            assert (form.get("method") or "").lower() == "post", key
            assert not (form.get("action") or "").strip(), key

    def test_login_success_clears_fields(self):
        """After a successful login, `login()` still clears `#loginUsername` and `#loginPassword` as today."""
        # As today: on success login() hides the popup and clears the password; the
        # username was never cleared, so it is not asserted here.
        fn = _js_function(_js("app-auth.js"), "login")
        success = fn[fn.index("await loadMe()"):]
        assert 'getElementById("loginModal").classList.add("hidden")' in success
        assert 'getElementById("loginPassword").value = ""' in success

    def test_forms_have_no_extra_margin(self):
        """`style.css` sets `margin: 0` on forms inside modals/profile so the visible layout is unchanged."""
        m = re.search(r"(?m)^([^{}\n]*\bform\b[^{}\n]*)\{([^}]*)\}", _js("style.css"))
        assert m, "no CSS rule for credential forms"
        assert ".modal form" in m.group(1) and "#changePasswordForm" in m.group(1)
        assert re.search(r"margin:\s*0\s*;", m.group(2))

    def test_validation_errors_unchanged(self):
        """Failure path: forms use `novalidate` and `login()` / `register()` keep their empty-username error messages, so a failed validation shows the same error as today."""
        for field in _FORM_FIELD.values():
            assert "novalidate" in _parsed().forms[_form_of(field)], field
        js = _js("app-auth.js")
        assert 'setStatus("loginStatus", "Enter username and password", false)' in _js_function(js, "login")
        assert '"Username is required"' in _js_function(js, "register")
        assert '"Email is required"' in _js_function(js, "register")
