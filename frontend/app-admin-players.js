let _playerPoolRows = [];

async function loadPlayerPool() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/players`);
    const rows = await res.json();
    if (!res.ok) return setStatus("playerPoolStatus", rows.detail, false);
    _playerPoolRows = rows;
    _renderPlayerPool(rows);
    setStatus("playerPoolStatus", "");
    loadSeasonAccolades();
    // Issue 50: the pool marker shows each player's titles.
    loadAccolades(true).then(() => _renderPlayerPool(_playerPoolRows));
  } catch (e) {
    setStatus("playerPoolStatus", e.message, false);
  }
}

function _renderPlayerPool(rows) {
  const search = (document.getElementById("playerPoolSearch")?.value || "").toLowerCase();
  const visible = search
    ? rows.filter(p => p.name.toLowerCase().includes(search) || (p.team_name || "").toLowerCase().includes(search) || String(p.id).includes(search))
    : rows;
  const tbody = document.getElementById("playerPoolBody");
  if (!visible.length) {
    tbody.innerHTML = `<tr><td colspan='6' style='color:#444'>${search ? "No matches" : "No players in pool"}</td></tr>`;
    _updateRemoveBtn();
    return;
  }
  tbody.innerHTML = visible.map(p => `
    <tr data-player-id="${p.id}" data-player-name="${_escHtml(p.name)}">
      <td><input type="checkbox" class="player-pool-cb" onchange="_updateRemoveBtn()" /></td>
      <td><img draggable="false" src="${_imgSrc(p.avatar_url)}" style="width:20px;height:20px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${_escHtml(p.name)}${_poolMarkerHtml(p.id)}</td>
      <td>${_escHtml(p.team_name || "—")}</td>
      <td style="font-size:0.8rem;color:#888;">${p.id}</td>
      <td>${p.active_card_count}</td>
      <td>${p.is_active ? "" : "<span style='color:#888;font-size:0.75rem;'>INACTIVE</span>"}</td>
    </tr>`).join("");
  _updateRemoveBtn();
  refreshAccoladeIcons();
}

/** Issue 50: a pool player's titles as chips (pips at phone width). */
function _poolMarkerHtml(playerId) {
  const titles = playerAccolades(playerId).filter(a => a.kind !== "played");
  if (!titles.length) return "";
  return ` <span class="accolade-swap">${accoladeChipsHtml(titles)}${accoladePipsHtml(titles)}</span>`;
}

function filterPlayerPool() {
  _renderPlayerPool(_playerPoolRows);
}

function _updateRemoveBtn() {
  const btn = document.getElementById("removePlayersBtn");
  if (!btn) return;
  const checked = document.querySelectorAll(".player-pool-cb:checked").length;
  btn.disabled = checked === 0;
}

function openAddPlayerPopup() {
  document.getElementById("addPlayerModal").classList.remove("hidden");
  setStatus("addPlayerStatus", "");
  document.getElementById("addPlayerIdInput").value = "";
}

function closeAddPlayerPopup() {
  document.getElementById("addPlayerModal").classList.add("hidden");
}

async function addPlayer() {
  const idVal = document.getElementById("addPlayerIdInput").value.trim();
  if (!idVal) return setStatus("addPlayerStatus", "Enter an OpenDota account ID", false);
  const player_id = parseInt(idVal, 10);
  if (isNaN(player_id)) return setStatus("addPlayerStatus", "ID must be an integer", false);
  const confirmBtn = document.getElementById("addPlayerConfirmBtn");
  const closeBtn = document.getElementById("addPlayerCloseBtn");
  const input = document.getElementById("addPlayerIdInput");
  if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = "Adding…"; }
  if (closeBtn) closeBtn.disabled = true;
  if (input) input.disabled = true;
  try {
    const res = await fetch(`${API}/admin/players`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_id}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("addPlayerStatus", data.detail, false);
    setStatus("addPlayerStatus", `Added: ${data.name} (${data.id})`);
    document.getElementById("addPlayerIdInput").value = "";
    loadPlayerPool();
  } catch (e) {
    setStatus("addPlayerStatus", e.message, false);
  } finally {
    if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "Confirm"; }
    if (closeBtn) closeBtn.disabled = false;
    if (input) input.disabled = false;
  }
}

function openBulkAddPlayersPopup() {
  document.getElementById("bulkAddPlayersModal").classList.remove("hidden");
  setStatus("bulkAddPlayersStatus", "");
  document.getElementById("bulkAddIdsInput").value = "";
  _resetBulkAddProgress();
}

function closeBulkAddPlayersPopup() {
  document.getElementById("bulkAddPlayersModal").classList.add("hidden");
}

function _resetBulkAddProgress() {
  const panel = document.getElementById("bulkAddProgressPanel");
  const list = document.getElementById("bulkAddProgressList");
  const counter = document.getElementById("bulkAddProgressCounter");
  if (panel) panel.classList.add("hidden");
  if (list) list.innerHTML = "";
  if (counter) counter.textContent = "";
}

const _bulkAddStatusLabel = { added: "Added", skipped: "Skipped", error: "Failed", pending: "Pending" };

function renderBulkAddProgress(evt) {
  const list = document.getElementById("bulkAddProgressList");
  if (!list) return;
  const label = _bulkAddStatusLabel[evt.status] || evt.status;
  const reason = evt.reason ? ` — ${_escHtml(evt.reason)}` : "";
  let row = list.querySelector(`li[data-progress-id="${evt.id}"]`);
  if (!row) {
    row = document.createElement("li");
    row.dataset.progressId = evt.id;
    list.appendChild(row);
  }
  row.textContent = "";
  row.innerHTML = `${_escHtml(String(evt.id))}: <span class="bulk-add-status-${evt.status}">${label}</span>${reason}`;
  const counter = document.getElementById("bulkAddProgressCounter");
  if (counter) counter.textContent = `${evt.index} of ${evt.total} processed`;
}

async function bulkAddPlayers() {
  const csv = document.getElementById("bulkAddIdsInput").value.trim();
  if (!csv) return setStatus("bulkAddPlayersStatus", "Enter at least one ID", false);
  const confirmBtn = document.getElementById("bulkAddConfirmBtn");
  const input = document.getElementById("bulkAddIdsInput");
  // Guards against a second overlapping stream writing into the same progress
  // panel — the Cancel button stays enabled since hiding the popup does not
  // abort the in-flight request; it keeps streaming and refreshes the table
  // when done regardless of whether the modal is visible.
  if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = "Adding…"; }
  if (input) input.disabled = true;
  _resetBulkAddProgress();
  const panel = document.getElementById("bulkAddProgressPanel");
  if (panel) panel.classList.remove("hidden");
  try {
    const res = await fetch(`${API}/admin/players/bulk`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_ids: csv}),
    });
    if (!res.ok) {
      const data = await res.json();
      return setStatus("bulkAddPlayersStatus", data.detail, false);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let summary = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // last (possibly incomplete) line stays in buffer
      for (const line of lines) {
        if (!line) continue;
        const evt = JSON.parse(line);
        if (evt.done) { summary = evt; } else { renderBulkAddProgress(evt); }
      }
    }
    if (!summary) return setStatus("bulkAddPlayersStatus", "Stream ended unexpectedly", false);
    const msg = `Added: ${summary.added}. Skipped: ${summary.skipped.length}.`;
    setStatus("bulkAddPlayersStatus", msg);
    if (summary.added > 0) loadPlayerPool();
  } catch (e) {
    setStatus("bulkAddPlayersStatus", e.message, false);
  } finally {
    if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "Confirm"; }
    if (input) input.disabled = false;
  }
}

function openRemovePlayersConfirm() {
  const checked = document.querySelectorAll(".player-pool-cb:checked");
  if (!checked.length) return;
  const names = Array.from(checked).map(cb => {
    const row = cb.closest("tr");
    return row ? row.dataset.playerName : "Unknown";
  });
  document.getElementById("removePlayersNames").textContent = names.join(", ");
  document.getElementById("removePlayersModal").classList.remove("hidden");
  setStatus("removePlayersStatus", "");
}

function closeRemovePlayersConfirm() {
  document.getElementById("removePlayersModal").classList.add("hidden");
}

async function removeSelectedPlayers() {
  const checked = document.querySelectorAll(".player-pool-cb:checked");
  const player_ids = Array.from(checked).map(cb => {
    const row = cb.closest("tr");
    return row ? parseInt(row.dataset.playerId, 10) : null;
  }).filter(id => id !== null);
  if (!player_ids.length) return;
  try {
    const res = await fetch(`${API}/admin/players/remove`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_ids}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("removePlayersStatus", data.detail, false);
    setStatus("removePlayersStatus", "Players removed and refunds issued");
    closeRemovePlayersConfirm();
    loadPlayerPool();
  } catch (e) {
    setStatus("removePlayersStatus", e.message, false);
  }
}


// ---------------------------------------------------------------------------
// Champions and accolades (issue 50)
// ---------------------------------------------------------------------------

let _accoladeRows = [];
let _champPreview = null;   // GET /admin/season/accolades-preview (live season and teams)
let _champMode = "current";

async function loadSeasonAccolades() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/season-accolades`);
    const rows = await res.json();
    if (!res.ok) return setStatus("accoladeAdminStatus", rows.detail, false);
    _accoladeRows = rows;
    _renderAccoladeTable(rows);
    setStatus("accoladeAdminStatus", "");
  } catch (e) {
    setStatus("accoladeAdminStatus", e.message, false);
  }
}

/** Champion rows of one season and division collapse into one "[Team] · N players" row. */
function _accoladeTableRows(rows) {
  const out = [];
  const groups = new Map();
  for (const r of rows) {
    if (r.kind !== "champion") { out.push({ type: "row", row: r }); continue; }
    const key = `${r.season_label}\u0000${r.division}`;
    if (!groups.has(key)) {
      const g = { type: "champions", season_label: r.season_label, season_short: r.season_short,
                  division: r.division, team_name: r.team_name, players: [] };
      groups.set(key, g);
      out.push(g);
    }
    groups.get(key).players.push({ account_id: r.player_account_id, name: r.player_name });
  }
  return out;
}

function _accoladeChipFor(r) {
  return accoladeChipsHtml([{ kind: r.kind, division: r.division, season: r.season_label,
                              season_short: r.season_short, team_name: r.team_name }]);
}

function _renderAccoladeTable(rows) {
  const tbody = document.getElementById("accoladeAdminBody");
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = "<tr><td colspan='6' style='color:#444'>No champions or accolades yet</td></tr>";
    return;
  }
  tbody.innerHTML = _accoladeTableRows(rows).map((item, i) => {
    if (item.type === "champions") {
      const chip = _accoladeChipFor({ kind: "champion", division: item.division,
                                      season_label: item.season_label, season_short: item.season_short });
      const n = item.players.length;
      return `<tr data-champ-index="${i}">
        <td>${_escHtml(item.season_label)}</td>
        <td><span class="accolade-swap">${chip}</span></td>
        <td>${_escHtml(item.team_name || "")} · ${n} player${n === 1 ? "" : "s"}</td>
        <td></td>
        <td></td>
        <td class="accolade-admin-actions"><button class="secondary" onclick="editChampionSet(${i})">Edit</button> <button class="danger" onclick="removeChampionSet(${i})">Remove</button></td>
      </tr>`;
    }
    const r = item.row;
    const winner = r.kind === "fantasy_winner" ? _escHtml(r.username || "") : `${_escHtml(r.player_name || "")} <span class="accolade-admin-id">${_escHtml(String(r.player_account_id ?? ""))}</span>`;
    const value = r.value == null ? "" : _escHtml(Number(r.value).toFixed(1));
    return `<tr data-accolade-id="${r.id}">
      <td>${_escHtml(r.season_label)}</td>
      <td><span class="accolade-swap">${_accoladeChipFor(r)}</span></td>
      <td>${winner}</td>
      <td class="accolade-admin-num">${value}</td>
      <td>${_escHtml(r.source)}</td>
      <td class="accolade-admin-actions"><button class="secondary" onclick="editAccoladeValue(${r.id})">Edit</button> <button class="danger" onclick="removeAccolade(${r.id})">Remove</button></td>
    </tr>`;
  }).join("");
  refreshAccoladeIcons();
}

function _champGroup(i) {
  return _accoladeTableRows(_accoladeRows)[i];
}

async function editChampionSet(i) {
  const g = _champGroup(i);
  if (!g || g.type !== "champions") return;
  await openMarkChampions({ season_label: g.season_label, division: g.division,
                            team_name: g.team_name, players: g.players });
}

async function removeChampionSet(i) {
  const g = _champGroup(i);
  if (!g || g.type !== "champions") return;
  if (!confirm(`Remove all ${g.players.length} ${g.division === "div2" ? "Div 2" : "Div 1"} champions of ${g.season_label} (${g.team_name || "no team"})?`)) return;
  const res = await adminFetch(`${API}/admin/season-champions`, {
    method: "PUT", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ season_label: g.season_label, division: g.division, team_name: g.team_name || "", players: [] }),
  });
  const data = await res.json();
  if (!res.ok) return setStatus("accoladeAdminStatus", data.detail, false);
  setStatus("accoladeAdminStatus", `Removed ${data.removed} champions`);
  _afterAccoladeChange();
}

async function editAccoladeValue(id) {
  const row = _accoladeRows.find(r => r.id === id);
  if (!row) return;
  const raw = prompt("Value (empty to keep)", row.value == null ? "" : String(row.value));
  if (raw === null) return;
  const body = {};
  if (raw.trim() !== "") {
    const v = Number(raw);
    if (!Number.isFinite(v)) return setStatus("accoladeAdminStatus", "Value must be a number", false);
    body.value = v;
  }
  const nameField = row.kind === "fantasy_winner" ? "username" : "player_name";
  const name = prompt("Name", row[nameField] || "");
  if (name === null) return;
  if (name.trim() && name.trim() !== row[nameField]) body[nameField] = name.trim();
  if (!Object.keys(body).length) return;
  const res = await adminFetch(`${API}/admin/season-accolades/${id}`, {
    method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) return setStatus("accoladeAdminStatus", data.detail, false);
  setStatus("accoladeAdminStatus", "Accolade updated");
  _afterAccoladeChange();
}

async function removeAccolade(id) {
  const row = _accoladeRows.find(r => r.id === id);
  if (!row || !confirm(`Remove ${row.season_label} ${row.kind.replace(/_/g, " ")} (${row.player_name || row.username || ""})?`)) return;
  const res = await adminFetch(`${API}/admin/season-accolades/${id}`, { method: "DELETE" });
  const data = await res.json();
  if (!res.ok) return setStatus("accoladeAdminStatus", data.detail, false);
  setStatus("accoladeAdminStatus", "Accolade removed");
  _afterAccoladeChange();
}

function _afterAccoladeChange() {
  loadSeasonAccolades();
  loadAccolades(true).then(() => _renderPlayerPool(_playerPoolRows));
}

// --- Mark champions --------------------------------------------------------

/**
 * Checks the roster editor's rows ([{account_id, name}] as typed): every id a
 * positive whole number, each id once, every row named. Returns the message to show,
 * or null when the list can be saved.
 */
function validateChampionRoster(rows) {
  const seen = new Set();
  for (const r of rows) {
    const raw = String(r.account_id ?? "").trim();
    if (!/^\d+$/.test(raw) || !Number.isSafeInteger(Number(raw)) || Number(raw) <= 0) {
      return `OpenDota id "${raw}" must be a positive whole number`;
    }
    if (seen.has(Number(raw))) return `OpenDota id ${raw} is listed twice`;
    seen.add(Number(raw));
    if (!String(r.name ?? "").trim()) return `Player ${raw} needs a name`;
  }
  return null;
}

/** A name for an OpenDota id: the pool's, else from earlier accolade rows. */
function _knownPlayerName(id) {
  const n = Number(id);
  const pool = _playerPoolRows.find(p => p.id === n);
  if (pool && pool.name) return pool.name;
  const earlier = _accoladeRows.find(r => r.player_account_id === n && r.player_name);
  return earlier ? earlier.player_name : "";
}

async function _loadChampPreview() {
  try {
    const res = await fetch(`${API}/admin/season/accolades-preview`);
    if (res.ok) _champPreview = await res.json();
  } catch (_) { /* past-season mode still works */ }
  return _champPreview;
}

function _currentSeasonNumber() {
  return _champPreview ? _seasonNumber(_champPreview.season_label) : null;
}

function _fillChampSeasons() {
  const sel = document.getElementById("champSeason");
  const current = _champPreview ? _champPreview.season_label : "";
  let labels;
  if (_champMode === "current") {
    labels = current ? [current] : [];
  } else {
    const n = _currentSeasonNumber();
    labels = [];
    for (let i = (n || 1) - 1; i >= 1; i--) labels.push(`Season ${i}`);
    _accoladeRows.forEach(r => { if (r.season_label !== current && !labels.includes(r.season_label)) labels.push(r.season_label); });
  }
  sel.innerHTML = labels.map(l => `<option value="${_escHtml(l)}">${_escHtml(l)}</option>`).join("");
}

function setChampMode(mode) {
  _champMode = mode === "past" ? "past" : "current";
  document.querySelectorAll('input[name="champMode"]').forEach(r => { r.checked = r.value === _champMode; });
  document.getElementById("champTeamPickWrap").hidden = _champMode !== "current";
  _fillChampSeasons();
  if (_champMode === "current") _fillChampTeams();
}

/** From this season: the division's teams first (teamOptionsForDivision). */
function _fillChampTeams() {
  const teams = (_champPreview && _champPreview.teams) || [];
  const division = document.getElementById("champDivision").value;
  document.getElementById("champTeamPick").innerHTML = `<option value="">Pick a team…</option>` +
    teamOptionsForDivision(teams, division);
}

/** From this season: a team's players for the season fill the roster (editable). */
function champPickTeam() {
  const id = parseInt(document.getElementById("champTeamPick").value, 10);
  const team = ((_champPreview && _champPreview.teams) || []).find(t => t.team_id === id);
  if (!team) return;
  document.getElementById("champTeamName").value = team.team_name;
  _setChampRoster(team.players.map(p => ({ account_id: p.account_id, name: p.name })));
}

function _champRosterRows() {
  return [...document.querySelectorAll("#champRoster .champ-row")].map(row => ({
    account_id: row.querySelector(".champ-id").value,
    name: row.querySelector(".champ-name").value,
  }));
}

function _champRowHtml(r) {
  return `<div class="champ-row">
    <input class="champ-id" type="text" inputmode="numeric" aria-label="OpenDota id" placeholder="OpenDota id" value="${_escHtml(String(r.account_id ?? ""))}" oninput="champIdTyped(this)" />
    <input class="champ-name" type="text" maxlength="100" aria-label="Player name" placeholder="Name" value="${_escHtml(r.name || "")}" />
    <button type="button" class="ghost" onclick="champRemoveRow(this)">Remove</button>
  </div>`;
}

function _setChampRoster(rows) {
  document.getElementById("champRoster").innerHTML = rows.map(_champRowHtml).join("");
  _updateChampCount();
}

function _updateChampCount() {
  const n = _champRosterRows().length;
  document.getElementById("champCountNote").textContent =
    n === 5 ? "5 players" : `${n} player${n === 1 ? "" : "s"} (usually 5)`;
}

function champAddRow() {
  document.getElementById("champRoster").insertAdjacentHTML("beforeend", _champRowHtml({}));
  _updateChampCount();
}

function champRemoveRow(btn) {
  const row = btn.closest(".champ-row");
  if (row) row.remove();
  _updateChampCount();
}

/** Typing an id fills an empty name from the pool or earlier accolades. */
function champIdTyped(input) {
  const nameEl = input.closest(".champ-row").querySelector(".champ-name");
  if (!nameEl.value.trim()) nameEl.value = _knownPlayerName(input.value.trim());
}

/** "<id> <name>" per line into roster rows. */
function _parsePlayerLines(text) {
  return String(text || "").split(/\r?\n/).map(l => l.trim()).filter(Boolean).map(l => {
    const m = /^(\S+)\s*(.*)$/.exec(l);
    return { account_id: m[1], name: m[2].trim() || _knownPlayerName(m[1]) };
  });
}

function champApplyPaste() {
  const el = document.getElementById("champPaste");
  const rows = _champRosterRows().filter(r => String(r.account_id).trim() || String(r.name).trim());
  _setChampRoster(rows.concat(_parsePlayerLines(el.value)));
  el.value = "";
}

/** Opens the form; preset = {season_label, division, team_name, players} edits a saved set. */
async function openMarkChampions(preset) {
  document.getElementById("markChampionsModal").classList.remove("hidden");
  setStatus("champStatus", "");
  document.getElementById("champPaste").value = "";
  await _loadChampPreview();
  const current = _champPreview ? _champPreview.season_label : "";
  const past = preset && preset.season_label !== current;
  setChampMode(past ? "past" : "current");
  if (preset) {
    const sel = document.getElementById("champSeason");
    if (![...sel.options].some(o => o.value === preset.season_label)) {
      sel.insertAdjacentHTML("afterbegin", `<option value="${_escHtml(preset.season_label)}">${_escHtml(preset.season_label)}</option>`);
    }
    sel.value = preset.season_label;
    document.getElementById("champDivision").value = preset.division;
    document.getElementById("champTeamName").value = preset.team_name || "";
    _setChampRoster(preset.players);
  } else {
    document.getElementById("champTeamName").value = "";
    _setChampRoster([]);
  }
}

function closeMarkChampions() {
  document.getElementById("markChampionsModal").classList.add("hidden");
}

/** Saving replaces this season and division's champions with the list shown. */
async function saveChampions() {
  const rows = _champRosterRows();
  const problem = validateChampionRoster(rows);
  if (problem) return setStatus("champStatus", problem, false);
  const season_label = document.getElementById("champSeason").value;
  const team_name = document.getElementById("champTeamName").value.trim();
  if (!season_label) return setStatus("champStatus", "Pick a season", false);
  if (rows.length && !team_name) return setStatus("champStatus", "Enter the team name", false);
  const btn = document.getElementById("champSaveBtn");
  await withBusy(btn, async () => {
    try {
      const res = await adminFetch(`${API}/admin/season-champions`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          season_label, team_name, division: document.getElementById("champDivision").value,
          players: rows.map(r => ({ account_id: Number(String(r.account_id).trim()), name: String(r.name).trim() })),
        }),
      });
      const data = await res.json();
      if (!res.ok) return setStatus("champStatus", data.detail, false);
      setStatus("champStatus", `Saved: ${data.players} players (${data.added} added, ${data.removed} removed)`);
      _afterAccoladeChange();
    } catch (e) {
      setStatus("champStatus", e.message, false);
    }
  });
}

// --- Add accolade ----------------------------------------------------------

async function openAddAccolade() {
  document.getElementById("addAccoladeModal").classList.remove("hidden");
  setStatus("accStatus", "");
  ["accPlayerId", "accPlayerName", "accUsername", "accValue", "accBulk"].forEach(id => { document.getElementById(id).value = ""; });
  await _loadChampPreview();
  const n = _currentSeasonNumber();
  document.getElementById("accSeason").value = n && n > 1 ? `Season ${n - 1}` : "";
  accKindChanged();
}

function closeAddAccolade() {
  document.getElementById("addAccoladeModal").classList.add("hidden");
}

function accKindChanged() {
  const kind = document.getElementById("accKind").value;
  const isUser = kind === "fantasy_winner";
  const isPlayed = kind === "played";
  document.getElementById("accUserWrap").hidden = !isUser;
  document.getElementById("accPlayerWrap").hidden = isUser || isPlayed;
  document.getElementById("accNameWrap").hidden = isUser || isPlayed;
  document.getElementById("accValueWrap").hidden = isPlayed;
  document.getElementById("accBulkWrap").hidden = !isPlayed;
}

function accFillName() {
  const nameEl = document.getElementById("accPlayerName");
  if (!nameEl.value.trim()) nameEl.value = _knownPlayerName(document.getElementById("accPlayerId").value.trim());
}

async function saveAccolade() {
  const season_label = document.getElementById("accSeason").value.trim();
  const kind = document.getElementById("accKind").value;
  if (!season_label) return setStatus("accStatus", "Enter the season", false);
  const valueRaw = document.getElementById("accValue").value.trim();
  const value = valueRaw === "" ? null : Number(valueRaw);
  if (value !== null && !Number.isFinite(value)) return setStatus("accStatus", "Value must be a number", false);
  let body;
  if (kind === "played") {
    const rows = _parsePlayerLines(document.getElementById("accBulk").value);
    if (!rows.length) return setStatus("accStatus", "Add at least one player", false);
    const problem = validateChampionRoster(rows);
    if (problem) return setStatus("accStatus", problem, false);
    body = rows.map(r => ({ season_label, kind, player_account_id: Number(r.account_id), player_name: r.name.trim() }));
  } else if (kind === "fantasy_winner") {
    const username = document.getElementById("accUsername").value.trim();
    if (!username) return setStatus("accStatus", "Enter the winning user", false);
    body = { season_label, kind, username, value };
  } else {
    const row = { account_id: document.getElementById("accPlayerId").value, name: document.getElementById("accPlayerName").value };
    const problem = validateChampionRoster([row]);
    if (problem) return setStatus("accStatus", problem, false);
    body = { season_label, kind, player_account_id: Number(row.account_id), player_name: row.name.trim(), value };
  }
  await withBusy(document.getElementById("accSaveBtn"), async () => {
    try {
      const res = await adminFetch(`${API}/admin/season-accolades`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) return setStatus("accStatus", data.detail, false);
      setStatus("accStatus", Array.isArray(body) ? `Added ${data.added}, ${data.skipped} already recorded` : "Accolade added");
      _afterAccoladeChange();
    } catch (e) {
      setStatus("accStatus", e.message, false);
    }
  });
}
