let _leaguesCached = [];
let _purgeTargetLeagueId = null;

async function loadLeagues() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/leagues`);
    const data = await res.json();
    if (!res.ok) return;
    _leaguesCached = data;
    _renderLeagues();
  } catch (e) { /* silently ignore network errors */ }
}

function _renderLeagues() {
  const tbody = document.getElementById('leagueTableBody');
  if (!_leaguesCached.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:#444">No leagues</td></tr>`;
    return;
  }
  tbody.innerHTML = _leaguesCached.map(l => `
    <tr>
      <td>${l.id}</td>
      <td>${_escHtml(l.name)}</td>
      <td>${l.match_count}</td>
      <td>${l.is_monitored ? 'Yes' : 'No'}</td>
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
  const id = parseInt(document.getElementById('addLeagueIdInput').value);
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
  const res = await fetch(`${API}/admin/leagues/${_purgeTargetLeagueId}/data`, { method: 'DELETE' });
  const data = await res.json();
  closePurgeLeagueModal();
  if (!res.ok) { setStatus('leaguesStatus', data.detail, false); return; }
  setStatus('leaguesStatus', `Purged: ${data.deleted_matches} matches, ${data.deleted_stats} stats. ${data.note}`);
  loadLeagues();
}
