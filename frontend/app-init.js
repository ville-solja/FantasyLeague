async function loadHowToPlay() {
  const res = await fetch(`${API}/weights`);
  if (!res.ok) return;
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

document.addEventListener("keydown", function(e) {
  if (e.key !== "Escape") return;
  const visible = id => !document.getElementById(id).classList.contains("hidden");
  if (visible("playerModal"))  { closePlayerModal();  return; }
  if (visible("teamModal"))    { closeTeamModal();    return; }
  if (visible("revealModal"))  { closeReveal();       return; }
  if (visible("registerModal")){ closeRegisterModal(); return; }
  if (visible("forgotModal"))  { showLogin();         return; }
  if (visible("loginModal"))   { closeLoginModal();   return; }
});

async function init() {
  await loadConfig();
  await loadMe();
  applyAuthState();
  if (activeUserId) {
    loadDeck();
    loadWeeks().then(() => {
      loadRoster(_rosterWeekId);
      _populateLbWeekSelect();
      loadSeasonLeaderboard();
    });
  } else {
    loadWeeks().then(() => { _populateLbWeekSelect(); loadSeasonLeaderboard(); });
  }
  loadLeaderboard();
  loadTop();
}

init().then(() => {
  if (typeof lucide !== "undefined") lucide.createIcons();
});
