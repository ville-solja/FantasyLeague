async function loadAdminMatches() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/matches`);
    const rows = await res.json();
    if (!res.ok) return setStatus('adminMatchesStatus', rows.detail, false);

    const tbody = document.getElementById('adminMatchesBody');
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='7' style='color:#444'>No matches</td></tr>";
      setStatus('adminMatchesStatus', '');
      return;
    }
    tbody.innerHTML = '';
    rows.forEach(m => {
      const tr = document.createElement('tr');
      const start = m.start_time ? new Date(m.start_time * 1000).toLocaleString() : '—';
      tr.innerHTML = `
        <td><a class="stream-link" href="https://www.opendota.com/matches/${m.match_id}" target="_blank" rel="noopener noreferrer">${m.match_id} ↗</a></td>
        <td>${m.league_id || '—'}</td>
        <td style="font-size:0.85rem;">${teamLink(m.radiant_team_id, m.team1)}</td>
        <td style="font-size:0.85rem;">${teamLink(m.dire_team_id, m.team2)}</td>
        <td style="font-size:0.8rem;">${start}</td>
        <td class="mvp-cell">${m.mvp_player_name || '—'}</td>
        <td></td>`;
      const setMvpBtn = document.createElement('button');
      setMvpBtn.className = 'secondary';
      setMvpBtn.style.cssText = 'padding:2px 7px;';
      setMvpBtn.textContent = 'Set MVP';
      setMvpBtn.addEventListener('click', () => openMvpModal(m.match_id, tr));
      tr.cells[6].appendChild(setMvpBtn);
      tbody.appendChild(tr);
    });
    setStatus('adminMatchesStatus', '');
  } catch (e) {
    setStatus('adminMatchesStatus', e.message, false);
  }
}

// ---------------------------------------------------------------------------
// MVP selection modal
// ---------------------------------------------------------------------------

let _mvpTargetMatchId = null;
let _mvpTargetRow = null;

/** Splits the match's players into two team columns (team1 left, team2 right)
 * for #mvpPlayerList's 2-column grid. Falls back to one flat list when the
 * data doesn't cleanly resolve to exactly two teams. */
function _mvpPlayerColumnsHtml(players) {
  const teamOrder = [];
  const byTeam = {};
  players.forEach(p => {
    const key = p.team_id ?? "unknown";
    if (!byTeam[key]) { byTeam[key] = []; teamOrder.push(key); }
    byTeam[key].push(p);
  });

  const playerRow = p =>
    `<label style="display:block;padding:6px 0;cursor:pointer;">` +
    `<input type="radio" name="mvpPlayer" value="${p.id}" style="margin-right:8px;">${_escHtml(p.name)}` +
    `</label>`;

  if (teamOrder.length !== 2) {
    return `<div style="grid-column:1/-1;">${players.map(playerRow).join('')}</div>`;
  }

  return teamOrder.map(key => {
    const teamPlayers = byTeam[key];
    const teamName = teamPlayers[0].team_name || 'Unknown Team';
    return `<div>
      <div style="font-size:0.7rem;letter-spacing:0.05em;text-transform:uppercase;color:#888;margin-bottom:6px;">${_escHtml(teamName)}</div>
      ${teamPlayers.map(playerRow).join('')}
    </div>`;
  }).join('');
}

async function openMvpModal(matchId, row) {
  _mvpTargetMatchId = matchId;
  _mvpTargetRow = row;
  document.getElementById('mvpModalStatus').textContent = '';
  document.getElementById('mvpPlayerList').innerHTML = '<p style="color:#888">Loading…</p>';
  document.getElementById('mvpModal').style.display = 'flex';

  try {
    const res = await fetch(`${API}/admin/matches/${matchId}/players`);
    const players = await res.json();
    if (!res.ok) {
      document.getElementById('mvpPlayerList').innerHTML =
        `<p style='color:#e05'>${players.detail}</p>`;
      return;
    }
    if (!players.length) {
      document.getElementById('mvpPlayerList').innerHTML =
        '<p style="color:#888">No players found for this match.</p>';
      return;
    }
    document.getElementById('mvpPlayerList').innerHTML = _mvpPlayerColumnsHtml(players);
  } catch (e) {
    document.getElementById('mvpPlayerList').innerHTML =
      `<p style='color:#e05'>${e.message}</p>`;
  }
}

function closeMvpModal() {
  document.getElementById('mvpModal').style.display = 'none';
  _mvpTargetMatchId = null;
  _mvpTargetRow = null;
}

async function confirmSetMvp() {
  const selected = document.querySelector('input[name="mvpPlayer"]:checked');
  if (!selected) {
    document.getElementById('mvpModalStatus').textContent = 'Select a player first.';
    return;
  }
  const playerId = parseInt(selected.value);

  try {
    const res = await fetch(`${API}/admin/matches/${_mvpTargetMatchId}/mvp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_id: playerId }),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('mvpModalStatus').textContent = data.detail;
      return;
    }
    // Update the MVP cell in the table row immediately
    if (_mvpTargetRow) {
      const mvpCell = _mvpTargetRow.querySelector('.mvp-cell');
      if (mvpCell) mvpCell.textContent = data.player_name;
    }
    closeMvpModal();
  } catch (e) {
    document.getElementById('mvpModalStatus').textContent = e.message;
  }
}
