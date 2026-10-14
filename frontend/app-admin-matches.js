let _adminMatchesRows = [];
let _adminMatchesWeeks = [];
let _adminOutOfWeek = [];

const _PARSE_STATUS_LABELS = { parsed: 'Parsed', unparsed: 'Unparsed', unparseable: 'Unparseable' };

async function loadAdminMatches() {
  if (!activeIsAdmin) return;
  try {
    const [res, weeksRes, oowRes] = await Promise.all([
      fetch(`${API}/admin/matches`),
      fetch(`${API}/admin/weeks`),
      fetch(`${API}/admin/matches/out-of-week`),
    ]);
    const rows = await res.json();
    if (!res.ok) return setStatus('adminMatchesStatus', rows.detail, false);
    _adminMatchesRows = rows;
    _adminMatchesWeeks = weeksRes.ok ? await weeksRes.json() : [];
    _adminOutOfWeek = oowRes.ok ? await oowRes.json() : [];
    renderAdminMatches();
    renderOutOfWeekBanner();
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
    tbody.innerHTML = `<tr><td colspan='14' style='color:#444'>${unparseableOnly ? 'No unparseable matches' : 'No matches'}</td></tr>`;
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
      ${_timingCell(m.live_first_seen_at, m.start_time)}
      ${_timingCell(m.ingested_at, m.start_time)}
      ${_timingCell(m.mvp_confirmed_at, m.start_time)}
      <td></td>
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
    tr.cells[8].appendChild(_buildParseCell(m));
    tr.cells[9].appendChild(_buildScoringCell(m));
    tr.cells[10].appendChild(_buildWeekCell(m));
    tr.cells[12].appendChild(_buildVodCell(m.match_id, m.vod_url));
    tr.cells[13].appendChild(setMvpBtn);
    tbody.appendChild(tr);
  });
}

// Minutes from the match start to a timing (issue #161), e.g. "+2 min"; "—" when unknown.
// The exact time is in the cell's title.
function _timingCell(at, startTime) {
  if (!at) return '<td style="font-size:0.8rem;">—</td>';
  const exact = _escHtml(new Date(at * 1000).toLocaleString());
  if (!startTime) return `<td style="font-size:0.8rem;" title="${exact}">—</td>`;
  const mins = Math.round((at - startTime) / 60);
  const text = `${mins >= 0 ? '+' : '−'}${Math.abs(mins)} min`;
  return `<td style="font-size:0.8rem;white-space:nowrap;" title="${exact}">${_escHtml(text)}</td>`;
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
// Scoring week (issue #193): which fantasy week a series counts for
// ---------------------------------------------------------------------------

const _SERIES_GAP_SECONDS = 6 * 3600;

// "Week 4", "Week 4 (set)" for an override, "—" when no week contains the match.
function _scoringWeekText(m) {
  if (!m.scoring_week_label) return '—';
  return m.scoring_week_source === 'override' ? `${m.scoring_week_label} (set)` : m.scoring_week_label;
}

// Games of m's series as the backend groups them: same two teams, start within 6 hours.
function _seriesGameCount(m) {
  if (!m.radiant_team_id || !m.dire_team_id || !m.start_time) return 1;
  const pair = [m.radiant_team_id, m.dire_team_id].sort().join('-');
  return _adminMatchesRows.filter(r =>
    r.radiant_team_id && r.dire_team_id && r.start_time &&
    [r.radiant_team_id, r.dire_team_id].sort().join('-') === pair &&
    Math.abs(r.start_time - m.start_time) <= _SERIES_GAP_SECONDS).length || 1;
}

function _buildWeekCell(m) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:2px;font-size:0.8rem;';
  const label = document.createElement('span');
  label.textContent = _scoringWeekText(m);
  wrap.appendChild(label);

  const select = document.createElement('select');
  select.style.cssText = 'font-size:0.8rem;padding:1px 2px;';
  const byTime = document.createElement('option');
  byTime.value = '';
  byTime.textContent = `By time (${m.time_week_label || '—'})`;
  select.appendChild(byTime);
  _adminMatchesWeeks.forEach(w => {
    const opt = document.createElement('option');
    opt.value = String(w.id);
    opt.textContent = w.label;
    select.appendChild(opt);
  });
  select.value = m.scoring_week_source === 'override' && m.week_override_id != null
    ? String(m.week_override_id) : '';
  select.addEventListener('change', () => {
    const weekId = select.value ? parseInt(select.value, 10) : null;
    const target = weekId === null
      ? `by time (${m.time_week_label || 'no week'})`
      : (_adminMatchesWeeks.find(w => w.id === weekId) || {}).label;
    const n = _seriesGameCount(m);
    if (!confirm(`Count ${n} ${n === 1 ? 'game' : 'games'} ${weekId === null ? '' : 'for '}${target}?`)) {
      select.value = m.scoring_week_source === 'override' && m.week_override_id != null
        ? String(m.week_override_id) : '';
      return;
    }
    setMatchWeek(m.match_id, weekId, select);
  });
  wrap.appendChild(select);
  return wrap;
}

// "2 games updated; Week 4: substitutions re-run (3)"
function _weekChangeSummary(data) {
  const n = (data.changed_match_ids || []).length;
  const parts = [`${n} ${n === 1 ? 'game' : 'games'} updated`];
  (data.substitution_reruns || []).forEach(r => {
    parts.push(`${r.week_label}: substitutions re-run (${r.substitutions})`);
  });
  return parts.join('; ');
}

async function setMatchWeek(matchId, weekId, control) {
  if (control) control.disabled = true;
  try {
    const res = await fetch(`${API}/matches/${matchId}/week`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ week_id: weekId, apply_to_series: true }),
    });
    const data = await res.json();
    if (!res.ok) {
      if (control) control.disabled = false;
      setStatus('adminMatchesStatus', data.detail, false);
      return;
    }
    await loadAdminMatches();
    setStatus('adminMatchesStatus', _weekChangeSummary(data));
  } catch (e) {
    if (control) control.disabled = false;
    setStatus('adminMatchesStatus', e.message, false);
  }
}

// Banner of series counted outside their league week's fantasy week, each with
// "Count for Week N" (scheduled week) and "Keep in Week M" (explicit override).
function renderOutOfWeekBanner() {
  const box = document.getElementById('adminMatchesOutOfWeek');
  if (!box) return;
  box.replaceChildren();
  if (!_adminOutOfWeek.length) {
    box.style.display = 'none';
    return;
  }
  box.style.display = '';
  const n = _adminOutOfWeek.length;
  const title = document.createElement('div');
  title.style.cssText = 'font-weight:600;margin-bottom:6px;';
  title.textContent = `${n} series played outside their scheduled week`;
  box.appendChild(title);
  _adminOutOfWeek.forEach(s => {
    const line = document.createElement('div');
    line.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:0.85rem;margin:4px 0;';
    const text = document.createElement('span');
    const played = s.played_at ? new Date(s.played_at * 1000).toLocaleString() : '—';
    text.textContent = `${s.team1 || '?'} – ${s.team2 || '?'}, played ${played}: ` +
      `scheduled ${s.scheduled_week_label}, counted ${s.counted_week_label || 'in no week'}`;
    line.appendChild(text);
    const firstMatch = (s.match_ids || [])[0];
    if (firstMatch) {
      const countBtn = document.createElement('button');
      countBtn.className = 'secondary';
      countBtn.style.cssText = 'padding:2px 7px;';
      countBtn.textContent = `Count for ${s.scheduled_week_label}`;
      countBtn.addEventListener('click', () => setMatchWeek(firstMatch, s.scheduled_week_id, countBtn));
      line.appendChild(countBtn);
      if (s.counted_week_id) {
        const keepBtn = document.createElement('button');
        keepBtn.className = 'secondary';
        keepBtn.style.cssText = 'padding:2px 7px;';
        keepBtn.textContent = `Keep in ${s.counted_week_label}`;
        keepBtn.addEventListener('click', () => setMatchWeek(firstMatch, s.counted_week_id, keepBtn));
        line.appendChild(keepBtn);
      }
    }
    box.appendChild(line);
  });
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
