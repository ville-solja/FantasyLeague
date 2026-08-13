function switchHowToPlayTab(role) {
  // Update button active states
  document.querySelectorAll('.howtoplay-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === role);
  });

  // Show the matching panel; hide all others — pure client-side, no fetch
  document.querySelectorAll('[data-howtoplay-tab]').forEach(el => {
    el.style.display = el.dataset.howtoplayTab === role ? '' : 'none';
  });
}

function initHowToPlayTabs() {
  const tabBar = document.getElementById('howtoplay-tab-bar');
  if (!tabBar) return;

  tabBar.querySelectorAll('.howtoplay-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchHowToPlayTab(btn.dataset.tab));
  });

  // The How to Play tab always opens on the Users subtab
  switchHowToPlayTab('users');
}

async function loadHowToPlay() {
  initHowToPlayTabs();
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
    'kills', 'last_hits', 'denies', 'gold_per_min', 'obs_placed',
    'towers_killed', 'roshan_kills', 'teamfight_participation',
    'camps_stacked', 'rune_pickups', 'firstblood_claimed', 'stuns',
  ];
  const statsLabels = {
    kills:                   'Kills',
    last_hits:               'Last hits',
    denies:                  'Denies',
    gold_per_min:            'Gold per minute',
    obs_placed:              'Observer wards',
    towers_killed:           'Towers killed',
    roshan_kills:            'Roshan kills',
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
    rows.push(`<tr><td>Deaths (survival bonus)</td><td>+${pool} at 0 deaths, −${ded} per death (min 0)</td></tr>`);
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

// Generic modal handling: every `.modal-overlay`/`.reveal-overlay` declares its own
// close function via `data-close="fnName"`, so Escape, backdrop clicks, and focus
// management all work uniformly without a per-modal hardcoded list.
function _isModalVisible(el) {
  return getComputedStyle(el).display !== "none";
}

function _getVisibleModal() {
  return [...document.querySelectorAll(".modal-overlay, .reveal-overlay")].find(_isModalVisible) || null;
}

function _getFocusableIn(container) {
  return [...container.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
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

async function init() {
  await loadConfig();
  await loadMe();
  applyAuthState();
  if (activeUserId) {
    claimTokenEvents();
    checkNotifications();
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
