const API = "";

let activeUserId   = localStorage.getItem("user_id");
let activeUsername = localStorage.getItem("username");
let activeIsAdmin  = localStorage.getItem("is_admin") === "true";

// -------------------------------------------------------
// AUTH
// -------------------------------------------------------

function applyAuthState() {
  const loggedIn = !!activeUserId;

  document.getElementById("headerUserLabel").textContent = loggedIn ? activeUsername : "";
  document.getElementById("headerLoginBtn").style.display  = loggedIn ? "none" : "";
  document.getElementById("headerLogoutBtn").style.display = loggedIn ? "" : "none";

  document.getElementById("tab-btn-team").style.display  = loggedIn ? "" : "none";
  document.getElementById("tab-btn-admin").style.display = (loggedIn && activeIsAdmin) ? "" : "none";

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

    activeUserId   = String(data.id);
    activeUsername = data.username;
    activeIsAdmin  = data.is_admin;

    localStorage.setItem("user_id",  activeUserId);
    localStorage.setItem("username", activeUsername);
    localStorage.setItem("is_admin", activeIsAdmin);

    document.getElementById("loginModal").classList.add("hidden");
    document.getElementById("loginPassword").value = "";
    applyAuthState();
    switchTab("team");
    loadDeck();
    loadRoster();
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

    setStatus("registerStatus", "Account created — you can now log in");
    document.getElementById("regUsername").value = "";
    document.getElementById("regEmail").value    = "";
    document.getElementById("regPassword").value = "";
    setTimeout(showLogin, 1200);
  } catch (e) {
    setStatus("registerStatus", e.message, false);
  }
}

function logout() {
  activeUserId = activeUsername = null;
  activeIsAdmin = false;
  localStorage.removeItem("user_id");
  localStorage.removeItem("username");
  localStorage.removeItem("is_admin");
  applyAuthState();
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

  if (name === "team")        { loadDeck(); loadRoster(); }
  if (name === "leaderboard") { loadRosterLeaderboard(); loadLeaderboard(); loadTop(); }
  if (name === "schedule")      loadSchedule();
  if (name === "admin")       { loadWeights(); loadUsers(); }
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
    const res = await fetch(`${API}/draw`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId)}) });
    const data = await res.json();
    if (!res.ok) return setStatus("deckStatus", data.detail, false);
    showReveal(data);
    loadDeck();
    loadRoster();
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}

function showReveal(card) {
  document.getElementById("revealCard").className = `reveal-card ${card.card_type}`;
  document.getElementById("revealRarity").textContent = card.card_type;
  const revealAvatar = document.getElementById("revealAvatar");
  if (card.avatar_url) { revealAvatar.src = card.avatar_url; revealAvatar.style.display = ""; }
  else { revealAvatar.style.display = "none"; }
  document.getElementById("revealPlayer").textContent = card.player_name;
  document.getElementById("revealTeam").textContent = card.team_name || "";
  document.getElementById("revealDestination").textContent =
    card.is_active ? "Added to active roster" : "Added to bench (roster full)";
  document.getElementById("revealModal").classList.remove("hidden");
}

function closeReveal() {
  document.getElementById("revealModal").classList.add("hidden");
}

// -------------------------------------------------------
// ROSTER
// -------------------------------------------------------

async function loadRoster() {
  if (!activeUserId) return;
  try {
    const res = await fetch(`${API}/roster/${activeUserId}`);
    const data = await res.json();
    const { active, bench, combined_value, draws_used, draw_limit } = data;
    const counter = document.getElementById("drawCounter");
    if (counter) counter.textContent = draws_used !== undefined ? `${draws_used} / ${draw_limit} draws used` : "";

    const activeBody = document.getElementById("rosterActive");
    if (!active.length) {
      activeBody.innerHTML = "<tr><td colspan='4' style='color:#444'>No active cards</td></tr>";
      document.getElementById("rosterCombined").textContent = "0.0";
    } else {
      activeBody.innerHTML = active.map(c => `
        <tr>
          <td><img src="${c.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${c.player_name}</td>
          <td><span class="badge ${c.card_type}">${c.card_type}</span></td>
          <td>${Number(c.total_points).toFixed(1)}</td>
          <td><button class="secondary" onclick="deactivateCard(${c.id})">Bench</button></td>
        </tr>`).join("");
      document.getElementById("rosterCombined").textContent = Number(combined_value).toFixed(1);
    }

    const benchSection = document.getElementById("benchSection");
    const benchBody = document.getElementById("rosterBench");
    const rosterFull = active.length >= 5;
    if (bench.length) {
      benchSection.style.display = "";
      benchBody.innerHTML = bench.map(c => `
        <tr>
          <td><img src="${c.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${c.player_name}</td>
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

    setStatus("rosterStatus", `${active.length}/5 active`);
  } catch (e) {
    setStatus("rosterStatus", e.message, false);
  }
}

async function activateCard(cardId) {
  try {
    const res = await fetch(`${API}/roster/${cardId}/activate`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId)}) });
    const data = await res.json();
    if (res.ok) loadRoster();
    else setStatus("rosterStatus", data.detail, false);
  } catch (e) {
    setStatus("rosterStatus", e.message, false);
  }
}

async function deactivateCard(cardId) {
  try {
    const res = await fetch(`${API}/roster/${cardId}/deactivate`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId)}) });
    const data = await res.json();
    if (res.ok) loadRoster();
    else setStatus("rosterStatus", data.detail, false);
  } catch (e) {
    setStatus("rosterStatus", e.message, false);
  }
}

// -------------------------------------------------------
// LEADERBOARDS
// -------------------------------------------------------

async function loadRosterLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard/roster`);
    const rows = await res.json();
    const tbody = document.getElementById("rosterLeaderboardBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='4' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${r.username}</td>
        <td>${r.total_cards}</td>
        <td>${Number(r.roster_value).toFixed(1)}</td>
      </tr>`).join("");
    setStatus("rosterLeaderboardStatus", "");
  } catch (e) {
    setStatus("rosterLeaderboardStatus", e.message, false);
  }
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
        <td><img src="${r.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${r.name}</td>
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
        <td><img src="${r.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${r.name}</td>
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
// ADMIN — USERS / DRAW LIMITS
// -------------------------------------------------------

async function loadUsers() {
  try {
    const res = await fetch(`${API}/users?user_id=${activeUserId}`);
    const rows = await res.json();
    if (!res.ok) return setStatus("usersStatus", rows.detail, false);
    document.getElementById("usersBody").innerHTML = rows.map(u => `
      <tr>
        <td>${u.username}</td>
        <td>${u.draws_used}</td>
        <td>${u.draw_limit}</td>
        <td style="display:flex;gap:6px;align-items:center;">
          <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
          <button class="secondary" onclick="grantDraws(${u.id})">Grant</button>
        </td>
      </tr>`).join("");
    setStatus("usersStatus", "");
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function grantDraws(targetId) {
  const amount = parseInt(document.getElementById(`grant_${targetId}`).value);
  if (!amount || amount < 1) return setStatus("usersStatus", "Enter a valid amount", false);
  try {
    const res = await fetch(`${API}/grant-draws`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId), target_user_id: targetId, amount}) });
    const data = await res.json();
    setStatus("usersStatus", res.ok ? `${data.username} now has limit ${data.draw_limit}` : data.detail, res.ok);
    if (res.ok) loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — INGEST / RECALCULATE / SCHEDULE REFRESH
// -------------------------------------------------------

async function refreshSchedule() {
  setStatus("scheduleRefreshStatus", "Refreshing...");
  try {
    const res = await fetch(`${API}/schedule/refresh`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId)}) });
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
    const res = await fetch(`${API}/ingest/league/${id}`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId)}) });
    const data = await res.json();
    setStatus("ingestStatus", res.ok ? `Done. League ${data.league_id} ingested.` : data.detail, res.ok);
  } catch (e) {
    setStatus("ingestStatus", e.message, false);
  }
}

async function recalculate() {
  setStatus("recalcStatus", "Recalculating...");
  try {
    const res = await fetch(`${API}/recalculate`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: parseInt(activeUserId)}) });
    const data = await res.json();
    setStatus("recalcStatus", res.ok ? `Done. ${data.recalculated} records updated.` : data.detail, res.ok);
  } catch (e) {
    setStatus("recalcStatus", e.message, false);
  }
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
        <span class="series-team">${s.team1 || "—"}</span>
        ${scoreHtml}
        <span class="series-team right">${s.team2 || "—"}</span>
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

function init() {
  applyAuthState();
  if (!activeUserId) {
    showLogin();
  } else {
    loadDeck();
    loadRoster();
  }
  loadLeaderboard();
  loadTop();
}

init();
