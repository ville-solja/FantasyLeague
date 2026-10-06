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

function _promptReauth() {
  if (_reauthResolve) _finishReauth(false);
  document.getElementById("reauthUsername").value = activeUsername || "";
  document.getElementById("reauthPassword").value = "";
  document.getElementById("reauthStatus").textContent = "";
  document.getElementById("reauthModal").classList.remove("hidden");
  return new Promise(resolve => { _reauthResolve = resolve; });
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
      status.textContent = typeof data.detail === "string" ? data.detail : "Password check failed";
      input.value = "";
      return;
    }
    _finishReauth(true);
  } catch (e) {
    status.textContent = e.message;
  }
}
