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
      <td><img src="${p.avatar_url || ''}" style="width:20px;height:20px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${_escHtml(p.name)}</td>
      <td>${_escHtml(p.team_name || "—")}</td>
      <td style="font-size:0.8rem;color:#888;">${p.id}</td>
      <td>${p.active_card_count}</td>
      <td>${p.is_active ? "" : "<span style='color:#888;font-size:0.75rem;'>INACTIVE</span>"}</td>
    </tr>`).join("");
  _updateRemoveBtn();
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
  }
}

function openBulkAddPlayersPopup() {
  document.getElementById("bulkAddPlayersModal").classList.remove("hidden");
  setStatus("bulkAddPlayersStatus", "");
  document.getElementById("bulkAddIdsInput").value = "";
}

function closeBulkAddPlayersPopup() {
  document.getElementById("bulkAddPlayersModal").classList.add("hidden");
}

async function bulkAddPlayers() {
  const csv = document.getElementById("bulkAddIdsInput").value.trim();
  if (!csv) return setStatus("bulkAddPlayersStatus", "Enter at least one ID", false);
  try {
    const res = await fetch(`${API}/admin/players/bulk`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_ids: csv}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("bulkAddPlayersStatus", data.detail, false);
    const msg = `Added: ${data.added}. Skipped: ${data.skipped.length}.`;
    setStatus("bulkAddPlayersStatus", msg);
    if (data.added > 0) loadPlayerPool();
  } catch (e) {
    setStatus("bulkAddPlayersStatus", e.message, false);
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
