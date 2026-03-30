const API = "";

let activeUserId   = null;
let activeUsername = localStorage.getItem("username");
let activeIsAdmin  = localStorage.getItem("is_admin") === "true";
let _tokenName     = "Tokens";
let _tokenBalance  = null;

// -------------------------------------------------------
// CONFIG
// -------------------------------------------------------

async function loadConfig() {
  try {
    const res = await fetch(`${API}/config`);
    if (res.ok) {
      const cfg = await res.json();
      _tokenName = cfg.token_name || "Tokens";
    }
  } catch (_) { /* non-fatal */ }
}

function updateTokenDisplay(balance) {
  _tokenBalance = balance;
  const el = document.getElementById("tokenBalance");
  if (!el) return;
  if (balance !== null && activeUserId) {
    el.textContent = `${balance} ${_tokenName}`;
    el.style.display = "";
  } else {
    el.style.display = "none";
  }
}

// -------------------------------------------------------
// AUTH
// -------------------------------------------------------

function applyAuthState() {
  const loggedIn = !!activeUserId;

  document.getElementById("headerUserLabel").textContent = loggedIn ? activeUsername : "";
  document.getElementById("headerLoginBtn").style.display  = loggedIn ? "none" : "";
  document.getElementById("headerLogoutBtn").style.display = loggedIn ? "" : "none";

  document.getElementById("tab-btn-team").style.display    = loggedIn ? "" : "none";
  document.getElementById("tab-btn-profile").style.display = loggedIn ? "" : "none";
  document.getElementById("tab-btn-admin").style.display   = (loggedIn && activeIsAdmin) ? "" : "none";

  const tokenEl = document.getElementById("tokenBalance");
  if (tokenEl) tokenEl.style.display = loggedIn ? "" : "none";

  if (!loggedIn) switchTab("leaderboard");
}

function showLogin() {
  document.getElementById("registerModal").classList.add("hidden");
  document.getElementById("loginModal").classList.remove("hidden");
  document.getElementById("loginStatus").textContent = "";
}

function closeLoginModal() {
  document.getElementById("loginModal").classList.add("hidden");
}

function showRegister() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("registerModal").classList.remove("hidden");
  document.getElementById("registerStatus").textContent = "";
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

    document.getElementById("loginModal").classList.add("hidden");
    document.getElementById("loginPassword").value = "";
    applyAuthState();
    switchTab("team");
    loadDeck();
  } catch (e) {
    setStatus("loginStatus", e.message, false);
  }
}

async function register() {
  const username = document.getElementById("regUsername").value.trim();
  const email    = document.getElementById("regEmail").value.trim();
  const password = document.getElementById("regPassword").value;
  if (!username || !email || !password) return setStatus("registerStatus", "All fields required", false);

  try {
    const res = await fetch(`${API}/register`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, email, password}) });
    const data = await res.json();
    if (!res.ok) return setStatus("registerStatus", data.detail, false);

    // Auto-login on registration
    await loadMe();
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

async function loadMe() {
  try {
    const res = await fetch(`${API}/me`);
    if (!res.ok) return;
    const data = await res.json();
    activeUserId   = data.user_id;
    activeUsername = data.username;
    activeIsAdmin  = data.is_admin;
    localStorage.setItem("username", activeUsername);
    localStorage.setItem("is_admin", String(activeIsAdmin));
    updateTokenDisplay(data.tokens ?? null);
  } catch (_) {}
}

async function logout() {
  await fetch(`${API}/logout`, { method: "POST" });
  activeUserId = activeUsername = null;
  activeIsAdmin = false;
  localStorage.removeItem("username");
  localStorage.removeItem("is_admin");
  updateTokenDisplay(null);
  applyAuthState();
}

// -------------------------------------------------------
// PROFILE
// -------------------------------------------------------

async function loadProfile() {
  document.getElementById("profileUsername").value = activeUsername || "";
  document.getElementById("profilePlayerPreview").style.display = "none";
  document.getElementById("playerIdStatus").textContent = "";
  document.getElementById("usernameStatus").textContent = "";
  try {
    const res = await fetch(`${API}/profile/${activeUserId}`);
    const data = await res.json();
    if (data.player_id) {
      document.getElementById("profilePlayerId").value = data.player_id;
      if (data.player_name) showPlayerPreview(data.player_name, data.player_avatar_url);
    } else {
      document.getElementById("profilePlayerId").value = "";
    }
  } catch (e) {
    setStatus("playerIdStatus", e.message, false);
  }
}

function showPlayerPreview(name, avatarUrl) {
  const preview = document.getElementById("profilePlayerPreview");
  document.getElementById("profilePlayerName").textContent = name || "";
  const avatar = document.getElementById("profilePlayerAvatar");
  if (avatarUrl) { avatar.src = avatarUrl; avatar.style.display = ""; }
  else { avatar.style.display = "none"; }
  preview.style.display = name ? "flex" : "none";
}

async function saveUsername() {
  const username = document.getElementById("profileUsername").value.trim();
  if (!username) return setStatus("usernameStatus", "Username cannot be empty", false);
  try {
    const res = await fetch(`${API}/profile/username`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username})
    });
    const data = await res.json();
    if (!res.ok) return setStatus("usernameStatus", data.detail, false);
    activeUsername = data.username;
    localStorage.setItem("username", activeUsername);
    document.getElementById("headerUserLabel").textContent = activeUsername;
    setStatus("usernameStatus", "Username updated");
  } catch (e) {
    setStatus("usernameStatus", e.message, false);
  }
}

async function changePassword() {
  const current = document.getElementById("pwCurrent").value;
  const newPw   = document.getElementById("pwNew").value;
  if (!current || !newPw) return setStatus("passwordStatus", "Fill in both fields", false);
  try {
    const res = await fetch(`${API}/profile/password`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({current_password: current, new_password: newPw})
    });
    const data = await res.json();
    if (!res.ok) return setStatus("passwordStatus", data.detail, false);
    document.getElementById("pwCurrent").value = "";
    document.getElementById("pwNew").value = "";
    setStatus("passwordStatus", "Password updated");
  } catch (e) {
    setStatus("passwordStatus", e.message, false);
  }
}

async function savePlayerId() {
  const raw = document.getElementById("profilePlayerId").value.trim();
  const player_id = raw ? parseInt(raw) : null;
  try {
    const res = await fetch(`${API}/profile/player-id`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_id})
    });
    const data = await res.json();
    if (!res.ok) return setStatus("playerIdStatus", data.detail, false);
    if (data.player_name) {
      showPlayerPreview(data.player_name, data.player_avatar_url);
      setStatus("playerIdStatus", "Player linked");
    } else if (player_id) {
      document.getElementById("profilePlayerPreview").style.display = "none";
      setStatus("playerIdStatus", "ID saved — player not found in current league data yet");
    } else {
      document.getElementById("profilePlayerPreview").style.display = "none";
      setStatus("playerIdStatus", "Player unlinked");
    }
  } catch (e) {
    setStatus("playerIdStatus", e.message, false);
  }
}

// -------------------------------------------------------
// TABS
// -------------------------------------------------------

function switchTab(name) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  const btn = document.getElementById(`tab-btn-${name}`);
  if (btn) btn.classList.add("active");

  if (name === "profile")       loadProfile();
  if (name === "team")        { loadDeck(); loadWeeks().then(() => loadRoster(_rosterWeekId)); }
  if (name === "leaderboard") {
    loadWeeks().then(() => { _populateLbWeekSelect(); switchLeaderboard(_lbMode); });
    loadLeaderboard(); loadTop();
  }
  if (name === "players")       loadPlayers();
  if (name === "teams")         loadTeams();
  if (name === "schedule")      loadSchedule();
  if (name === "admin")       { loadWeights(); loadUsers(); loadCodes(); }
}

// -------------------------------------------------------
// HELPERS
// -------------------------------------------------------

function setStatus(id, msg, ok = true) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = "status " + (ok ? "ok" : "err");
}

// -------------------------------------------------------
// DECK
// -------------------------------------------------------

async function loadDeck() {
  try {
    const res = await fetch(`${API}/deck`);
    const counts = await res.json();
    const rarities = ["common", "rare", "epic", "legendary"];
    let total = 0;
    for (const r of rarities) {
      const n = counts[r] ?? 0;
      document.getElementById(`deck-${r}`).textContent = n;
      total += n;
    }
    setStatus("deckStatus", total > 0 ? `${total} cards available` : "Deck is empty");
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}

async function drawCard() {
  try {
    const res = await fetch(`${API}/draw`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("deckStatus", data.detail, false);
    updateTokenDisplay(data.tokens ?? null);
    showReveal(data);
    loadDeck();
    loadRoster(_rosterWeekId);
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}

function toggleScoringInfo() {
  const el = document.getElementById("scoringInfo");
  if (el) el.style.display = el.style.display === "none" ? "" : "none";
}

async function redeemCode() {
  const code = document.getElementById("redeemCodeInput").value.trim().toUpperCase();
  if (!code) return setStatus("redeemStatus", "Enter a code", false);
  try {
    const res = await fetch(`${API}/redeem`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code}) });
    const data = await res.json();
    if (!res.ok) return setStatus("redeemStatus", data.detail, false);
    document.getElementById("redeemCodeInput").value = "";
    updateTokenDisplay(data.tokens ?? null);
    setStatus("redeemStatus", `+${data.granted} ${_tokenName}!`);
  } catch (e) {
    setStatus("redeemStatus", e.message, false);
  }
}

function showCard(card, footer) {
  document.getElementById("revealCard").className = `reveal-card ${card.card_type}`;
  document.getElementById("revealRarity").textContent = card.card_type;
  const revealAvatar = document.getElementById("revealAvatar");
  if (card.avatar_url) { revealAvatar.src = card.avatar_url; revealAvatar.style.display = ""; }
  else { revealAvatar.style.display = "none"; }
  document.getElementById("revealPlayer").textContent = card.player_name;
  document.getElementById("revealTeam").textContent = card.team_name || "";
  document.getElementById("revealDestination").textContent = footer || "";
  document.getElementById("revealModal").classList.remove("hidden");
}

function showReveal(card) {
  showCard(card, card.is_active ? "Added to active roster" : "Added to bench (roster full)");
}

function closeReveal() {
  document.getElementById("revealModal").classList.add("hidden");
}

// -------------------------------------------------------
// ROSTER
// -------------------------------------------------------

let _rosterCards = [];
let _weeks = [];
let _rosterWeekId = null; // null = current week (default)

function showRosterCard(cardId) {
  const c = _rosterCards.find(x => x.id === cardId);
  if (!c) return;
  const status = c.is_active ? "active" : "bench";
  showCard(c, `${Number(c.total_points).toFixed(1)} wk pts · ${status}`);
}

async function loadWeeks() {
  try {
    const res = await fetch(`${API}/weeks`);
    _weeks = await res.json();
    _renderWeekSelector();
  } catch (e) { /* weeks endpoint may not exist on older deploys */ }
}

function _renderWeekSelector() {
  const sel = document.getElementById("rosterWeekSelect");
  if (!sel || !_weeks.length) return;
  const now = Date.now() / 1000;
  // Next editable week = first week that hasn't started yet
  const nextWeek = _weeks.find(w => w.start_time > now);
  sel.innerHTML = _weeks.map(w => {
    const isLive   = w.is_locked && w.start_time <= now && w.end_time >= now;
    const isNext   = nextWeek && w.id === nextWeek.id;
    const label = w.is_locked
      ? (isLive ? `${w.label} (live)` : `${w.label} \u2713`)
      : (isNext ? `${w.label} (upcoming)` : w.label);
    const isSelected = _rosterWeekId === w.id || (_rosterWeekId === null && isNext);
    return `<option value="${w.id}"${isSelected ? " selected" : ""}>${label}</option>`;
  }).join("");
}

function onRosterWeekChange() {
  const sel = document.getElementById("rosterWeekSelect");
  _rosterWeekId = sel ? parseInt(sel.value) : null;
  loadRoster(_rosterWeekId);
}

async function loadRoster(weekId = null) {
  if (!activeUserId) return;
  try {
    const url = weekId != null
      ? `${API}/roster/${activeUserId}?week_id=${weekId}`
      : `${API}/roster/${activeUserId}`;
    const res = await fetch(url);
    const data = await res.json();
    const { active, bench, combined_value, tokens, season_points, week } = data;
    const isLocked = week?.is_locked ?? false;

    _rosterCards = [...active, ...bench];

    if (tokens !== undefined) updateTokenDisplay(tokens);

    const seasonEl = document.getElementById("rosterSeasonPoints");
    if (seasonEl) seasonEl.textContent = season_points !== undefined ? Number(season_points).toFixed(1) : "—";

    const counter = document.getElementById("drawCounter");
    if (counter) counter.textContent = tokens !== undefined ? `${tokens} ${_tokenName} remaining` : "";

    // Week status label
    const weekStatusEl = document.getElementById("rosterWeekStatus");
    if (weekStatusEl && week) {
      if (isLocked) {
        const now = Date.now() / 1000;
        const isLive = week.start_time <= now && week.end_time >= now;
        weekStatusEl.textContent = isLive ? "In progress" : "Locked";
        weekStatusEl.style.color = "#888";
      } else {
        const lockDate = new Date((week.start_time - 1) * 1000);
        const formatted = lockDate.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
        weekStatusEl.textContent = `Locks ${formatted}`;
        weekStatusEl.style.color = "#f0b429";
      }
    }

    // Locked banner
    const banner = document.getElementById("rosterLockedBanner");
    if (banner) {
      if (isLocked && week) {
        banner.textContent = `Roster locked — ${week.label} snapshot`;
        banner.style.display = "";
      } else {
        banner.style.display = "none";
      }
    }

    const activeBody = document.getElementById("rosterActive");
    if (!active.length) {
      activeBody.innerHTML = "<tr><td colspan='4' style='color:#444'>No active cards</td></tr>";
      document.getElementById("rosterCombined").textContent = "0.0";
    } else {
      activeBody.innerHTML = active.map(c => `
        <tr>
          <td><img src="${c.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" /><span class="entity-link" onclick="showRosterCard(${c.id})">${c.player_name}</span></td>
          <td><span class="badge ${c.card_type}">${c.card_type}</span></td>
          <td>${Number(c.total_points).toFixed(1)}</td>
          <td>${isLocked ? "" : `<button class="secondary" onclick="deactivateCard(${c.id})">Bench</button>`}</td>
        </tr>`).join("");
      document.getElementById("rosterCombined").textContent = Number(combined_value).toFixed(1);
    }

    const benchSection = document.getElementById("benchSection");
    const benchBody = document.getElementById("rosterBench");
    if (!isLocked && bench.length) {
      const rosterFull = active.length >= 5;
      benchSection.style.display = "";
      benchBody.innerHTML = bench.map(c => `
        <tr>
          <td><img src="${c.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" /><span class="entity-link" onclick="showRosterCard(${c.id})">${c.player_name}</span></td>
          <td><span class="badge ${c.card_type}">${c.card_type}</span></td>
          <td>${Number(c.total_points).toFixed(1)}</td>
          <td>${rosterFull
            ? `<span style="color:#444;font-size:0.8rem;">Roster full</span>`
            : `<button class="secondary" onclick="activateCard(${c.id})">Activate</button>`
          }</td>
        </tr>`).join("");
    } else {
      benchSection.style.display = "none";
    }

    setStatus("rosterStatus", isLocked ? "" : `${active.length}/5 active`);
  } catch (e) {
    setStatus("rosterStatus", e.message, false);
  }
}

async function activateCard(cardId) {
  try {
    const res = await fetch(`${API}/roster/${cardId}/activate`, { method: "POST" });
    const data = await res.json();
    if (res.ok) loadRoster(_rosterWeekId);
    else setStatus("rosterStatus", data.detail, false);
  } catch (e) {
    setStatus("rosterStatus", e.message, false);
  }
}

async function deactivateCard(cardId) {
  try {
    const res = await fetch(`${API}/roster/${cardId}/deactivate`, { method: "POST" });
    const data = await res.json();
    if (res.ok) loadRoster(_rosterWeekId);
    else setStatus("rosterStatus", data.detail, false);
  } catch (e) {
    setStatus("rosterStatus", e.message, false);
  }
}

// -------------------------------------------------------
// LEADERBOARDS
// -------------------------------------------------------

let _lbMode = "season";

function switchLeaderboard(mode) {
  _lbMode = mode;
  const seasonBtn = document.getElementById("lbSeasonBtn");
  const weeklyBtn = document.getElementById("lbWeeklyBtn");
  const weekSel   = document.getElementById("lbWeekSelect");
  const header    = document.getElementById("lbPtsHeader");
  if (seasonBtn) seasonBtn.className = mode === "season" ? "secondary" : "ghost";
  if (weeklyBtn) weeklyBtn.className = mode === "weekly"  ? "secondary" : "ghost";
  if (weekSel)   weekSel.style.display = mode === "weekly" ? "" : "none";
  if (header)    header.textContent = mode === "season" ? "Season pts" : "Week pts";
  if (mode === "season") {
    loadSeasonLeaderboard();
  } else {
    const sel = document.getElementById("lbWeekSelect");
    const weekId = sel ? parseInt(sel.value) : null;
    if (weekId) loadWeeklyLeaderboard(weekId);
  }
}

async function onLbWeekChange() {
  const sel = document.getElementById("lbWeekSelect");
  if (sel) loadWeeklyLeaderboard(parseInt(sel.value));
}

async function loadSeasonLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard/season`);
    const rows = await res.json();
    const tbody = document.getElementById("standingsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => {
      const isMe = activeUserId && String(r.id) === String(activeUserId);
      const style = isMe ? " style='color:#f0b429;font-weight:bold;'" : "";
      return `<tr${style}><td>${i + 1}</td><td>${r.username}</td><td>${Number(r.season_points).toFixed(1)}</td></tr>`;
    }).join("");
    setStatus("standingsStatus", "");
  } catch (e) {
    setStatus("standingsStatus", e.message, false);
  }
}

async function loadWeeklyLeaderboard(weekId) {
  try {
    const res = await fetch(`${API}/leaderboard/weekly?week_id=${weekId}`);
    const rows = await res.json();
    const tbody = document.getElementById("standingsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => {
      const isMe = activeUserId && String(r.id) === String(activeUserId);
      const style = isMe ? " style='color:#f0b429;font-weight:bold;'" : "";
      return `<tr${style}><td>${i + 1}</td><td>${r.username}</td><td>${Number(r.week_points).toFixed(1)}</td></tr>`;
    }).join("");
    setStatus("standingsStatus", "");
  } catch (e) {
    setStatus("standingsStatus", e.message, false);
  }
}

function _populateLbWeekSelect() {
  const sel = document.getElementById("lbWeekSelect");
  if (!sel || !_weeks.length) return;
  sel.innerHTML = _weeks.filter(w => w.is_locked).map(w =>
    `<option value="${w.id}">${w.label}</option>`
  ).join("");
  if (!sel.innerHTML) sel.innerHTML = "<option disabled>No locked weeks yet</option>";
}

async function loadLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard`);
    const rows = await res.json();
    const tbody = document.getElementById("leaderboardBody");
    if (!rows.length) { tbody.innerHTML = "<tr><td colspan='4' style='color:#444'>No data yet</td></tr>"; return; }
    tbody.innerHTML = rows.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td><img src="${r.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(r.id, r.name)}</td>
        <td>${r.matches}</td>
        <td>${Number(r.avg_points).toFixed(1)}</td>
      </tr>`).join("");
    setStatus("leaderboardStatus", "");
  } catch (e) {
    setStatus("leaderboardStatus", e.message, false);
  }
}

async function loadTop() {
  try {
    const res = await fetch(`${API}/top`);
    const rows = await res.json();
    document.getElementById("topBody").innerHTML = rows.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td><img src="${r.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(r.id, r.name)}</td>
        <td>${Number(r.fantasy_points).toFixed(1)}</td>
      </tr>`).join("");
    setStatus("topStatus", "");
  } catch (e) {
    setStatus("topStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — WEIGHTS
// -------------------------------------------------------

async function loadWeights() {
  try {
    const res = await fetch(`${API}/weights`);
    const weights = await res.json();
    document.getElementById("weightsBody").innerHTML = weights.map(w => `
      <tr>
        <td>${w.label}</td>
        <td><input type="number" step="any" id="w_${w.key}" value="${w.value}" style="width:100px;flex:none;" /></td>
        <td><button onclick="saveWeight('${w.key}')">Save</button></td>
      </tr>`).join("");
    setStatus("weightsStatus", "");
  } catch (e) {
    setStatus("weightsStatus", e.message, false);
  }
}

async function saveWeight(key) {
  const value = parseFloat(document.getElementById(`w_${key}`).value);
  if (isNaN(value)) return setStatus("weightsStatus", "Invalid value", false);
  try {
    const res = await fetch(`${API}/weights/${key}`, { method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({value}) });
    const data = await res.json();
    setStatus("weightsStatus", res.ok ? `Saved ${key} = ${data.value}` : data.detail, res.ok);
  } catch (e) {
    setStatus("weightsStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — USERS / TOKEN BALANCES
// -------------------------------------------------------

async function loadUsers() {
  try {
    const res = await fetch(`${API}/users`);
    const rows = await res.json();
    if (!res.ok) return setStatus("usersStatus", rows.detail, false);
    document.getElementById("usersBody").innerHTML = rows.map(u => `
      <tr>
        <td>${u.username}</td>
        <td>${u.tokens}</td>
        <td style="display:flex;gap:6px;align-items:center;">
          <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
          <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
        </td>
      </tr>`).join("");
    setStatus("usersStatus", "");
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function grantTokens(targetId) {
  const amount = parseInt(document.getElementById(`grant_${targetId}`).value);
  if (!amount || amount < 1) return setStatus("usersStatus", "Enter a valid amount", false);
  try {
    const res = await fetch(`${API}/grant-tokens`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({target_user_id: targetId, amount}) });
    const data = await res.json();
    setStatus("usersStatus", res.ok ? `${data.username} now has ${data.tokens} ${_tokenName}` : data.detail, res.ok);
    if (res.ok) loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — PROMO CODES
// -------------------------------------------------------

async function loadCodes() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/codes`);
    const rows = await res.json();
    if (!res.ok) return setStatus("codesStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("codesBody").innerHTML = "<tr><td colspan='4' style='color:#444'>No codes yet</td></tr>";
      return;
    }
    document.getElementById("codesBody").innerHTML = rows.map(c => `
      <tr>
        <td><code>${c.code}</code></td>
        <td>${c.token_amount}</td>
        <td>${c.redemptions}</td>
        <td><button class="ghost" style="font-size:0.8rem;" onclick="deleteCode(${c.id})">Delete</button></td>
      </tr>`).join("");
    setStatus("codesStatus", "");
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

async function createCode() {
  const code   = document.getElementById("newCodeInput").value.trim().toUpperCase();
  const amount = parseInt(document.getElementById("newCodeAmount").value);
  if (!code)        return setStatus("codesStatus", "Enter a code name", false);
  if (!amount || amount < 1) return setStatus("codesStatus", "Enter a token amount ≥ 1", false);
  try {
    const res = await fetch(`${API}/codes`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code, token_amount: amount}) });
    const data = await res.json();
    if (!res.ok) return setStatus("codesStatus", data.detail, false);
    document.getElementById("newCodeInput").value  = "";
    document.getElementById("newCodeAmount").value = "";
    setStatus("codesStatus", `Code ${data.code} created`);
    loadCodes();
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

async function deleteCode(codeId) {
  try {
    const res = await fetch(`${API}/codes/${codeId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("codesStatus", d.detail, false); }
    setStatus("codesStatus", "Code deleted");
    loadCodes();
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — INGEST / RECALCULATE / SCHEDULE REFRESH
// -------------------------------------------------------

async function refreshSchedule() {
  setStatus("scheduleRefreshStatus", "Refreshing...");
  try {
    const res = await fetch(`${API}/schedule/refresh`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("scheduleRefreshStatus", data.detail, false);
    const count = data.weeks?.length ?? 0;
    setStatus("scheduleRefreshStatus", count > 0 ? `Done. ${count} weeks loaded.` : (data.error || "No data returned"), count > 0);
  } catch (e) {
    setStatus("scheduleRefreshStatus", e.message, false);
  }
}

async function ingestLeague() {
  const id = document.getElementById("leagueId").value;
  if (!id) return setStatus("ingestStatus", "Enter a league ID", false);
  setStatus("ingestStatus", "Ingesting... this may take a while");
  try {
    const res = await fetch(`${API}/ingest/league/${id}`, { method: "POST" });
    const data = await res.json();
    setStatus("ingestStatus", res.ok ? `Done. League ${data.league_id} ingested.` : data.detail, res.ok);
  } catch (e) {
    setStatus("ingestStatus", e.message, false);
  }
}

async function recalculate() {
  setStatus("recalcStatus", "Recalculating...");
  try {
    const res = await fetch(`${API}/recalculate`, { method: "POST" });
    const data = await res.json();
    setStatus("recalcStatus", res.ok ? `Done. ${data.recalculated} records updated.` : data.detail, res.ok);
  } catch (e) {
    setStatus("recalcStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ENTITY LINKS
// -------------------------------------------------------

function playerLink(id, name) {
  return `<span class="entity-link" onclick="openPlayerModal(${id})">${name}</span>`;
}

function teamLink(id, name) {
  if (!id) return name || "—";
  return `<span class="entity-link" onclick="openTeamModal(${id})">${name}</span>`;
}

// -------------------------------------------------------
// PLAYERS TAB
// -------------------------------------------------------

let _playersData = [];

async function loadPlayers() {
  try {
    const res = await fetch(`${API}/players`);
    const rows = await res.json();
    _playersData = rows;
    renderPlayers(rows);
    setStatus("playersStatus", `${rows.length} players`);
  } catch (e) {
    setStatus("playersStatus", e.message, false);
  }
}

function filterPlayers() {
  const q = document.getElementById("playersSearch").value.toLowerCase();
  const filtered = _playersData.filter(p =>
    p.name.toLowerCase().includes(q) || (p.team_name || "").toLowerCase().includes(q)
  );
  renderPlayers(filtered);
}

function renderPlayers(rows) {
  const tbody = document.getElementById("playersBody");
  if (!rows.length) {
    tbody.innerHTML = "<tr><td colspan='5' style='color:#444'>No players found</td></tr>";
    return;
  }
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td><img src="${p.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(p.id, p.name)}</td>
      <td>${p.team_id ? teamLink(p.team_id, p.team_name) : (p.team_name || "—")}</td>
      <td>${p.matches}</td>
      <td>${Number(p.avg_points).toFixed(1)}</td>
      <td>${Number(p.total_points).toFixed(1)}</td>
    </tr>`).join("");
}

// -------------------------------------------------------
// TEAMS TAB
// -------------------------------------------------------

async function loadTeams() {
  try {
    const res = await fetch(`${API}/teams`);
    const rows = await res.json();
    const tbody = document.getElementById("teamsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No teams found</td></tr>";
      setStatus("teamsStatus", "");
      return;
    }
    tbody.innerHTML = rows.map(t => `
      <tr>
        <td>${teamLink(t.id, t.name)}</td>
        <td>${t.matches}</td>
        <td>${t.player_count}</td>
      </tr>`).join("");
    setStatus("teamsStatus", `${rows.length} teams`);
  } catch (e) {
    setStatus("teamsStatus", e.message, false);
  }
}

// -------------------------------------------------------
// PLAYER MODAL
// -------------------------------------------------------

async function openPlayerModal(playerId) {
  const modal = document.getElementById("playerModal");
  modal.classList.remove("hidden");
  document.getElementById("playerModalName").textContent = "Loading...";
  document.getElementById("playerModalTeam").innerHTML = "";
  document.getElementById("playerModalAvatar").style.display = "none";
  document.getElementById("playerModalStats").innerHTML = "";
  document.getElementById("playerModalHistory").innerHTML = "";
  document.getElementById("playerModalStatus").textContent = "";

  try {
    const res = await fetch(`${API}/players/${playerId}`);
    const p = await res.json();
    if (!res.ok) {
      document.getElementById("playerModalName").textContent = "";
      setStatus("playerModalStatus", p.detail || "Failed to load", false);
      return;
    }

    const avatar = document.getElementById("playerModalAvatar");
    if (p.avatar_url) { avatar.src = p.avatar_url; avatar.style.display = ""; }

    document.getElementById("playerModalName").textContent = p.name;
    document.getElementById("playerModalTeam").innerHTML = p.team_id
      ? `<span class="entity-link" onclick="closePlayerModal();openTeamModal(${p.team_id})">${p.team_name}</span>`
      : (p.team_name || "");

    document.getElementById("playerModalStats").innerHTML = `
      <div class="player-modal-stat-grid">
        <div class="player-modal-stat"><div class="val">${p.matches}</div><div class="lbl">Matches</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.avg_points).toFixed(1)}</div><div class="lbl">Avg pts</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.total_points).toFixed(1)}</div><div class="lbl">Total pts</div></div>
        ${p.best_match ? `<div class="player-modal-stat"><div class="val">${Number(p.best_match.fantasy_points).toFixed(1)}</div><div class="lbl">Best match</div></div>` : ""}
      </div>`;

    if (!p.match_history.length) {
      document.getElementById("playerModalHistory").innerHTML =
        "<tr><td colspan='6' style='color:#444'>No matches yet</td></tr>";
    } else {
      document.getElementById("playerModalHistory").innerHTML = p.match_history.map(m => {
        const date = m.start_time
          ? new Date(m.start_time * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "2-digit"})
          : "—";
        return `<tr>
          <td>${date}</td>
          <td>${Number(m.fantasy_points).toFixed(1)}</td>
          <td>${m.kills}/${m.assists}/${m.deaths}</td>
          <td>${Math.round(m.gold_per_min)}</td>
          <td>${m.obs_placed + m.sen_placed}</td>
          <td>${Math.round(m.tower_damage)}</td>
        </tr>`;
      }).join("");
    }
  } catch (e) {
    setStatus("playerModalStatus", e.message, false);
  }
}

function closePlayerModal() {
  document.getElementById("playerModal").classList.add("hidden");
}

// -------------------------------------------------------
// TEAM MODAL
// -------------------------------------------------------

async function openTeamModal(teamId) {
  const modal = document.getElementById("teamModal");
  modal.classList.remove("hidden");
  document.getElementById("teamModalName").textContent = "Loading...";
  document.getElementById("teamModalMeta").textContent = "";
  document.getElementById("teamModalPlayers").innerHTML = "";
  document.getElementById("teamModalStatus").textContent = "";

  try {
    const res = await fetch(`${API}/teams/${teamId}`);
    const t = await res.json();
    if (!res.ok) {
      document.getElementById("teamModalName").textContent = "";
      setStatus("teamModalStatus", t.detail || "Failed to load", false);
      return;
    }

    document.getElementById("teamModalName").textContent = t.name;
    document.getElementById("teamModalMeta").textContent = `${t.matches} matches`;

    if (!t.players.length) {
      document.getElementById("teamModalPlayers").innerHTML =
        "<tr><td colspan='4' style='color:#444'>No players found</td></tr>";
    } else {
      document.getElementById("teamModalPlayers").innerHTML = t.players.map(p => `
        <tr>
          <td><img src="${p.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" /><span class="entity-link" onclick="closeTeamModal();openPlayerModal(${p.id})">${p.name}</span></td>
          <td>${p.matches}</td>
          <td>${Number(p.avg_points).toFixed(1)}</td>
          <td>${Number(p.total_points).toFixed(1)}</td>
        </tr>`).join("");
    }
  } catch (e) {
    setStatus("teamModalStatus", e.message, false);
  }
}

function closeTeamModal() {
  document.getElementById("teamModal").classList.add("hidden");
}

// -------------------------------------------------------
// SCHEDULE
// -------------------------------------------------------

async function loadSchedule() {
  const content = document.getElementById("scheduleContent");
  const staleEl = document.getElementById("scheduleStale");
  content.innerHTML = "<span style='color:#444'>Loading...</span>";
  staleEl.style.display = "none";
  try {
    const res = await fetch(`${API}/schedule`);
    const data = await res.json();
    if (!res.ok) { setStatus("scheduleStatus", data.detail || "Failed to load", false); content.innerHTML = ""; return; }

    if (data.stale) {
      staleEl.textContent = `Cached data from ${data.cached_at ? new Date(data.cached_at).toLocaleString() : "unknown"}`;
      staleEl.style.display = "";
    }
    if (data.error && !data.weeks?.length) {
      content.innerHTML = `<span style='color:#555'>${data.error}</span>`;
      setStatus("scheduleStatus", "");
      return;
    }
    if (!data.weeks?.length) {
      content.innerHTML = "<span style='color:#555'>No schedule data available.</span>";
      setStatus("scheduleStatus", "");
      return;
    }

    // Flatten all weeks, both divisions; drop entries with no datetime
    const allSeries = [];
    for (const week of data.weeks) {
      for (const s of (week.div1 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div1"});
      for (const s of (week.div2 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div2"});
    }

    const upcoming = allSeries.filter(s => s.match_status !== "past")
                              .sort((a, b) => b.datetime_iso.localeCompare(a.datetime_iso));
    const past     = allSeries.filter(s => s.match_status === "past")
                              .sort((a, b) => b.datetime_iso.localeCompare(a.datetime_iso));

    const renderRow = s => {
      const isPast = s.match_status === "past";
      const divLabel = s.division === "div1"
        ? `<span class="badge badge-division div1">Div 1</span>`
        : `<span class="badge badge-division div2">Div 2</span>`;

      const r = s.series_result;
      const scoreHtml = r
        ? `<span class="series-score">${r.team1_wins}–${r.team2_wins}</span>`
        : `<span class="series-score no-result">vs</span>`;

      let meta;
      if (r && r.start_time) {
        const d = new Date(r.start_time * 1000);
        meta = d.toLocaleDateString("fi-FI", {day: "numeric", month: "numeric"})
             + " " + d.toLocaleTimeString("fi-FI", {hour: "2-digit", minute: "2-digit"});
      } else {
        meta = `${s.date || ""}${s.date && s.time ? " " : ""}${s.time || ""}`;
      }

      const streamHtml = s.stream_url
        ? `<a class="stream-link" href="${s.stream_url}" target="_blank" rel="noopener">${s.stream_label || "Watch"} ↗</a>`
        : (s.stream_label ? `<span style="color:#555;">${s.stream_label}</span>` : `<span></span>`);

      return `<div class="series-row${isPast ? " past" : ""}">
        ${divLabel}
        <span class="series-team">${s.team1_id ? teamLink(s.team1_id, s.team1) : (s.team1 || "—")}</span>
        ${scoreHtml}
        <span class="series-team right">${s.team2_id ? teamLink(s.team2_id, s.team2) : (s.team2 || "—")}</span>
        <span class="series-meta">${meta}</span>
        ${streamHtml}
      </div>`;
    };

    const upcomingHtml = upcoming.map(renderRow).join("");
    const pastHtml     = past.map(renderRow).join("");
    const divider      = upcoming.length && past.length
      ? `<div style="border-top:1px solid #2a2a2a;margin:16px 0 12px;"></div>`
      : "";

    content.innerHTML = upcomingHtml + divider + pastHtml;
    if (!allSeries.length) content.innerHTML = "<span style='color:#555'>No dated fixtures found.</span>";

    setStatus("scheduleStatus", "");
  } catch (e) {
    setStatus("scheduleStatus", e.message, false);
    content.innerHTML = "";
  }
}

// -------------------------------------------------------
// INIT
// -------------------------------------------------------

async function init() {
  await loadConfig();
  await loadMe();
  applyAuthState();
  if (!activeUserId) {
    showLogin();
  } else {
    loadDeck();
    loadWeeks().then(() => loadRoster(_rosterWeekId));
  }
  loadWeeks().then(() => { _populateLbWeekSelect(); loadSeasonLeaderboard(); });
  loadLeaderboard();
  loadTop();
}

init();
