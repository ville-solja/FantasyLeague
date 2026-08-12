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
//   app-admin-demo.js          Demo Mode panel (DEMO_MODE-gated)
// This file only owns the tab bar itself, since every other file needs it
// loaded first for initWeekDateInputs()/switchAdminTab() to exist.
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
}
