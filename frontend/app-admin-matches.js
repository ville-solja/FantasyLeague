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
    _applyMvpMissingDefault(rows);
    renderAdminMatches();
    renderOutOfWeekBanner();
    setStatus('adminMatchesStatus', '');
  } catch (e) {
    setStatus('adminMatchesStatus', e.message, false);
  }
}

// ---------------------------------------------------------------------------
// Filters and series grouping (issue 214)
// ---------------------------------------------------------------------------

const _DIVISION_LABELS = { div1: 'Div 1', div2: 'Div 2' };
let _adminMatchesFilterInit = false;

// "MVP missing" starts checked when any match lacks an MVP; set once per page so
// a reload after an edit keeps the admin's own choice.
function _applyMvpMissingDefault(rows) {
  if (_adminMatchesFilterInit) return;
  _adminMatchesFilterInit = true;
  const el = document.getElementById('adminMatchesMvpMissing');
  if (el) el.checked = rows.some(m => !m.mvp_player_id);
}

function adminMatchesFilters() {
  const mvp = document.getElementById('adminMatchesMvpMissing');
  const league = document.getElementById('adminMatchesLeague');
  const unparseable = document.getElementById('adminMatchesUnparseableOnly');
  const manual = document.getElementById('adminMatchesManualOnly');
  return {
    mvpMissing: !!(mvp && mvp.checked),
    league: league && _DIVISION_LABELS[league.value] ? league.value : '',
    unparseable: !!(unparseable && unparseable.checked),
    manualOnly: !!(manual && manual.checked),
  };
}

// Filters combine: a match shows only when it passes every active one.
function filterAdminMatches(rows, f) {
  return rows.filter(m =>
    (!f.mvpMissing || !m.mvp_player_id) &&
    (!f.league || m.division === f.league) &&
    (!f.unparseable || m.parse_status === 'unparseable') &&
    (!f.manualOnly || _isManualMatch(m)));
}

function adminMatchesEmptyText(f) {
  const active = [];
  if (f.mvpMissing) active.push('MVP missing');
  if (f.league) active.push(_DIVISION_LABELS[f.league]);
  if (f.unparseable) active.push('Unparseable');
  if (f.manualOnly) active.push('Manual only');
  return active.length ? `No matches for the filters: ${active.join(', ')}` : 'No matches';
}

// Issue 224: matches added from Admin > Matches > Add match, not by league ingest.
const _SOURCE_CHIPS = { opendota_manual: 'Manual', replay: 'Replay' };

function _isManualMatch(m) {
  return !!_SOURCE_CHIPS[m.source];
}

// "Manual" / "Replay" chip with "Added by <admin>, <time>" as its tooltip; nothing for league matches.
function _sourceChipHtml(m) {
  const label = _SOURCE_CHIPS[m.source];
  if (!label) return '';
  const when = m.added_at ? new Date(m.added_at * 1000).toLocaleString() : null;
  const tip = m.added_by
    ? `Added by ${m.added_by}${when ? `, ${when}` : ''}`
    : (m.source === 'replay' ? 'Imported from a replay' : 'Added from OpenDota');
  return ` <span class="admin-source-chip ${m.source === 'replay' ? 'replay' : 'manual'}" title="${_escHtml(tip)}">${label}</span>`;
}

// Feed series newest first, each with its games in play order; matches the feed
// doesn't know form one last "Not in the schedule" group, newest first.
function groupAdminMatches(rows) {
  const groups = [];
  const byKey = new Map();
  const unscheduled = { key: null, rows: [] };
  rows.forEach(m => {
    if (!m.series_key) { unscheduled.rows.push(m); return; }
    let g = byKey.get(m.series_key);
    if (!g) {
      g = { key: m.series_key, rows: [] };
      byKey.set(m.series_key, g);
      groups.push(g);
    }
    g.rows.push(m);
  });
  const latest = g => Math.max(...g.rows.map(m => m.start_time || 0));
  groups.forEach(g => g.rows.sort((a, b) => (a.start_time || 0) - (b.start_time || 0)));
  groups.sort((a, b) => latest(b) - latest(a));
  unscheduled.rows.sort((a, b) => (b.start_time || 0) - (a.start_time || 0));
  if (unscheduled.rows.length) groups.push(unscheduled);
  return groups;
}

// The series' team 1 and team 2 in feed order, so they don't swap between games;
// radiant/dire for matches outside the feed.
function _seriesTeams(m) {
  const nameOf = id => id === m.radiant_team_id ? m.team1 : (id === m.dire_team_id ? m.team2 : null);
  if (m.series_team1_id && m.series_team2_id) {
    return [
      { id: m.series_team1_id, name: nameOf(m.series_team1_id) },
      { id: m.series_team2_id, name: nameOf(m.series_team2_id) },
    ];
  }
  return [{ id: m.radiant_team_id, name: m.team1 }, { id: m.dire_team_id, name: m.team2 }];
}

function _streamLinkHtml(url) {
  const safe = _safeUrl(url);
  if (!safe) return '—';
  return `<a class="stream-link" href="${_escHtml(safe)}" target="_blank" rel="noopener noreferrer">Stream ↗</a>`;
}

function _leagueText(m) {
  const name = _escHtml(m.league_name || (m.league_id ? String(m.league_id) : '')) || '—';
  const div = _DIVISION_LABELS[m.division];
  return div ? `${name} <span class="admin-match-div">· ${div}</span>` : name;
}

// Series header: "Team A vs Team B · Div 1 · Week 4 · Stream ↗"; "Not in the schedule" for the rest.
function _seriesHeaderHtml(group) {
  if (!group.key) return `<th colspan="13" scope="colgroup">Not in the schedule</th>`;
  const first = group.rows[0];
  const [t1, t2] = _seriesTeams(first);
  const parts = [`${_escHtml(t1.name || '?')} vs ${_escHtml(t2.name || '?')}`];
  if (_DIVISION_LABELS[first.division]) parts.push(_DIVISION_LABELS[first.division]);
  if (first.scoring_week_label) parts.push(_escHtml(first.scoring_week_label));
  if (_safeUrl(first.stream_url)) parts.push(_streamLinkHtml(first.stream_url));
  return `<th colspan="13" scope="colgroup">${parts.join(' · ')}</th>`;
}

// One game row; the empty cells take Set MVP, Week, Scoring, Parse and More controls.
function _adminMatchRowHtml(m) {
  const [t1, t2] = _seriesTeams(m);
  const start = m.start_time ? new Date(m.start_time * 1000).toLocaleString() : '—';
  return `
      <td><a class="stream-link" href="https://www.opendota.com/matches/${m.match_id}" target="_blank" rel="noopener noreferrer">${m.match_id} ↗</a>${_sourceChipHtml(m)}</td>
      <td class="admin-match-teams">${teamLink(t1.id, t1.name)} <span class="admin-match-vs">vs</span> ${teamLink(t2.id, t2.name)}</td>
      <td class="admin-match-league">${_leagueText(m)}</td>
      <td class="admin-match-start">${_escHtml(start)}</td>
      <td class="admin-match-mvp"><span class="mvp-cell">${_escHtml(m.mvp_player_name) || '—'}</span></td>
      <td>${_streamLinkHtml(m.stream_url)}</td>
      <td></td>
      <td></td>
      <td></td>
      ${_timingCell(m.live_first_seen_at, m.start_time)}
      ${_timingCell(m.ingested_at, m.start_time)}
      ${_timingCell(m.mvp_confirmed_at, m.start_time)}
      <td></td>`;
}

function _renderAdminMatchesCount(shown) {
  const el = document.getElementById('adminMatchesCount');
  if (!el) return;
  const total = _adminMatchesRows.length;
  el.textContent = shown === total ? `${total} matches` : `${shown} of ${total} matches`;
}

function renderAdminMatches() {
  const tbody = document.getElementById('adminMatchesBody');
  const filters = adminMatchesFilters();
  const rows = filterAdminMatches(_adminMatchesRows, filters);
  _renderAdminMatchesCount(rows.length);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan='13' class='admin-matches-empty'>${_escHtml(adminMatchesEmptyText(filters))}</td></tr>`;
    return;
  }
  tbody.innerHTML = '';
  groupAdminMatches(rows).forEach(group => {
    const head = document.createElement('tr');
    head.className = 'admin-series-row';
    head.innerHTML = _seriesHeaderHtml(group);
    tbody.appendChild(head);
    group.rows.forEach(m => {
      const tr = document.createElement('tr');
      tr.className = 'admin-match-row';
      tr.innerHTML = _adminMatchRowHtml(m);
      const more = document.createElement('tr');
      more.className = 'admin-match-more';
      more.hidden = true;
      more.innerHTML = `<td colspan='13'></td>`;
      const setMvpBtn = document.createElement('button');
      setMvpBtn.className = 'secondary admin-set-mvp';
      setMvpBtn.textContent = 'Set MVP';
      setMvpBtn.addEventListener('click', () => openMvpModal(m.match_id, tr));
      const moreBtn = document.createElement('button');
      moreBtn.className = 'ghost admin-more-btn';
      moreBtn.textContent = 'More';
      moreBtn.setAttribute('aria-expanded', 'false');
      moreBtn.addEventListener('click', () => {
        more.hidden = !more.hidden;
        moreBtn.setAttribute('aria-expanded', String(!more.hidden));
      });
      tr.cells[4].appendChild(setMvpBtn);
      tr.cells[6].appendChild(_buildWeekCell(m));
      tr.cells[7].appendChild(_buildScoringCell(m));
      tr.cells[8].appendChild(_buildParseCell(m));
      tr.cells[12].appendChild(moreBtn);
      more.cells[0].appendChild(_buildMoreDetails(m));
      tbody.appendChild(tr);
      tbody.appendChild(more);
    });
  });
}

// More details: the admin VOD link (shown in the Weekly Report) and the exact
// timing times behind the "+N min" columns.
function _buildMoreDetails(m) {
  const wrap = document.createElement('div');
  wrap.className = 'admin-match-details';
  const vodLabel = document.createElement('span');
  vodLabel.className = 'admin-match-details-label';
  vodLabel.textContent = 'VOD link (Weekly Report)';
  wrap.appendChild(vodLabel);
  wrap.appendChild(_buildVodCell(m.match_id, m.vod_url));
  [['Live seen', m.live_first_seen_at], ['Stats in', m.ingested_at], ['MVP picked', m.mvp_confirmed_at]]
    .forEach(([label, at]) => {
      const k = document.createElement('span');
      k.className = 'admin-match-details-label';
      k.textContent = label;
      const v = document.createElement('span');
      v.textContent = at ? new Date(at * 1000).toLocaleString() : '—';
      wrap.appendChild(k);
      wrap.appendChild(v);
    });
  return wrap;
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
  if (m.parse_status === 'unparsed' && m.source !== 'replay') {
    const btn = document.createElement('button');
    btn.className = 'secondary';
    btn.style.cssText = 'padding:2px 7px;';
    btn.textContent = 'Retry parse';
    btn.addEventListener('click', () => retryMatchParse(m.match_id, btn));
    wrap.appendChild(btn);
  }
  return wrap;
}

// Issue 214: checkbox and label columns of a fixed two-column grid, so rows line up.
function _buildScoringCell(m) {
  const wrap = document.createElement('div');
  wrap.className = 'admin-scoring-grid';
  const makeToggle = (text, checked, field) => {
    const lbl = document.createElement('label');
    lbl.className = 'admin-scoring-toggle';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!checked;
    cb.addEventListener('change', () => saveMatchScoring(m.match_id, { [field]: cb.checked }, cb));
    const span = document.createElement('span');
    span.textContent = text;
    lbl.appendChild(cb);
    lbl.appendChild(span);
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
    // Update the MVP cell in the table row immediately; the row stays until the next
    // render, so the MVP missing filter doesn't pull it from under the admin.
    const row = _adminMatchesRows.find(r => r.match_id === _mvpTargetMatchId);
    if (row) { row.mvp_player_id = playerId; row.mvp_player_name = data.player_name; }
    if (_mvpTargetRow) {
      const mvpCell = _mvpTargetRow.querySelector('.mvp-cell');
      if (mvpCell) mvpCell.textContent = data.player_name;
    }
    closeMvpModal();
  } catch (e) {
    document.getElementById('mvpModalStatus').textContent = e.message;
  }
}

// ---------------------------------------------------------------------------
// Add match (issue 224): a match played outside the league lobby, from OpenDota
// by its id or from a replay summary written by scripts/replay_to_match.py
// ---------------------------------------------------------------------------

const _ADD_MATCH_MAX_BYTES = 56 * 1024;
let _addMatchMode = 'opendota';
let _addMatchBody = null;     // {match_id} or {replay} the preview was made from
let _addMatchPreview = null;

function openAddMatchDialog() {
  _addMatchBody = null;
  _addMatchPreview = null;
  document.getElementById('addMatchId').value = '';
  document.getElementById('addMatchFile').value = '';
  document.getElementById('addMatchPreview').innerHTML = '';
  document.getElementById('addMatchStoreBtn').disabled = true;
  setStatus('addMatchStatus', '');
  setAddMatchMode('opendota');
  document.getElementById('addMatchModal').style.display = 'flex';
  document.getElementById('addMatchId').focus && document.getElementById('addMatchId').focus();
}

function closeAddMatchDialog() {
  document.getElementById('addMatchModal').style.display = 'none';
}

function setAddMatchMode(mode) {
  _addMatchMode = mode === 'replay' ? 'replay' : 'opendota';
  const replay = _addMatchMode === 'replay';
  const odTab = document.getElementById('addMatchTabOpenDota');
  const rpTab = document.getElementById('addMatchTabReplay');
  odTab.classList.toggle('active', !replay);
  rpTab.classList.toggle('active', replay);
  odTab.setAttribute('aria-selected', String(!replay));
  rpTab.setAttribute('aria-selected', String(replay));
  document.getElementById('addMatchOpenDotaPanel').hidden = replay;
  document.getElementById('addMatchReplayPanel').hidden = !replay;
  _addMatchBody = null;
  _addMatchPreview = null;
  document.getElementById('addMatchPreview').innerHTML = '';
  document.getElementById('addMatchStoreBtn').disabled = true;
}

// The preview request body for the active tab; throws a readable Error.
async function _addMatchRequestBody() {
  if (_addMatchMode === 'opendota') {
    const raw = document.getElementById('addMatchId').value.trim();
    const id = parseInt(raw, 10);
    if (!/^[0-9]+$/.test(raw) || !Number.isFinite(id) || id <= 0) throw new Error('Enter a match id.');
    return { match_id: id };
  }
  const input = document.getElementById('addMatchFile');
  const file = input.files && input.files[0];
  if (!file) throw new Error('Choose the match-<id>.json file.');
  if (file.size > _ADD_MATCH_MAX_BYTES) throw new Error('The file is larger than 56 KB.');
  let replay;
  try {
    replay = JSON.parse(await file.text());
  } catch (e) {
    throw new Error('The file is not valid JSON.');
  }
  return { replay };
}

function _fmtDuration(sec) {
  if (!Number.isFinite(sec)) return '—';
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

// Summary, partial-stats note, replacement note and the ten players (escaped).
function addMatchPreviewHtml(p) {
  const start = p.start_time ? new Date(p.start_time * 1000).toLocaleString() : '—';
  const winnerName = p.winner === 'radiant' ? (p.radiant_name || 'Radiant') : (p.dire_name || 'Dire');
  const winner = p.winner ? `${p.winner === 'radiant' ? 'Radiant' : 'Dire'} won (${_escHtml(winnerName)})` : 'Winner unknown';
  const teams = `${_escHtml(p.radiant_name || 'Radiant')} vs ${_escHtml(p.dire_name || 'Dire')}`;
  const parts = [`<p class="add-match-summary">Match ${_escHtml(String(p.match_id))} · ${teams} · ${_escHtml(start)} · ${_fmtDuration(p.duration)} · ${winner}</p>`];
  if (p.partial_note) parts.push(`<p class="add-match-partial">${_escHtml(p.partial_note)}</p>`);
  if (p.existing_source) {
    parts.push(`<p class="add-match-note">Already added (${_escHtml(_SOURCE_CHIPS[p.existing_source] || p.existing_source)}): adding it again replaces its stats.</p>`);
  }
  const notInPool = (p.players || []).filter(pl => !pl.in_pool).length;
  if (notInPool) {
    parts.push(`<p class="add-match-note">${notInPool} ${notInPool === 1 ? 'player is' : 'players are'} not in the season's pool; they are stored anyway.</p>`);
  }
  const rows = (p.players || []).map(pl => {
    const hero = pl.hero_name || (pl.hero_id ? `Hero ${pl.hero_id}` : '—');
    const warn = pl.in_pool ? '' : ' <span class="add-match-warn">Not in pool</span>';
    return `<tr><td>${pl.side === 'radiant' ? 'Radiant' : 'Dire'}</td><td>${_escHtml(pl.name || String(pl.account_id))}${warn}</td>` +
      `<td>${_escHtml(hero)}</td><td>${_escHtml(pl.kills)}/${_escHtml(pl.deaths)}/${_escHtml(pl.assists)}</td></tr>`;
  }).join('');
  parts.push(`<table class="add-match-players"><thead><tr><th>Side</th><th>Player</th><th>Hero</th><th>K/D/A</th></tr></thead><tbody>${rows}</tbody></table>`);
  return parts.join('');
}

function _fillAddMatchSelect(id, options, selected) {
  const sel = document.getElementById(id);
  sel.replaceChildren();
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = 'Choose…';
  sel.appendChild(blank);
  options.forEach(o => {
    const opt = document.createElement('option');
    opt.value = String(o.value);
    opt.textContent = o.label;
    sel.appendChild(opt);
  });
  sel.value = selected != null ? String(selected) : '';
}

function renderAddMatchPreview(p) {
  _addMatchPreview = p;
  document.getElementById('addMatchPreview').innerHTML = addMatchPreviewHtml(p);
  const leagues = (p.leagues || []).map(l => ({ value: l.id, label: `${l.name || l.id} (${l.division_label})` }));
  const teams = (p.teams || []).map(t => ({ value: t.id, label: t.name || String(t.id) }));
  const leagueSel = document.getElementById('addMatchLeague');
  const keepLeague = leagueSel.value && leagues.some(l => String(l.value) === leagueSel.value) ? leagueSel.value : null;
  _fillAddMatchSelect('addMatchLeague', leagues, keepLeague);
  _fillAddMatchSelect('addMatchRadiant', teams, p.suggested_radiant_team_id);
  _fillAddMatchSelect('addMatchDire', teams, p.suggested_dire_team_id);
  document.getElementById('addMatchStoreBtn').disabled = false;
}

async function previewAddMatch() {
  let body;
  try {
    body = await _addMatchRequestBody();
  } catch (e) {
    setStatus('addMatchStatus', e.message, false);
    return;
  }
  _addMatchBody = null;
  _addMatchPreview = null;
  document.getElementById('addMatchPreview').innerHTML = '';
  document.getElementById('addMatchStoreBtn').disabled = true;
  setStatus('addMatchStatus', 'Loading…');
  try {
    const res = await fetch(`${API}/admin/matches/manual/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setStatus('addMatchStatus', data.detail || `Request failed (${res.status})`, false);
      return;
    }
    _addMatchBody = body;
    renderAddMatchPreview(data);
    setStatus('addMatchStatus', '');
  } catch (e) {
    setStatus('addMatchStatus', e.message, false);
  }
}

function _addMatchId(id) {
  const n = parseInt(document.getElementById(id).value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

// Stores through adminFetch, so a stale re-auth opens the confirm popup and resends.
// A 409 asking to replace an earlier manual match is confirmed, then resent with confirm.
async function storeAddMatch(confirmReplace = false) {
  if (!_addMatchBody) return setStatus('addMatchStatus', 'Fetch or check the match first.', false);
  const leagueId = _addMatchId('addMatchLeague');
  const radiantId = _addMatchId('addMatchRadiant');
  const direId = _addMatchId('addMatchDire');
  if (!leagueId) return setStatus('addMatchStatus', 'Choose the league.', false);
  if (!radiantId) return setStatus('addMatchStatus', 'Choose the Radiant team.', false);
  if (!direId) return setStatus('addMatchStatus', 'Choose the Dire team.', false);
  const btn = document.getElementById('addMatchStoreBtn');
  btn.disabled = true;
  try {
    const res = await adminFetch(`${API}/admin/matches/manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ..._addMatchBody, league_id: leagueId, radiant_team_id: radiantId,
                             dire_team_id: direId, confirm: confirmReplace }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 409 && !confirmReplace && /Confirm to replace/.test(data.detail || '')) {
      btn.disabled = false;
      if (confirm(`${data.detail}\n\nReplace it?`)) return storeAddMatch(true);
      return setStatus('addMatchStatus', 'Not replaced.', false);
    }
    if (!res.ok) {
      btn.disabled = false;
      return setStatus('addMatchStatus', data.detail || `Request failed (${res.status})`, false);
    }
    closeAddMatchDialog();
    await loadAdminMatches();
    const partial = (data.missing_stats || []).length ? ` (partial stats: ${data.missing_stats.join(', ')})` : '';
    setStatus('adminMatchesStatus',
      `Match ${data.match_id} ${data.replaced ? 'replaced' : 'added'} as ${_SOURCE_CHIPS[data.source] || data.source}${partial}`);
  } catch (e) {
    btn.disabled = false;
    setStatus('addMatchStatus', e.message, false);
  }
}
