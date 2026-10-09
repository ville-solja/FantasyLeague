function applyAuthState() {
  const loggedIn = !!activeUserId;

  const userLabel = document.getElementById("headerUserLabel");
  userLabel.textContent    = loggedIn ? activeUsername : "";
  userLabel.style.display  = loggedIn ? "" : "none";
  document.getElementById("headerLoginBtn").style.display  = loggedIn ? "none" : "";
  document.getElementById("headerLogoutBtn").style.display = loggedIn ? "" : "none";

  document.getElementById("tab-btn-team").style.display  = loggedIn ? "" : "none";
  document.getElementById("tab-btn-admin").style.display = (loggedIn && activeIsAdmin) ? "" : "none";
  document.getElementById("weeklyReportBtn").style.display = loggedIn ? "" : "none";

  const tokenEl = document.getElementById("tokenBalance");
  if (tokenEl) tokenEl.style.display = loggedIn ? "flex" : "none";

  if (!loggedIn) switchTab("leaderboard");
}

// ---------------------------------------------------------------------------
// Steam sign-in (issue #150). Sign in, Link and re-auth are full-page navigations
// to GET /auth/steam/start, which sends the browser to steamcommunity.com; Steam
// returns to /auth/steam/callback, which redirects back here with
// /#<tab>?steam=<key> (handleSteamReturn). Never a pop-up or an embedded frame.
// ---------------------------------------------------------------------------

/** Pure: which Steam elements show for a login method and the /me flags (null when
 *  logged out). Tested under Node by tests/test_issue_150_steam_login.py. */
function steamUiState(loginMethod, me) {
  const steam = loginMethod === "both" || loginMethod === "steam_signup";
  const loggedIn = !!me;
  return {
    steamSignIn: steam && !loggedIn,
    passwordRegistration: loginMethod !== "steam_signup",
    steamSignupNotice: loginMethod === "steam_signup",
    profileSteamPanel: steam && loggedIn,
    linkSteam: steam && loggedIn && !me.steam_linked && !me.is_demo,
    unlinkSteam: steam && loggedIn && !!me.steam_linked && !!me.has_password,
    linkReminder: loginMethod === "steam_signup" && loggedIn && !!me.has_password && !me.steam_linked,
  };
}

function applyLoginMode() {
  const ui = steamUiState(_loginMethod, null);
  const show = (id, on) => { const el = document.getElementById(id); if (el) el.style.display = on ? "" : "none"; };
  show("steamLoginBlock", ui.steamSignIn);
  show("createAccountLink", ui.passwordRegistration);
  show("steamSignupNotice", ui.steamSignupNotice);
}

function startSteamLogin() {
  window.location.href = `${API}/auth/steam/start?purpose=login`;
}

const _STEAM_RETURN_MESSAGES = {
  failed:        ["Steam sign-in did not complete. Nothing was changed. Try again.", false],
  cancelled:     ["Steam sign-in was cancelled. Nothing was changed.", false],
  unavailable:   ["Steam sign-in is unavailable right now. Try again later, or sign in with your password.", false],
  login_required:["Log in to Kana Cards first.", false],
  no_session:    ["Log in to Kana Cards first, then try again.", false],
  linked:        ["Steam linked. Your Dota player id is now verified.", true],
  in_use:        ["This Steam account is linked to another Kana Cards account", false],
  unlink_first:  ["Unlink your current Steam account first", false],
  not_allowed:   ["Demo accounts can't link Steam.", false],
  not_linked:    ["This account has no Steam link to confirm with.", false],
  reauth_ok:     ["Confirmed with Steam. Repeat the action to continue.", true],
  reauth_failed: ["That Steam account is not the one linked to this account. Nothing was confirmed.", false],
};

// Actions a Steam confirmation may resume (set by _promptReauth's caller before the
// round trip). Anything else falls back to "Repeat the action to continue".
const _REAUTH_RESUMABLE = { connectTwitch: () => connectTwitch() };

function _takeReauthResume() {
  let action = null;
  try {
    action = sessionStorage.getItem("reauthResume");
    sessionStorage.removeItem("reauthResume");
  } catch (e) { /* storage blocked */ }
  return _REAUTH_RESUMABLE[action] || null;
}

/** Reads /#<tab>?steam=<key> left by the Steam redirects, strips it from the address
 *  bar and shows the outcome. Returns true when handled. */
function handleSteamReturn() {
  const match = (window.location.hash || "").match(/^#(login|welcome|profile|admin)\?(.*)$/);
  if (!match) return false;
  const key = new URLSearchParams(match[2]).get("steam");
  if (!key) return false;
  history.replaceState(null, "", window.location.pathname);
  const [, tab] = match;
  const msg = _STEAM_RETURN_MESSAGES[key] || _STEAM_RETURN_MESSAGES.failed;
  const resume = _takeReauthResume();
  if (tab === "welcome") {
    showSteamSignup();
    return true;
  }
  if (tab === "login" || !activeUserId) {
    showLogin();
    setStatus("loginStatus", msg[0], msg[1]);
    return true;
  }
  if (tab === "admin" && activeIsAdmin) {
    switchTab("admin");
    setStatus("adminSteamStatus", msg[0], msg[1]);
    return true;
  }
  switchTab("profile");
  if (key === "reauth_ok" && resume) {
    setStatus("twitchStatus", "Confirmed with Steam. Continuing to Twitch…");
    resume();
    return true;
  }
  if (key === "reauth_required") {
    _promptReauth().then(ok => {
      if (ok) linkSteam();
      else setStatus("steamStatus", "Confirm your password to link Steam.", false);
    });
    return true;
  }
  setStatus("steamStatus", msg[0], msg[1]);
  return true;
}

function showSteamSignup() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("steamSignupStatus").textContent = "";
  document.getElementById("steamSignupModal").classList.remove("hidden");
}

function closeSteamSignup() {
  document.getElementById("steamSignupModal").classList.add("hidden");
}

async function submitSteamSignup() {
  const username = document.getElementById("steamSignupUsername").value.trim();
  if (!username) return setStatus("steamSignupStatus", "Choose a display name", false);
  try {
    const res = await fetch(`${API}/auth/steam/signup`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username})
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      let detail = data.detail;
      if (Array.isArray(detail)) detail = detail.map(err => err.msg).join(". ");
      if (detail === "signup_expired") detail = "This sign-up has expired. Sign in with Steam again.";
      return setStatus("steamSignupStatus", detail || "Could not create the account", false);
    }
    closeSteamSignup();
    document.getElementById("steamSignupUsername").value = "";
    await loadMe();
    await claimTokenEvents();
    checkNotifications();
    applyAuthState();
    switchTab("team");
    loadDeck();
  } catch (e) {
    setStatus("steamSignupStatus", e.message, false);
  }
}

function showLogin() {
  document.getElementById("registerModal").classList.add("hidden");
  document.getElementById("forgotModal").classList.add("hidden");
  document.getElementById("resetPasswordModal").classList.add("hidden");
  document.getElementById("loginModal").classList.remove("hidden");
  document.getElementById("loginStatus").textContent = "";
}

// Username from the forgot-password step, so the reset form's hidden username
// field lets password managers save the new password under the right login.
let _forgotPasswordUsername = "";

function showForgotPassword() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("resetPasswordModal").classList.add("hidden");
  document.getElementById("forgotModal").classList.remove("hidden");
  document.getElementById("forgotStatus").textContent = "";
  document.getElementById("forgotUsername").value = "";
}

async function submitForgotPassword() {
  const username = document.getElementById("forgotUsername").value.trim();
  if (!username) return setStatus("forgotStatus", "Enter your username", false);
  try {
    const res = await fetch(`${API}/forgot-password`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username})
    });
    if (res.ok) {
      _forgotPasswordUsername = username;
      setStatus("forgotStatus", "If an account with that username exists, a password reset link/code has been sent to its registered email. Your current password stays valid until you complete the reset.");
      document.getElementById("forgotUsername").value = "";
    } else {
      const data = await res.json();
      setStatus("forgotStatus", data.detail, false);
    }
  } catch (e) {
    setStatus("forgotStatus", e.message, false);
  }
}

function showResetPassword(prefillToken) {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("forgotModal").classList.add("hidden");
  document.getElementById("resetPasswordModal").classList.remove("hidden");
  document.getElementById("resetPasswordStatus").textContent = "";
  document.getElementById("resetUsername").value =
    document.getElementById("forgotUsername").value.trim() || _forgotPasswordUsername;
  document.getElementById("resetToken").value = prefillToken || "";
  document.getElementById("resetNewPassword").value = "";
}

async function submitResetPassword() {
  const token = document.getElementById("resetToken").value.trim();
  const new_password = document.getElementById("resetNewPassword").value;
  if (!token) return setStatus("resetPasswordStatus", "Enter your reset code", false);
  if (!new_password || new_password.length < 6) {
    return setStatus("resetPasswordStatus", "New password must be at least 6 characters", false);
  }
  try {
    const res = await fetch(`${API}/reset-password`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token, new_password})
    });
    const data = await res.json();
    if (res.ok) {
      setStatus("resetPasswordStatus", "Password updated. You can now log in with your new password.");
      document.getElementById("resetToken").value = "";
      document.getElementById("resetNewPassword").value = "";
    } else {
      setStatus("resetPasswordStatus", data.detail, false);
    }
  } catch (e) {
    setStatus("resetPasswordStatus", e.message, false);
  }
}

function closeLoginModal() {
  document.getElementById("loginModal").classList.add("hidden");
}

function closeRegisterModal() {
  document.getElementById("registerModal").classList.add("hidden");
}

function showRegister() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("registerModal").classList.remove("hidden");
  _regClearErrors();
}

function _regFieldErr(inputId, errId, msg) {
  document.getElementById(inputId).classList.add("invalid");
  document.getElementById(errId).textContent = msg;
}

function _regClearField(inputId, errId) {
  document.getElementById(inputId).classList.remove("invalid");
  document.getElementById(errId).textContent = "";
}

function _regClearErrors() {
  ["regUsername", "regEmail", "regPassword"].forEach(id => _regClearField(id, id + "Err"));
  document.getElementById("registerStatus").textContent = "";
}

async function checkNotifications() {
  try {
    const res = await fetch(`${API}/notifications`);
    if (!res.ok) return;
    const items = await res.json();
    if (!items.length) return;
    showNotificationPopup(items[0]);
  } catch (_) {}
}

function showNotificationPopup(notif) {
  document.getElementById("notifMessage").textContent = notif.message;
  document.getElementById("notifModal").classList.remove("hidden");
  window._dismissActiveNotification = async () => {
    await fetch(`${API}/notifications/${notif.id}/dismiss`, { method: "POST" });
    document.getElementById("notifModal").classList.add("hidden");
  };
  document.getElementById("notifDismissBtn").onclick = window._dismissActiveNotification;
}

async function claimTokenEvents() {
  try {
    const res = await fetch(`${API}/claim-events`, { method: "POST" });
    if (!res.ok) return;
    const data = await res.json();
    if (data.granted > 0) {
      await loadMe();
    }
  } catch (_) {}
}

async function login() {
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  if (!username || !password) return setStatus("loginStatus", "Enter username and password", false);

  try {
    const res = await fetch(`${API}/login`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, password}) });
    const data = await res.json();
    if (!res.ok) return setStatus("loginStatus", data.detail, false);

    await loadMe();
    await claimTokenEvents();
    checkNotifications();
    checkWeeklySummaryHighlight();
    document.getElementById("loginModal").classList.add("hidden");
    document.getElementById("loginPassword").value = "";
    applyAuthState();
    if (activeMustChangePassword) {
      switchTab("profile");
    } else {
      switchTab("team");
      loadDeck();
    }
  } catch (e) {
    setStatus("loginStatus", e.message, false);
  }
}

async function register() {
  _regClearErrors();
  const username = document.getElementById("regUsername").value.trim();
  const email    = document.getElementById("regEmail").value.trim();
  const password = document.getElementById("regPassword").value;

  let valid = true;
  let firstInvalidId = null;
  if (!username) {
    _regFieldErr("regUsername", "regUsernameErr", "Username is required");
    firstInvalidId = firstInvalidId || "regUsername";
    valid = false;
  } else if (username.length > 64) {
    _regFieldErr("regUsername", "regUsernameErr", "Username must be 64 characters or fewer");
    firstInvalidId = firstInvalidId || "regUsername";
    valid = false;
  }
  if (!email) {
    _regFieldErr("regEmail", "regEmailErr", "Email is required");
    firstInvalidId = firstInvalidId || "regEmail";
    valid = false;
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    _regFieldErr("regEmail", "regEmailErr", "Enter a valid email address");
    firstInvalidId = firstInvalidId || "regEmail";
    valid = false;
  }
  if (!password) {
    _regFieldErr("regPassword", "regPasswordErr", "Password is required");
    firstInvalidId = firstInvalidId || "regPassword";
    valid = false;
  } else if (password.length < 6) {
    _regFieldErr("regPassword", "regPasswordErr", "Password must be at least 6 characters");
    firstInvalidId = firstInvalidId || "regPassword";
    valid = false;
  } else if (password.length > 128) {
    _regFieldErr("regPassword", "regPasswordErr", "Password must be 128 characters or fewer");
    firstInvalidId = firstInvalidId || "regPassword";
    valid = false;
  }
  if (!valid) {
    if (firstInvalidId) document.getElementById(firstInvalidId).scrollIntoView({block: "center"});
    return;
  }

  try {
    const res = await fetch(`${API}/register`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, email, password}) });
    const data = await res.json();
    if (!res.ok) {
      const detail = data.detail;
      if (Array.isArray(detail)) {
        detail.forEach(err => {
          const field = err.loc ? err.loc[err.loc.length - 1] : null;
          if (field === "username") _regFieldErr("regUsername", "regUsernameErr", err.msg);
          else if (field === "email") _regFieldErr("regEmail", "regEmailErr", err.msg);
          else if (field === "password") _regFieldErr("regPassword", "regPasswordErr", err.msg);
          else setStatus("registerStatus", err.msg, false);
        });
      } else if (typeof detail === "string" && detail.toLowerCase().includes("username")) {
        _regFieldErr("regUsername", "regUsernameErr", detail);
      } else if (typeof detail === "string" && (detail.toLowerCase().includes("email") || detail.toLowerCase().includes("mail"))) {
        _regFieldErr("regEmail", "regEmailErr", detail);
      } else {
        setStatus("registerStatus", detail, false);
      }
      return;
    }

    await loadMe();
    await claimTokenEvents();
    checkNotifications();
    checkWeeklySummaryHighlight();
    document.getElementById("registerModal").classList.add("hidden");
    document.getElementById("regUsername").value = "";
    document.getElementById("regEmail").value    = "";
    document.getElementById("regPassword").value = "";
    applyAuthState();
    switchTab("team");
    loadDeck();
  } catch (e) {
    setStatus("registerStatus", e.message, false);
  }
}

// Drop every trace of the logged-in user from the page and show the logged-out state.
function _clearLocalAuthState() {
  activeUserId = activeUsername = null;
  activeIsAdmin = false;
  activeMustChangePassword = false;
  activeSteamLinked = false;
  activeHasPassword = true;
  activeIsDemo = false;
  localStorage.removeItem("username");
  localStorage.removeItem("is_admin");
  updateTokenDisplay(null);
  applyAuthState();
}

async function logout() {
  await fetch(`${API}/logout`, { method: "POST" });
  _clearLocalAuthState();
}

async function loadMe() {
  try {
    const res = await fetch(`${API}/me`);
    // 401: the session expired or was revoked (password change elsewhere, log out
    // everywhere, admin force logout). Show the logged-out state, not a stale header.
    if (res.status === 401) {
      if (activeUsername || localStorage.getItem("username")) _clearLocalAuthState();
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    activeUserId             = data.user_id;
    activeUsername           = data.username;
    activeIsAdmin            = data.is_admin;
    activeMustChangePassword = data.must_change_password ?? false;
    activeSteamLinked        = data.steam_linked === true;
    activeHasPassword        = data.has_password !== false;
    activeIsDemo             = data.is_demo === true;
    activeUsernameChangeAvailableAt = data.username_change_available_at ?? null;
    localStorage.setItem("username", activeUsername);
    localStorage.setItem("is_admin", String(activeIsAdmin));
    updateTokenDisplay(data.tokens ?? null);
    _applyTempPasswordBanner();
  } catch (_) {}
}

function _applyTempPasswordBanner() {
  const banner = document.getElementById("tempPasswordBanner");
  if (banner) banner.style.display = activeMustChangePassword ? "" : "none";
}

// Each credential flow is a <form> so password managers can fill and save it
// (issue #158). Submitting (Enter or the submit button) runs the existing
// function once; preventDefault() keeps the page from reloading.
document.getElementById("loginForm").addEventListener("submit", e => { e.preventDefault(); login(); });
document.getElementById("registerForm").addEventListener("submit", e => { e.preventDefault(); register(); });
document.getElementById("resetPasswordForm").addEventListener("submit", e => { e.preventDefault(); submitResetPassword(); });
document.getElementById("steamSignupForm").addEventListener("submit", e => { e.preventDefault(); submitSteamSignup(); });
