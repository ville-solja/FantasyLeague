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
  if (tabName === 'twitch') loadTwitchChannels();
  if (tabName === 'settings') { loadBackups(); restoreSettingsSection(); }
}

// ---------------------------------------------------------------------------
// Pending streamer approvals badge (issue 214)
//
// The Twitch sub-tab button and the top-level Admin tab show how many channels
// wait for approval, from GET /admin/twitch/channels. Fetched when an admin
// loads the page (applyAuthState) and re-rendered whenever the Approved
// streamers list loads, which Approve and Reject trigger. Hidden at zero.
// ---------------------------------------------------------------------------

const _PENDING_BADGE_IDS = ['adminTwitchPendingBadge', 'adminTabPendingBadge'];

function pendingBadgeLabel(n) {
  return `${n} ${n === 1 ? 'streamer' : 'streamers'} waiting for approval`;
}

function setTwitchPendingBadge(n) {
  const count = Number.isInteger(n) && n > 0 ? n : 0;
  _PENDING_BADGE_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.hidden = count === 0;
    el.textContent = count ? String(count) : '';
    if (count) el.setAttribute('aria-label', pendingBadgeLabel(count));
    else el.removeAttribute('aria-label');
  });
}

async function refreshTwitchPendingBadge() {
  if (!activeUserId || !activeIsAdmin) return setTwitchPendingBadge(0);
  try {
    const res = await fetch(`${API}/admin/twitch/channels`);
    if (!res.ok) return setTwitchPendingBadge(0);
    const data = await res.json();
    setTwitchPendingBadge((data.pending || []).length);
  } catch (e) {
    setTwitchPendingBadge(0);
  }
}

// ---------------------------------------------------------------------------
// Settings section nav (issue 214): selecting a section scrolls to it and is
// remembered per browser; storage may be blocked, so every access is guarded.
// ---------------------------------------------------------------------------

const SETTINGS_SECTION_KEY = 'adminSettingsSection';

function selectSettingsSection(name, scroll = true) {
  const section = document.getElementById(`settings-section-${name}`);
  if (!section) return;
  document.querySelectorAll('.settings-nav-btn').forEach(btn => {
    const on = btn.dataset.settingsTarget === name;
    btn.classList.toggle('active', on);
    if (on) btn.setAttribute('aria-current', 'true');
    else btn.removeAttribute('aria-current');
  });
  if (scroll) section.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
  try { localStorage.setItem(SETTINGS_SECTION_KEY, name); } catch (e) { /* storage blocked */ }
}

function restoreSettingsSection() {
  let saved = null;
  try { saved = localStorage.getItem(SETTINGS_SECTION_KEY); } catch (e) { /* storage blocked */ }
  const name = saved && document.getElementById(`settings-section-${saved}`) ? saved : 'season';
  selectSettingsSection(name, name !== 'season');
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

// An action the full-page Steam confirmation resumes on return (handleSteamReturn),
// e.g. "connectTwitch"; without one the page asks the user to repeat the action. The
// popup path (issue 213) needs none: the caller's promise resolves in place.
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

// Issue #150: an account without a password (created through Steam) confirms with
// Steam. Issue 213: an account with a password and a linked Steam account may use
// either, so the password view also offers "Confirm with Steam instead".
function _showReauthMethod(method) {
  const steam = method === "steam";
  document.getElementById("reauthTitle").textContent = steam ? "Confirm with Steam" : "Confirm your password";
  document.getElementById("reauthPasswordText").style.display = steam ? "none" : "";
  document.getElementById("reauthForm").style.display = steam ? "none" : "";
  document.getElementById("reauthSteamBlock").style.display = steam ? "" : "none";
  const steamOn = _loginMethod === "both" || _loginMethod === "steam_signup";
  document.getElementById("reauthSteamInstead").style.display =
    !steam && steamOn && activeSteamLinked ? "" : "none";
  _showSteamNotice(null);
}

/** Shows one of the modal's Steam notices ("blocked", "unavailable") or none. */
function _showSteamNotice(which) {
  document.getElementById("reauthPopupBlocked").style.display = which === "blocked" ? "" : "none";
  document.getElementById("reauthSteamUnavailable").style.display = which === "unavailable" ? "" : "none";
}

// ---------------------------------------------------------------------------
// Steam re-auth in a popup (issue 213)
//
// Confirm with Steam opens GET /auth/steam/start?purpose=reauth&return_tab=popup in a
// small window, so the page and any open dialog stay as they are. The popup ends on
// /steam-reauth-done.html, which posts {type: "steam-reauth", result} to this window
// (same origin only) and closes. On "ok" the prompt resolves and adminFetch retries
// the original request once; other results show their message and retry nothing.
// A popup closed without a message counts as not confirmed. A blocked popup offers
// the full-page round trip (startSteamReauthFullPage) as before.
// ---------------------------------------------------------------------------

const _STEAM_POPUP_MESSAGES = {
  reauth_failed: "That Steam account is not the one linked to this account. Nothing was confirmed.",
  no_session:    "Log in to Kana Cards first, then try again.",
  not_linked:    "This account has no Steam link to confirm with.",
  failed:        "Steam sign-in did not complete. Nothing was changed. Try again.",
};
const _STEAM_POPUP_CLOSED_GRACE_MS = 500;

let _steamPopup = null;   // {win, timer} while a popup is open

function startSteamReauth() {
  _showSteamNotice(null);
  document.getElementById("reauthStatus").textContent = "";
  if (!_steamReauthAvailable) return _showSteamNotice("unavailable");
  // Opened straight from the click, so the browser treats it as requested.
  let win = null;
  try {
    win = window.open(`${API}/auth/steam/start?purpose=reauth&return_tab=popup`,
                      "steamReauth", "popup,width=800,height=700");
  } catch (e) { win = null; }
  if (!win) return _showSteamNotice("blocked");
  _watchSteamPopup(win);
}

function startSteamReauthFullPage() {
  const active = document.querySelector(".tab-content.active");
  const tab = active && active.id === "tab-admin" ? "admin" : "profile";
  try {
    if (_reauthResume) sessionStorage.setItem("reauthResume", _reauthResume);
    else sessionStorage.removeItem("reauthResume");
  } catch (e) { /* storage blocked: the user repeats the action */ }
  window.location.href = `${API}/auth/steam/start?purpose=reauth&return_tab=${tab}`;
}

function _watchSteamPopup(win) {
  _stopSteamPopup(false);
  const popup = { win, timer: null };
  popup.timer = setInterval(() => {
    if (!win.closed) return;
    clearInterval(popup.timer);
    // A result posted just before the window closed is still on its way: wait briefly.
    setTimeout(() => {
      if (_steamPopup !== popup) return;
      _steamPopup = null;
      _finishReauth(false);
    }, _STEAM_POPUP_CLOSED_GRACE_MS);
  }, 500);
  _steamPopup = popup;
}

function _stopSteamPopup(closeWindow) {
  const popup = _steamPopup;
  _steamPopup = null;
  if (!popup) return;
  clearInterval(popup.timer);
  if (closeWindow && !popup.win.closed) {
    try { popup.win.close(); } catch (e) { /* already gone */ }
  }
}

function _onSteamReauthMessage(event) {
  if (!_steamPopup || event.origin !== window.location.origin || event.source !== _steamPopup.win) return;
  const data = event.data;
  if (!data || typeof data !== "object" || data.type !== "steam-reauth") return;
  const result = data.result;
  if (result !== "ok" && !Object.hasOwn(_STEAM_POPUP_MESSAGES, result)) return;
  _stopSteamPopup(false);
  if (result === "ok") return _finishReauth(true);
  document.getElementById("reauthStatus").textContent = _STEAM_POPUP_MESSAGES[result];
}

window.addEventListener("message", _onSteamReauthMessage);

function _finishReauth(confirmed) {
  _stopSteamPopup(true);
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
