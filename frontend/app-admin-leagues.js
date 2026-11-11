let _leaguesCached = [];
let _purgeTargetLeagueId = null;
// GET /admin/opendota-status: OpenDota's recent answers and each monitored league's last
// ingest check, so a rate limit or a listed game that wasn't stored shows here without
// the container logs. Null until loaded, or when the request failed.
let _opendotaStatus = null;

async function loadLeagues() {
  if (!activeIsAdmin) return;
  try {
    const [res, statusRes] = await Promise.all([
      fetch(`${API}/admin/leagues`),
      fetch(`${API}/admin/opendota-status`).catch(() => null),
    ]);
    const data = await res.json();
    if (!res.ok) return;
    _leaguesCached = data;
    _opendotaStatus = statusRes && statusRes.ok ? await statusRes.json().catch(() => null) : null;
    _renderLeagues();
  } catch (e) { /* silently ignore network errors */ }
}

function _odTime(at) {
  return at ? new Date(at * 1000).toLocaleString() : 'never';
}

const _OD_PROBLEM_TEXT = {
  rate_limited: 'rate limited (HTTP 429)',
  server_error: 'server error',
  network: 'no answer (timeout or connection)',
  client_error: 'refused the request',
  gave_up: 'gave up after retries',
};
const _NOT_STORED_TEXT = {
  fetch_failed: 'OpenDota did not return the match',
  too_short: 'shorter than 15 minutes, not stored by design',
  error: 'failed while storing',
  not_stored: 'not stored yet',
};

// One line on OpenDota's health above the table, plus a warning when it is failing now.
function _renderOpendotaStatus() {
  const panel = document.getElementById('leagueManagementPanel');
  if (!panel) return;
  let box = document.getElementById('opendotaStatusBox');
  if (!box) {
    box = document.createElement('div');
    box.id = 'opendotaStatusBox';
    box.className = 'admin-panel-desc';
    const wrap = panel.querySelector('.admin-table-wrap');
    panel.insertBefore(box, wrap);
  }
  const s = _opendotaStatus && _opendotaStatus.opendota;
  if (!s) { box.innerHTML = ''; return; }
  const counts = s.problems_24h || {};
  const problems = Object.keys(_OD_PROBLEM_TEXT).filter(k => counts[k])
    .map(k => `${counts[k]} ${_OD_PROBLEM_TEXT[k]}`);
  const last = s.last_problem;
  let warn = '';
  if (s.rate_limited_now) {
    warn = `<p class="status err">OpenDota is rate-limiting the server: new matches and Add match fail until it lets requests through again.${s.api_key_set ? ' An API key is set; check its quota.' : ' No OPENDOTA_API_KEY is set, so the free daily limit applies.'}</p>`;
  } else if (s.failing_now) {
    warn = `<p class="status err">OpenDota is failing right now: ${_escHtml(_OD_PROBLEM_TEXT[last.kind] || last.kind)}. Ingest retries on its next pass.</p>`;
  }
  box.innerHTML = `${warn}<p>OpenDota: last successful call ${_escHtml(_odTime(s.last_ok_at))}. `
    + (problems.length ? `Past 24 h: ${_escHtml(problems.join(', '))}.` : 'No problems in the past 24 h.')
    + (last ? ` Last problem ${_escHtml(_odTime(last.at))}: ${_escHtml(_OD_PROBLEM_TEXT[last.kind] || last.kind)}${last.status ? ` (HTTP ${Number(last.status)})` : ''}, ${_escHtml(last.label || '')}.` : '')
    + ` Kept in memory since the last restart.</p>`;
}

// The Last check and Not stored cells for a monitored league.
function _leagueCheckCells(l) {
  const st = _opendotaStatus && (_opendotaStatus.leagues || []).find(x => x.id === l.id);
  if (!l.is_monitored || !st) return '<td>—</td><td>—</td>';
  const failedLater = st.list_failed_at && (!st.listed_at || st.list_failed_at > st.listed_at);
  const check = failedLater
    ? `<span class="status err">Match list unavailable ${_escHtml(_odTime(st.list_failed_at))}</span>`
    : st.listed_at ? `${_escHtml(_odTime(st.listed_at))} · ${Number(st.listed)} listed` : 'Not checked since restart';
  const missing = (st.not_stored || []);
  const notStored = !missing.length ? (st.listed_at ? '0' : '—') : missing.map(m => {
    const id = Number(m.match_id);
    return `<div><a href="https://www.opendota.com/matches/${id}" target="_blank" rel="noopener noreferrer">${id}</a> `
      + `${_escHtml(_NOT_STORED_TEXT[m.reason] || m.reason)}</div>`;
  }).join('');
  return `<td>${check}</td><td>${notStored}</td>`;
}

function _renderLeagues() {
  _renderOpendotaStatus();
  const head = document.querySelector('#leagueTable thead tr');
  if (head) head.innerHTML = '<th>ID</th><th>Name</th><th>Matches</th><th>Monitored</th><th>Last check</th><th>Not stored</th><th>Actions</th>';
  const tbody = document.getElementById('leagueTableBody');
  if (!_leaguesCached.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:#444">No leagues</td></tr>`;
    return;
  }
  tbody.innerHTML = _leaguesCached.map(l => `
    <tr>
      <td>${l.id}</td>
      <td>${_escHtml(l.name)}</td>
      <td>${l.match_count}</td>
      <td>${l.is_monitored ? 'Yes' : 'No'}</td>
      ${_leagueCheckCells(l)}
      <td>
        ${l.is_monitored
          ? `<button data-ingest-id="${l.id}" onclick="ingestLeagueNow(${l.id})">Ingest Now</button>
             <button class="secondary" onclick="unmonitorLeague(${l.id})">Unmonitor</button>`
          : `<button onclick="monitorLeague(${l.id})">Monitor</button>`
        }
        ${l.match_count > 0
          ? `<button class="danger" onclick="openPurgeLeagueModal(${l.id}, '${_escHtml(l.name)}')">Purge data</button>`
          : ''
        }
      </td>
    </tr>`).join('');
}

function openAddLeagueModal() { document.getElementById('addLeagueModal').style.display = 'flex'; }
function closeAddLeagueModal() { document.getElementById('addLeagueModal').style.display = 'none'; }

async function submitAddLeague() {
  const raw = document.getElementById('addLeagueIdInput').value.trim();
  const id = /^\d+$/.test(raw) ? parseInt(raw, 10) : 0;
  if (!id) return setStatus('leaguesStatus', 'Enter a valid league ID', false);
  const res = await fetch(`${API}/admin/leagues/${id}/monitor`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) { setStatus('leaguesStatus', data.detail, false); return; }
  closeAddLeagueModal();
  setStatus('leaguesStatus', `League ${id} added`);
  loadLeagues();
}

async function monitorLeague(id) {
  const res = await fetch(`${API}/admin/leagues/${id}/monitor`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) { setStatus('leaguesStatus', data.detail, false); return; }
  setStatus('leaguesStatus', `League ${id} is now monitored`);
  loadLeagues();
}

async function unmonitorLeague(id) {
  const res = await fetch(`${API}/admin/leagues/${id}/monitor`, { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) { setStatus('leaguesStatus', data.detail, false); return; }
  setStatus('leaguesStatus', `League ${id} unmonitored`);
  loadLeagues();
}

async function ingestLeagueNow(id) {
  const btn = document.querySelector(`button[data-ingest-id="${id}"]`);
  if (btn) { btn.disabled = true; btn.textContent = 'Ingesting…'; }
  setStatus('leaguesStatus', `Ingesting league ${id} — this can take a few minutes for a full season…`);
  try {
    const res = await fetch(`${API}/ingest/league/${id}`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) return setStatus('leaguesStatus', data.detail || 'Ingest failed', false);
    setStatus('leaguesStatus', `Ingest complete for league ${id}`);
    loadLeagues();
  } catch (e) {
    setStatus('leaguesStatus', e.message, false);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Ingest Now'; }
  }
}

function openPurgeLeagueModal(id, name) {
  _purgeTargetLeagueId = id;
  document.getElementById('purgeLeagueDescription').textContent = `League: ${name} (ID ${id})`;
  document.getElementById('purgeLeagueModal').style.display = 'flex';
}
function closePurgeLeagueModal() {
  document.getElementById('purgeLeagueModal').style.display = 'none';
  _purgeTargetLeagueId = null;
}
async function confirmPurgeLeague() {
  if (!_purgeTargetLeagueId) return;
  const res = await adminFetch(`${API}/admin/leagues/${_purgeTargetLeagueId}/data`, { method: 'DELETE' });
  const data = await res.json();
  closePurgeLeagueModal();
  if (!res.ok) { setStatus('leaguesStatus', data.detail, false); return; }
  setStatus('leaguesStatus', `Purged: ${data.deleted_matches} matches, ${data.deleted_stats} stats. ${data.note}`);
  loadLeagues();
}
