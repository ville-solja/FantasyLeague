// ---------------------------------------------------------------------------
// Admin tab navigation
//
// The rest of the admin panel's logic lives in the sibling app-admin-*.js
// files, split along the backend's routers/admin_*.py boundaries:
//   app-admin-weeks.js         Week Management + Nordic date picker widget
//   app-admin-users.js         User Management, tags, tokens, redeemable codes
//   app-admin-notifications.js Notifications + token grant events
//   app-admin-ingest.js        Weights, schedule refresh, audit log, recalculate, enrich profiles
//   app-admin-players.js       Player Pool Management
//   app-admin-leagues.js       League Monitoring
//   app-admin-matches.js       Matches tab + MVP selection modal
//   app-admin-season.js        Season Lifecycle (End Season / Season Reset)
//   app-admin-backups.js       Database Backups (create / list / download)
//   app-admin-demo.js          Demo Mode panel (DEMO_MODE-gated)
// This file owns the tab bar itself, since every other file needs it
// loaded first for initWeekDateInputs()/switchAdminTab() to exist, and the
// shared adminFetch() re-authentication wrapper at the bottom.
// ---------------------------------------------------------------------------

function initAdminTabs() {
  const tabBar = document.getElementById('admin-tab-bar');
  if (!tabBar) return;

  tabBar.querySelectorAll('.admin-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchAdminTab(btn.dataset.tab));
  });

  initWeekDateInputs();

  // Restore previously selected tab from sessionStorage, defaulting to user-management
  const saved = sessionStorage.getItem('adminTab') || 'user-management';
  switchAdminTab(saved);
}

function switchAdminTab(tabName) {
  // Update button active states
  document.querySelectorAll('.admin-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  // Show the matching section; hide all others
  document.querySelectorAll('[data-admin-tab]').forEach(el => {
    el.style.display = el.dataset.adminTab === tabName ? '' : 'none';
  });

  // Persist selection so navigating away and back remembers the tab
  sessionStorage.setItem('adminTab', tabName);

  // Lazily load data for the matches tab on first activation
  if (tabName === 'matches') loadAdminMatches();
  if (tabName === 'settings') loadBackups();
}

// ---------------------------------------------------------------------------
// Admin re-authentication (issue #117)
//
// Destructive admin endpoints answer 403 {"detail": "reauth_required"} unless
// this session confirmed the password recently (POST /reauth). adminFetch()
// shows the in-page password prompt (#reauthModal), and once the password is
// confirmed it retries the original request exactly once. Cancelling returns
// the original 403 response to the caller.
// ---------------------------------------------------------------------------

let _reauthResolve = null;

async function adminFetch(url, options) {
  const res = await fetch(url, options);
  if (res.status !== 403) return res;
  const data = await res.clone().json().catch(() => ({}));
  if (data.detail !== "reauth_required") return res;
  const confirmed = await _promptReauth();
  if (!confirmed) return res;
  return fetch(url, options);
}

// An action the Steam confirmation resumes on return (handleSteamReturn), e.g.
// "connectTwitch"; without one the page asks the user to repeat the action.
let _reauthResume = null;

function _promptReauth(resume) {
  if (_reauthResolve) _finishReauth(false);
  _reauthResume = resume || null;
  document.getElementById("reauthUsername").value = activeUsername || "";
  document.getElementById("reauthPassword").value = "";
  document.getElementById("reauthStatus").textContent = "";
  _showReauthMethod(activeHasPassword ? "password" : "steam");
  document.getElementById("reauthModal").classList.remove("hidden");
  return new Promise(resolve => { _reauthResolve = resolve; });
}

// Issue #150: an account without a password (created through Steam) confirms with a
// Steam round trip instead. That leaves the page, so the action is repeated afterwards.
function _showReauthMethod(method) {
  const steam = method === "steam";
  document.getElementById("reauthTitle").textContent = steam ? "Confirm with Steam" : "Confirm your password";
  document.getElementById("reauthPasswordText").style.display = steam ? "none" : "";
  document.getElementById("reauthForm").style.display = steam ? "none" : "";
  document.getElementById("reauthSteamBlock").style.display = steam ? "" : "none";
}

function startSteamReauth() {
  const active = document.querySelector(".tab-content.active");
  const tab = active && active.id === "tab-admin" ? "admin" : "profile";
  try {
    if (_reauthResume) sessionStorage.setItem("reauthResume", _reauthResume);
    else sessionStorage.removeItem("reauthResume");
  } catch (e) { /* storage blocked: the user repeats the action */ }
  window.location.href = `${API}/auth/steam/start?purpose=reauth&return_tab=${tab}`;
}

function _finishReauth(confirmed) {
  document.getElementById("reauthModal").classList.add("hidden");
  document.getElementById("reauthPassword").value = "";
  const resolve = _reauthResolve;
  _reauthResolve = null;
  if (resolve) resolve(confirmed);
}

function closeReauthModal() {
  _finishReauth(false);
}

document.getElementById("reauthForm").addEventListener("submit", e => { e.preventDefault(); submitReauth(); });

async function submitReauth() {
  const input = document.getElementById("reauthPassword");
  const status = document.getElementById("reauthStatus");
  if (!input.value) {
    status.textContent = "Enter your password.";
    return;
  }
  try {
    const res = await fetch(`${API}/reauth`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: input.value}),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (res.status === 409 && data.detail === "use_steam_reauth") {
        activeHasPassword = false;
        input.value = "";
        return _showReauthMethod("steam");
      }
      status.textContent = typeof data.detail === "string" ? data.detail : "Password check failed";
      input.value = "";
      return;
    }
    _finishReauth(true);
  } catch (e) {
    status.textContent = e.message;
  }
}

// ---------------------------------------------------------------------------
// Typed confirmation (issue #150)
//
// Destructive admin actions also need the action's name typed in; the backend
// answers 400 {"detail": "confirmation_required"} without a matching `confirm`
// (deps.CONFIRM_PHRASES). typedConfirm() resolves with the typed phrase, or null
// when cancelled.
// ---------------------------------------------------------------------------

const ADMIN_CONFIRM_PHRASES = {
  season_end:      "END SEASON",
  season_reset:    "RESET SEASON",
  toggle_admin:    "CHANGE ADMIN",
  grant_tokens:    "GRANT TOKENS",
  backup_download: "DOWNLOAD BACKUP",
  delete_user:     "DELETE USER",
};

let _typedConfirmState = null;

function typedConfirm(action, text) {
  if (_typedConfirmState) _finishTypedConfirm(null);
  const phrase = ADMIN_CONFIRM_PHRASES[action];
  document.getElementById("typedConfirmText").textContent = text;
  document.getElementById("typedConfirmPhrase").textContent = phrase;
  document.getElementById("typedConfirmInput").value = "";
  document.getElementById("typedConfirmStatus").textContent = "";
  document.getElementById("typedConfirmModal").classList.remove("hidden");
  return new Promise(resolve => { _typedConfirmState = {phrase, resolve}; });
}

function _finishTypedConfirm(value) {
  document.getElementById("typedConfirmModal").classList.add("hidden");
  const state = _typedConfirmState;
  _typedConfirmState = null;
  if (state) state.resolve(value);
}

function closeTypedConfirm() {
  _finishTypedConfirm(null);
}

document.getElementById("typedConfirmForm").addEventListener("submit", e => {
  e.preventDefault();
  if (!_typedConfirmState) return;
  const typed = document.getElementById("typedConfirmInput").value.trim();
  if (typed.toUpperCase() !== _typedConfirmState.phrase) {
    document.getElementById("typedConfirmStatus").textContent = `Type "${_typedConfirmState.phrase}" to confirm.`;
    return;
  }
  _finishTypedConfirm(typed);
});
