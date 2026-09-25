let _adminMatchesRows = [];

const _PARSE_STATUS_LABELS = { parsed: 'Parsed', unparsed: 'Unparsed', unparseable: 'Unparseable' };

async function loadAdminMatches() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/matches`);
    const rows = await res.json();
    if (!res.ok) return setStatus('adminMatchesStatus', rows.detail, false);
    _adminMatchesRows = rows;
    renderAdminMatches();
    setStatus('adminMatchesStatus', '');
  } catch (e) {
    setStatus('adminMatchesStatus', e.message, false);
  }
}

function renderAdminMatches() {
  const tbody = document.getElementById('adminMatchesBody');
  const filterEl = document.getElementById('adminMatchesUnparseableOnly');
  const unparseableOnly = !!(filterEl && filterEl.checked);
  const rows = unparseableOnly
    ? _adminMatchesRows.filter(m => m.parse_status === 'unparseable')
    : _adminMatchesRows;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan='10' style='color:#444'>${unparseableOnly ? 'No unparseable matches' : 'No matches'}</td></tr>`;
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
      <td></td>
      <td></td>
      <td class="mvp-cell">${_escHtml(m.mvp_player_name) || '—'}</td>
      <td></td>
      <td></td>`;
    const setMvpBtn = document.createElement('button');
    setMvpBtn.className = 'secondary';
    setMvpBtn.style.cssText = 'padding:2px 7px;';
    setMvpBtn.textContent = 'Set MVP';
    setMvpBtn.addEventListener('click', () => openMvpModal(m.match_id, tr));
    tr.cells[5].appendChild(_buildParseCell(m));
    tr.cells[6].appendChild(_buildScoringCell(m));
    tr.cells[8].appendChild(_buildVodCell(m.match_id, m.vod_url));
    tr.cells[9].appendChild(setMvpBtn);
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------------------
// Parse status + scoring flags
// ---------------------------------------------------------------------------

function _buildParseCell(m) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:4px;align-items:center;font-size:0.8rem;';
  const label = document.createElement('span');
  label.textContent = _PARSE_STATUS_LABELS[m.parse_status] || '—';
  wrap.appendChild(label);
  if (m.parse_status === 'unparsed') {
    const btn = document.createElement('button');
    btn.className = 'secondary';
    btn.style.cssText = 'padding:2px 7px;';
    btn.textContent = 'Retry parse';
    btn.addEventListener('click', () => retryMatchParse(m.match_id, btn));
    wrap.appendChild(btn);
  }
  return wrap;
}

function _buildScoringCell(m) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:2px;font-size:0.8rem;';
  const makeToggle = (text, checked, field) => {
    const lbl = document.createElement('label');
    lbl.style.cssText = 'display:flex;gap:4px;align-items:center;white-space:nowrap;cursor:pointer;';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!checked;
    cb.addEventListener('change', () => saveMatchScoring(m.match_id, { [field]: cb.checked }, cb));
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode(text));
    return lbl;
  };
  wrap.appendChild(makeToggle('Unparseable', m.parse_status === 'unparseable', 'unparseable'));
  wrap.appendChild(makeToggle('Not scored', m.excluded_from_scoring, 'excluded_from_scoring'));
  return wrap;
}

const _RETRY_PARSE_MESSAGES = {
  refreshed: 'now parsed — stats and points replaced',
  requested: 'still unparsed — parse requested from OpenDota',
  cooldown: 'still unparsed — a parse was requested recently, try again later',
  request_failed: 'still unparsed — OpenDota rejected the parse request',
};

async function retryMatchParse(matchId, btn) {
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/admin/matches/${matchId}/retry-parse`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      btn.disabled = false;
      setStatus('adminMatchesStatus', data.detail, false);
      return;
    }
    await loadAdminMatches();
    setStatus('adminMatchesStatus',
      `Match ${matchId}: ${_RETRY_PARSE_MESSAGES[data.outcome] || data.outcome}`, data.outcome === 'refreshed');
  } catch (e) {
    btn.disabled = false;
    setStatus('adminMatchesStatus', e.message, false);
  }
}

async function saveMatchScoring(matchId, body, checkbox) {
  checkbox.disabled = true;
  try {
    const res = await fetch(`${API}/admin/matches/${matchId}/scoring`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      checkbox.checked = !checkbox.checked;
      checkbox.disabled = false;
      setStatus('adminMatchesStatus', data.detail, false);
      return;
    }
    await loadAdminMatches();
  } catch (e) {
    checkbox.checked = !checkbox.checked;
    checkbox.disabled = false;
    setStatus('adminMatchesStatus', e.message, false);
  }
}

// ---------------------------------------------------------------------------
// VOD link inline editing
// ---------------------------------------------------------------------------

function _buildVodCell(matchId, vodUrl) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:4px;align-items:center;';

  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'https://…';
  input.value = vodUrl || '';
  input.style.cssText = 'width:120px;font-size:0.8rem;padding:2px 4px;';

  const saveBtn = document.createElement('button');
  saveBtn.className = 'secondary';
  saveBtn.style.cssText = 'padding:2px 7px;';
  saveBtn.textContent = 'Save';
  saveBtn.addEventListener('click', () => saveMatchVod(matchId, input.value.trim(), wrap));

  wrap.appendChild(input);
  wrap.appendChild(saveBtn);
  return wrap;
}

async function saveMatchVod(matchId, vodUrl, cellWrap) {
  try {
    const res = await fetch(`${API}/admin/matches/${matchId}/vod`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vod_url: vodUrl || null }),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus('adminMatchesStatus', data.detail, false);
      return;
    }
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
