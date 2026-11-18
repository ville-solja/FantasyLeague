// How to Play subtab switching is handled declaratively by Alpine.js
// (x-data/x-show/@click on the tab markup in index.html) — see
// markdown/features/reference/frontend-framework-evaluation.md.

async function loadHowToPlay() {
  loadObsOverlayBuilder();
  const res = await fetch(`${API}/weights`);
  if (!res.ok) {
    ["howtoplay-stats-tbody", "howtoplay-rarity-tbody", "howtoplay-mods-tbody"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<tr><td colspan="2" style="color:#c44;">Could not load scoring data</td></tr>';
    });
    return;
  }
  const weights = await res.json();
  const byKey = Object.fromEntries(weights.map(w => [w.key, w]));

  const statsKeys = [
    'kills', 'assists', 'last_hits', 'denies', 'gold_per_min', 'obs_placed',
    'towers_killed', 'roshan_kills', 'courier_kills', 'teamfight_participation',
    'camps_stacked', 'rune_pickups', 'firstblood_claimed', 'stuns',
  ];
  const statsLabels = {
    kills:                   'Kills',
    assists:                 'Assists',
    last_hits:               'Last hits',
    denies:                  'Denies',
    gold_per_min:            'Gold per minute',
    obs_placed:              'Observer wards',
    towers_killed:           'Towers killed',
    roshan_kills:            'Roshan kills',
    courier_kills:           'Courier kills',
    teamfight_participation: 'Teamfight participation (0–1)',
    camps_stacked:           'Camps stacked',
    rune_pickups:            'Rune pickups',
    firstblood_claimed:      'First blood',
    stuns:                   'Stun seconds',
  };
  const tbody = document.getElementById('howtoplay-stats-tbody');
  if (tbody) {
    const rows = statsKeys.map(k => {
      const w = byKey[k];
      return `<tr><td>${statsLabels[k]}</td><td>${w ? w.value : '—'}</td></tr>`;
    });
    const pool = byKey['death_pool']?.value ?? 3.0;
    const ded  = byKey['death_deduction']?.value ?? 0.3;
    rows.push(`<tr><td>Deaths (survival bonus)</td><td>+${pool} per game at 0 deaths, −${ded} per death (min 0)</td></tr>`);
    tbody.innerHTML = rows.join('');
  }

  const rarityKeys = ['rarity_common', 'rarity_rare', 'rarity_epic', 'rarity_legendary'];
  const rarityTbody = document.getElementById('howtoplay-rarity-tbody');
  if (rarityTbody) {
    rarityTbody.innerHTML = rarityKeys.map(k => {
      const w = byKey[k];
      const label = k.replace('rarity_', '').replace(/^\w/, c => c.toUpperCase());
      return `<tr><td>${label}</td><td>+${w ? w.value : 0}%</td></tr>`;
    }).join('');
  }

  const modKeys = ['modifier_count_common', 'modifier_count_rare', 'modifier_count_epic', 'modifier_count_legendary'];
  const modTbody = document.getElementById('howtoplay-mods-tbody');
  if (modTbody) {
    const bonusPct = byKey['modifier_bonus_pct']?.value ?? 10;
    modTbody.innerHTML = modKeys.map(k => {
      const w = byKey[k];
      const label = k.replace('modifier_count_', '').replace(/^\w/, c => c.toUpperCase());
      const count = w ? w.value : 0;
      return `<tr><td>${label}</td><td>${count} modifier${count !== 1 ? 's' : ''} (+${bonusPct}% each)</td></tr>`;
    }).join('');
  }

  const mvpEl = document.getElementById('howtoplay-mvp-bonus');
  if (mvpEl) {
    const mvpPct = byKey['mvp_bonus_pct']?.value ?? 10;
    mvpEl.textContent = `+${mvpPct}%`;
  }
}

// Issue 246: How to Play › Streamers › Pause screen overlay URL builder.
function obsOverlayCopyEnabled(teamA, teamB) {
  const a = String(teamA ?? ''), b = String(teamB ?? '');
  return /^[1-9][0-9]*$/.test(a) && /^[1-9][0-9]*$/.test(b) && a !== b;
}

function obsOverlayUrl(origin, teamA, teamB, transparent) {
  if (!obsOverlayCopyEnabled(teamA, teamB)) return '';
  return `${origin}/obs/last-game.html?teams=${teamA},${teamB}` + (transparent ? '&theme=transparent' : '');
}

function obsOverlayTeamOptions(teams) {
  const rows = (teams || []).filter(t => Number.isFinite(Number(t.id)) && Number(t.id) > 0);
  rows.sort((x, y) => String(x.name || '').localeCompare(String(y.name || '')) || Number(x.id) - Number(y.id));
  return '<option value="">Pick a team</option>' +
    rows.map(t => `<option value="${Number(t.id)}">${_escHtml(t.name || `Team ${Number(t.id)}`)}</option>`).join('');
}

async function loadObsOverlayBuilder() {
  const a = document.getElementById('obs-team-a');
  const b = document.getElementById('obs-team-b');
  if (!a || !b || a.dataset.loaded) return;
  try {
    const res = await fetch(`${API}/teams`);
    if (!res.ok) return;
    const options = obsOverlayTeamOptions(await res.json());
    a.innerHTML = options;
    b.innerHTML = options;
    a.dataset.loaded = '1';
  } catch (e) {
    return;
  }
  updateObsOverlayUrl();
}

function updateObsOverlayUrl() {
  const a = document.getElementById('obs-team-a');
  const b = document.getElementById('obs-team-b');
  const field = document.getElementById('obs-url');
  const copy = document.getElementById('obs-copy');
  const preview = document.getElementById('obs-preview');
  const transparent = document.getElementById('obs-transparent');
  if (!a || !b || !field || !copy || !preview) return;
  const url = obsOverlayUrl(location.origin, a.value, b.value, !!(transparent && transparent.checked));
  field.value = url;
  copy.disabled = !url;
  if (url) {
    preview.setAttribute('href', url);
    preview.removeAttribute('aria-disabled');
  } else {
    preview.removeAttribute('href');
    preview.setAttribute('aria-disabled', 'true');
  }
  const status = document.getElementById('obs-copy-status');
  if (status) status.textContent = '';
}

async function copyObsOverlayUrl() {
  const field = document.getElementById('obs-url');
  const status = document.getElementById('obs-copy-status');
  if (!field || !field.value) return;
  try {
    await navigator.clipboard.writeText(field.value);
    if (status) status.textContent = 'Copied.';
  } catch (e) {
    field.select();
    if (status) status.textContent = 'Press Ctrl+C to copy the selected URL.';
  }
}

// Generic modal handling: every `.modal-overlay`/`.reveal-overlay` declares its own
// close function via `data-close="fnName"`, so Escape, backdrop clicks, and focus
// management all work uniformly without a per-modal hardcoded list.
function _isModalVisible(el) {
  return getComputedStyle(el).display !== "none";
}

function _getVisibleModal() {
  // When modals stack (e.g. a player/team modal opened from within the Weekly Report
  // popup), the later element in the DOM paints on top (the card viewer's
  // .reveal-overlay sits above the Weekly Report, and the player/team popups after it
  // sit above the viewer; see style.css) — so the *last* visible one, not the first, is the one
  // Escape/focus-trapping should target, leaving the modal(s) underneath untouched.
  const visible = [...document.querySelectorAll(".modal-overlay, .reveal-overlay")].filter(_isModalVisible);
  return visible[visible.length - 1] || null;
}

function _getFocusableIn(container) {
  return [...container.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter(el => el.offsetParent !== null);
}

document.addEventListener("keydown", function(e) {
  if (e.key !== "Escape") return;
  const modal = _getVisibleModal();
  if (!modal) return;
  const fnName = modal.dataset.close;
  if (fnName && typeof window[fnName] === "function") window[fnName]();
});

// Minimal focus trap: while any modal is open, Tab cycles only within it.
document.addEventListener("keydown", function(e) {
  if (e.key !== "Tab") return;
  const modal = _getVisibleModal();
  if (!modal) return;
  const focusables = _getFocusableIn(modal);
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault(); last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault(); first.focus();
  }
});

// Move focus into a modal the moment it becomes visible (class/style toggles).
(function () {
  let _lastVisible = new Set();
  const observer = new MutationObserver(() => {
    const nowVisible = new Set(document.querySelectorAll(".modal-overlay, .reveal-overlay"));
    nowVisible.forEach(el => {
      if (_isModalVisible(el) && !_lastVisible.has(el)) {
        const focusables = _getFocusableIn(el);
        if (focusables.length) focusables[0].focus();
      }
      if (_isModalVisible(el)) _lastVisible.add(el); else _lastVisible.delete(el);
    });
  });
  document.querySelectorAll(".modal-overlay, .reveal-overlay").forEach(el => {
    observer.observe(el, { attributes: true, attributeFilter: ["class", "style"] });
  });
})();

function _handleResetTokenParam() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("reset_token");
  if (!token) return;
  // Strip the token from the visible address bar so it doesn't linger in
  // browser history, then open the reset-password modal pre-filled with it.
  history.replaceState(null, "", window.location.pathname);
  showResetPassword(token);
}

// ---------------------------------------------------------------------------
// Tab links (issue #245): `/#<tab>` opens that tab; Back and Forward move between tabs.
// ---------------------------------------------------------------------------

const _TAB_LINK_NOTICES = {
  finals: "The Finals tab isn't open yet.",
  teamfinder: "Team Finder isn't open right now.",
};

/** Whether a tab's button is shown to this visitor (the same flags the tab bar uses). */
function _tabLinkAvailable(tab) {
  if (tab === "finals" || tab === "teamfinder") {
    const btn = document.getElementById(`tab-btn-${tab}`);
    return !!btn && !btn.hidden;
  }
  if (tab === "team" || tab === "profile") return !!activeUserId;
  if (tab === "admin") return !!(activeUserId && activeIsAdmin);
  return true;
}

/** Shows the tab a link names, or the fallback for one this visitor can't open. On
 *  page load a login-only tab opens the login dialog and waits for the login; on Back
 *  or Forward it falls back to Leaderboards. Returns the subtab it selected, or null. */
function _openLinkedTab(link, onLoad) {
  const tab = link.tab;
  if (_tabLinkAvailable(tab)) {
    switchTab(tab, onLoad ? undefined : { history: "none" });
    if (tab === "howtoplay" && link.subtab) setHowToPlaySubtab(link.subtab);
    return tab === "howtoplay" ? link.subtab : null;
  }
  switchTab("leaderboard");
  if (_TAB_LINK_NOTICES[tab]) {
    setStatus("tabLinkNotice", _TAB_LINK_NOTICES[tab]);
    document.getElementById("tabLinkNotice").hidden = false;
  } else if (onLoad && (tab === "team" || tab === "profile")) {
    _setPendingTab(tab);
    showLogin();
  }
  return null;
}

/** End of init()'s address handling: opens the linked tab (or the tab a link asked
 *  for before a Steam sign-in), then lets switchTab write the address again and, when
 *  the page came with a hash or a return changed the address, writes the current
 *  tab's link. A bare `/` load keeps its address. */
function _routeInitialLink(startHash, startSearch) {
  const link = tabFromLink(startHash);
  let subtab = null;
  let switched = false;
  if (link) {
    subtab = _openLinkedTab(link, true);
  } else if (activeUserId && !startHash) {
    const pending = _takePendingTab();
    if (pending) { switchTab(pending); switched = true; }
  }
  _tabLinkRouting = false;
  if (!startHash && !switched && (window.location.search || "") === startSearch) return;
  const active = document.querySelector(".tab-content.active");
  if (active) _writeTabAddress(active.id.replace(/^tab-/, ""), "replace", true, subtab);
}

window.addEventListener("popstate", () => {
  const hash = window.location.hash || "";
  if (!hash) { switchTab("leaderboard", { history: "none" }); return; }
  const link = tabFromLink(hash);
  if (link) _openLinkedTab(link, false);  // anything else (in-page anchors) is ignored
});

// How to Play's subtab lives in Alpine (`howToPlayTab`, index.html). Alpine is loaded
// with `defer`, so the component reads the subtab a link chose when it starts
// (htpSubtabOnStart) and hears later choices as an `htp-subtab` window event.
let _htpSubtab = null;

function setHowToPlaySubtab(subtab) {
  _htpSubtab = subtab;
  if (typeof window.dispatchEvent === "function" && typeof CustomEvent === "function") {
    window.dispatchEvent(new CustomEvent("htp-subtab", { detail: subtab }));
  }
}

function htpSubtabOnStart() {
  return _htpSubtab || "users";
}

/** Alpine's `$watch` on howToPlayTab: a subtab chosen on How to Play replaces the address. */
function htpSubtabChanged(subtab) {
  _htpSubtab = subtab;
  const tab = document.getElementById("tab-howtoplay");
  if (tab && tab.classList.contains("active")) _writeTabAddress("howtoplay", "replace", true, subtab);
}

/** Streamers overview buttons: scroll to a section without changing the address. */
function scrollToHtpSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
}

async function init() {
  // Issue #245: read the link before applyAuthState and the return handlers run.
  const startHash = window.location.hash || "";
  const startSearch = window.location.search || "";
  await loadConfig();
  loadAccolades();  // issue 50: accolade pips on every card, loaded once per page
  await loadMe();
  applyAuthState();
  _handleResetTokenParam();
  if (!handleSteamReturn() && !handleTwitchErrorReturn()) handleTwitchReturn();
  _routeInitialLink(startHash, startSearch);
  if (activeUserId) {
    claimTokenEvents();
    checkNotifications();
    checkWeeklySummaryHighlight();
    showOwnCardGrant();
    loadDeck();
    await loadWeeks();
    loadRoster(_rosterWeekId);
    _populateLbWeekSelect();
    loadSeasonLeaderboard();
  } else {
    await loadWeeks();
    _populateLbWeekSelect();
    loadSeasonLeaderboard();
  }
  loadLeaderboard();
  loadTop();
}

init().then(() => {
  if (typeof lucide !== "undefined") lucide.createIcons();
});
