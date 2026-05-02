var _allLeaderboardRows = [];

async function onLbWeekChange() {
  const sel = document.getElementById("lbWeekSelect");
  if (sel) loadWeeklyLeaderboard(parseInt(sel.value));
}

function toggleLbDetail(userId) {
  const el = document.getElementById(`lb-detail-${userId}`);
  if (el) el.classList.toggle("hidden");
}

function _lbStandingsRow(r, i, ptsKey, showCards = true) {
  const isMe = activeUserId && String(r.id) === String(activeUserId);
  const baseStyle = isMe ? "color:#f0b429;font-weight:bold;" : "";
  const youLabel = isMe ? ` <span style="font-size:0.75rem;opacity:0.7;font-weight:normal;">(You)</span>` : "";
  const cards = showCards ? (r.cards || []) : [];
  const hasCards = cards.length > 0;
  const cursorStyle = hasCards ? "cursor:pointer;" : "";
  const chevron = hasCards ? `<span class="lb-chevron" id="lb-chevron-${r.id}">›</span>` : "";
  const pts = Number(r[ptsKey] || 0).toFixed(1);
  const mainRow = `<tr style="${baseStyle}${cursorStyle}" ${hasCards ? `onclick="toggleLbDetail(${r.id})"` : ""}>
    <td>${i + 1}</td>
    <td>${_escHtml(r.username)}${youLabel}${chevron}</td>
    <td>${pts}</td>
  </tr>`;
  if (!hasCards) return mainRow;
  const breakdown = cards.map(c =>
    `<span class="lb-card-chip ${c.card_type}">${c.player_name} <span class="lb-chip-pts">${Number(c.points).toFixed(1)}</span></span>`
  ).join("");
  const detailRow = `<tr class="lb-card-detail hidden" id="lb-detail-${r.id}">
    <td colspan="3"><div class="lb-card-breakdown">${breakdown}</div></td>
  </tr>`;
  return mainRow + detailRow;
}

async function loadSeasonLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard/season`);
    const rows = await res.json();
    const tbody = document.getElementById("seasonStandingsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => _lbStandingsRow(r, i, "season_points", false)).join("");
    setStatus("seasonStandingsStatus", "");
  } catch (e) {
    setStatus("seasonStandingsStatus", e.message, false);
  }
}

async function loadWeeklyLeaderboard(weekId) {
  try {
    const res = await fetch(`${API}/leaderboard/weekly?week_id=${weekId}`);
    const rows = await res.json();
    const tbody = document.getElementById("weeklyStandingsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => _lbStandingsRow(r, i, "week_points")).join("");
    setStatus("weeklyStandingsStatus", "");
  } catch (e) {
    setStatus("weeklyStandingsStatus", e.message, false);
  }
}

function _populateLbWeekSelect() {
  const sel = document.getElementById("lbWeekSelect");
  if (!sel) return;
  const locked = _weeks.filter(w => w.is_locked);
  sel.innerHTML = locked.map(w => `<option value="${w.id}">${w.label}</option>`).join("");
  if (!locked.length) {
    sel.style.display = "none";
    const tbody = document.getElementById("weeklyStandingsBody");
    if (tbody) tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No weeks locked yet</td></tr>";
  } else {
    sel.style.display = "";
  }
}

async function loadLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard`);
    _allLeaderboardRows = await res.json();
    _renderLeaderboard(false);
    setStatus("leaderboardStatus", "");
  } catch (e) {
    setStatus("leaderboardStatus", e.message, false);
  }
}

function _renderLeaderboard(showAll) {
  const tbody = document.getElementById("leaderboardBody");
  const toggleBtn = document.getElementById("leaderboardToggle");
  const rows = _allLeaderboardRows;
  if (!rows.length) {
    tbody.innerHTML = "<tr><td colspan='4' style='color:#444'>No data yet</td></tr>";
    if (toggleBtn) toggleBtn.style.display = "none";
    return;
  }
  const visible = showAll ? rows : rows.slice(0, 10);
  tbody.innerHTML = visible.map((r, i) => `
    <tr>
      <td>${i + 1}</td>
      <td class="lb-name-cell"><div class="lb-name-inner"><img src="${r.avatar_url || ''}" style="width:20px;height:20px;border-radius:50%;flex-shrink:0" onerror="this.style.display='none'" />${playerLink(r.id, r.name)}</div></td>
      <td>${r.matches}</td>
      <td>${Number(r.avg_points).toFixed(1)}</td>
    </tr>`).join("");
  if (toggleBtn) {
    if (rows.length > 10) {
      toggleBtn.style.display = "";
      toggleBtn.textContent = showAll ? "Show less" : "Show all (" + rows.length + ")";
      toggleBtn.onclick = function() { _renderLeaderboard(!showAll); };
    } else {
      toggleBtn.style.display = "none";
    }
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
