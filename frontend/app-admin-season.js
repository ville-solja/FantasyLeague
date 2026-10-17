async function loadSeasonArchives() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/leaderboard/seasons`);
    const rows = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", rows.detail, false);
    const tbody = document.getElementById("seasonArchivesBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No archived seasons yet</td></tr>";
      return;
    }
    tbody.innerHTML = "";
    rows.forEach(s => {
      const tr = document.createElement("tr");
      const archived = new Date(s.archived_at * 1000).toLocaleString();
      tr.innerHTML = `<td>${_escHtml(s.season_label)}</td><td style="font-size:0.8rem;">${archived}</td><td>${s.user_count}</td>`;
      tbody.appendChild(tr);
    });
  } catch (e) {
    setStatus("seasonLifecycleStatus", e.message, false);
  }
}

// Issue 50: End Season opens a dialog that shows the awards and the Played count and
// asks for the Div 1 and Div 2 winning teams (players pre-ticked, a stand-in can be
// unticked, a player added by OpenDota id), then the typed END SEASON confirmation.
let _endSeasonPreview = null;

/**
 * Team <option>s for a division picker: that division's teams first (from the league
 * of their matches, "Lower" = Div 2), then every other team, since a team can play in
 * both. Shared by the End Season dialog and Mark champions.
 */
function teamOptionsForDivision(teams, division) {
  const inDiv = t => t.division === division || (t.divisions || []).includes(division);
  const opt = t => `<option value="${t.team_id}">${_escHtml(t.team_name)}</option>`;
  const first = teams.filter(inDiv), rest = teams.filter(t => !inDiv(t));
  if (!first.length || !rest.length) return teams.map(opt).join("");
  const label = division === "div2" ? "Div 2" : "Div 1";
  return `<optgroup label="${label}">${first.map(opt).join("")}</optgroup><optgroup label="Other teams">${rest.map(opt).join("")}</optgroup>`;
}
const _endSeasonPicks = { div1: [], div2: [] };   // [{account_id, name, checked}]

const _END_SEASON_AWARDS = [
  { kind: "most_points", name: "Most Points" },
  { kind: "best_average", name: "Best Average" },
  { kind: "best_match", name: "Best Single Match" },
  { kind: "fantasy_winner", name: "Fantasy Winner" },
];

async function endSeason() {
  const typed = document.getElementById("endSeasonLabel").value.trim();
  setStatus("seasonLifecycleStatus", "");
  try {
    const res = await fetch(`${API}/admin/season/accolades-preview`);
    const data = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", data.detail, false);
    _endSeasonPreview = data;
  } catch (e) {
    return setStatus("seasonLifecycleStatus", e.message, false);
  }
  const p = _endSeasonPreview;
  // Prefilled with the live season's label (current_season_label: the monitored leagues'
  // OpenDota names) unless the admin typed one beside the button; editable either way.
  document.getElementById("endSeasonDialogLabel").value = typed || p.season_label || "";
  document.getElementById("endSeasonAwards").innerHTML = _END_SEASON_AWARDS.map(({ kind, name }) => {
    const winners = (p.awards && p.awards[kind]) || [];
    const who = winners.length
      ? winners.map(w => _escHtml(w.player_name || w.username || "")).join(", ")
      : "None";
    const value = winners.length && winners[0].value != null ? `${Number(winners[0].value).toFixed(1)}` : "";
    return `<div class="end-season-award-row"><span>${name}</span><span>${who}</span><span class="end-season-num">${_escHtml(value)}</span></div>`;
  }).join("");
  document.getElementById("endSeasonPlayed").textContent = p.played_count
    ? `Played: ${p.played_count} players with a scored match`
    : "No scored matches: no awards or Played rows will be recorded.";
  ["div1", "div2"].forEach(div => {
    document.getElementById(`endSeasonTeam_${div}`).innerHTML = `<option value="">No champion yet</option>` + teamOptionsForDivision(p.teams || [], div);
    _endSeasonPicks[div] = [];
    _renderEndSeasonPlayers(div);
  });
  setStatus("endSeasonDialogStatus", "");
  _updateEndSeasonWarning();
  document.getElementById("endSeasonModal").classList.remove("hidden");
}

function closeEndSeasonDialog() {
  document.getElementById("endSeasonModal").classList.add("hidden");
}

function _endSeasonTeam(div) {
  const id = parseInt(document.getElementById(`endSeasonTeam_${div}`).value, 10);
  return ((_endSeasonPreview && _endSeasonPreview.teams) || []).find(t => t.team_id === id) || null;
}

/** Picking a team pre-ticks the players who played for it this season. */
function endSeasonPickTeam(div) {
  const team = _endSeasonTeam(div);
  _endSeasonPicks[div] = team ? team.players.map(p => ({ account_id: p.account_id, name: p.name, checked: true })) : [];
  _renderEndSeasonPlayers(div);
  _updateEndSeasonWarning();
}

function _renderEndSeasonPlayers(div) {
  document.getElementById(`endSeasonPlayers_${div}`).innerHTML = _endSeasonPicks[div].map((p, i) => `
    <label class="end-season-player"><input type="checkbox" ${p.checked ? "checked" : ""} onchange="endSeasonTogglePlayer('${div}', ${i}, this.checked)" /> ${_escHtml(p.name)} <span class="accolade-admin-id">${_escHtml(String(p.account_id))}</span></label>`).join("");
}

function endSeasonTogglePlayer(div, i, checked) {
  if (_endSeasonPicks[div][i]) _endSeasonPicks[div][i].checked = checked;
  _updateEndSeasonWarning();
}

function endSeasonAddPlayer(div) {
  const input = document.getElementById(`endSeasonAdd_${div}`);
  const raw = input.value.trim();
  if (!/^\d+$/.test(raw) || Number(raw) <= 0 || !Number.isSafeInteger(Number(raw))) {
    return setStatus("endSeasonDialogStatus", "OpenDota id must be a positive whole number", false);
  }
  const id = Number(raw);
  if (_endSeasonPicks[div].some(p => p.account_id === id)) return;
  let name = `Player ${id}`;
  for (const t of (_endSeasonPreview && _endSeasonPreview.teams) || []) {
    const hit = t.players.find(p => p.account_id === id);
    if (hit) { name = hit.name; break; }
  }
  _endSeasonPicks[div].push({ account_id: id, name, checked: true });
  input.value = "";
  _renderEndSeasonPlayers(div);
  _updateEndSeasonWarning();
}

/** [{division, team_name, player_account_ids}] for the divisions with a team and ticked players. */
function _endSeasonChampions() {
  return ["div1", "div2"].map(div => {
    const team = _endSeasonTeam(div);
    const ids = _endSeasonPicks[div].filter(p => p.checked).map(p => p.account_id);
    return team && ids.length ? { division: div, team_name: team.team_name, player_account_ids: ids } : null;
  }).filter(Boolean);
}

function _updateEndSeasonWarning() {
  document.getElementById("endSeasonChampWarning").hidden = _endSeasonChampions().length > 0;
}

async function confirmEndSeason() {
  const label = document.getElementById("endSeasonDialogLabel").value.trim();
  if (!label) return setStatus("endSeasonDialogStatus", "Enter a season label", false);
  const champions = _endSeasonChampions();
  const champNote = champions.length ? "" : " No champions recorded; add them in Player management.";
  closeEndSeasonDialog();
  const confirmText = await typedConfirm("season_end", `Archive the current standings and record the season's accolades as "${label}".${champNote}`);
  if (confirmText === null) return;
  try {
    const res = await adminFetch(`${API}/admin/season/end`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({season_label: label, champions, confirm: confirmText}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", data.detail, false);
    const extra = data.note ? ` ${data.note}.` : (data.warning ? ` ${data.warning}.` : "");
    setStatus("seasonLifecycleStatus", `Archived "${data.season_label}" (${data.archived_users} users, ${data.accolades} accolades, ${data.champions} champions).${extra}`);
    document.getElementById("endSeasonLabel").value = "";
    loadSeasonArchives();
    if (typeof loadSeasonAccolades === "function") loadSeasonAccolades();
  } catch (e) {
    setStatus("seasonLifecycleStatus", e.message, false);
  }
}

function openSeasonResetConfirm() {
  document.getElementById("seasonResetConfirmInput").value = "";
  document.getElementById("seasonResetModalStatus").textContent = "";
  document.getElementById("seasonResetModal").style.display = "flex";
}

function closeSeasonResetConfirm() {
  document.getElementById("seasonResetModal").style.display = "none";
}

async function confirmSeasonReset() {
  const typed = document.getElementById("seasonResetConfirmInput").value.trim();
  if (typed.toUpperCase() !== ADMIN_CONFIRM_PHRASES.season_reset) {
    document.getElementById("seasonResetModalStatus").textContent = `Type "${ADMIN_CONFIRM_PHRASES.season_reset}" to confirm.`;
    return;
  }
  try {
    const res = await adminFetch(`${API}/admin/season/reset`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({force: false, confirm: typed}),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById("seasonResetModalStatus").textContent = data.detail;
      return;
    }
    closeSeasonResetConfirm();
    setStatus("seasonLifecycleStatus", "Season reset complete");
    loadSeasonArchives();
    loadAdminWeeks();
    loadLeagues();
  } catch (e) {
    document.getElementById("seasonResetModalStatus").textContent = e.message;
  }
}
