let _weeklySummaryWeeks = [];
let _weeklySummaryActiveWeekId = null;

async function checkWeeklySummaryHighlight() {
  try {
    const res = await fetch(`${API}/weekly-summary`);
    if (!res.ok) return;
    const data = await res.json();
    _weeklySummaryWeeks = data.weeks || [];
    const badge = document.getElementById('weeklyReportBadge');
    if (badge) badge.style.display = data.has_unseen ? '' : 'none';
  } catch (_) {}
}

async function openWeeklySummary() {
  document.getElementById('weeklySummaryModal').classList.remove('hidden');
  await loadWeeklySummaryList();
  await markWeeklySummarySeen();
}

function closeWeeklySummary() {
  document.getElementById('weeklySummaryModal').classList.add('hidden');
}

async function loadWeeklySummaryList() {
  const content = document.getElementById('weeklySummaryContent');
  try {
    const res = await fetch(`${API}/weekly-summary`);
    const data = await res.json();
    if (!res.ok) { content.innerHTML = `<p style="color:#e05;">${data.detail}</p>`; return; }
    _weeklySummaryWeeks = data.weeks || [];
    renderWeeklySummaryTabs();
    if (_weeklySummaryWeeks.length) {
      await selectWeeklySummaryTab(_weeklySummaryWeeks[0].week_id);
    } else {
      document.getElementById('weeklySummaryTabs').innerHTML = '';
      content.innerHTML = '<p style="color:#888;">No weekly reports available yet.</p>';
    }
  } catch (e) {
    content.innerHTML = `<p style="color:#e05;">${e.message}</p>`;
  }
}

function renderWeeklySummaryTabs() {
  const bar = document.getElementById('weeklySummaryTabs');
  bar.innerHTML = '';
  _weeklySummaryWeeks.forEach(w => {
    const btn = document.createElement('button');
    btn.className = 'weekly-summary-tab-btn';
    btn.textContent = w.label;
    btn.dataset.weekId = w.week_id;
    btn.onclick = () => selectWeeklySummaryTab(w.week_id);
    bar.appendChild(btn);
  });
}

function _markActiveWeeklySummaryTab(weekId) {
  [...document.getElementById('weeklySummaryTabs').children].forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.weekId, 10) === weekId);
  });
}

async function selectWeeklySummaryTab(weekId) {
  _weeklySummaryActiveWeekId = weekId;
  _markActiveWeeklySummaryTab(weekId);
  const content = document.getElementById('weeklySummaryContent');
  content.innerHTML = '<p style="color:#888;">Loading…</p>';
  try {
    const res = await fetch(`${API}/weekly-summary/${weekId}`);
    const data = await res.json();
    if (!res.ok) { content.innerHTML = `<p style="color:#e05;">${data.detail}</p>`; return; }
    renderWeeklySummaryContent(data);
  } catch (e) {
    content.innerHTML = `<p style="color:#e05;">${e.message}</p>`;
  }
}

function _weeklySummaryTeamHtml(team) {
  if (!team) return '<span style="color:#888;">Unknown</span>';
  // Team crests are usually non-square (wordmarks, rectangular badges), so — unlike
  // the circular player avatars — this stays a plain rounded box sized large enough
  // to actually read, rather than cropping the logo into a tiny circle.
  const logo = team.logo_url
    ? `<img src="${_escHtml(team.logo_url)}" alt="" style="width:28px;height:28px;border-radius:6px;object-fit:contain;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'">`
    : '';
  return `${logo}${teamLink(team.id, team.name || 'Unknown')}`;
}

function _weeklySummaryTeamColHtml(team, isWinner, isRight) {
  const sideClass = isRight ? ' right' : '';
  const winnerClass = isWinner ? ' weekly-summary-winner' : '';
  const winnerLabel = isWinner ? '<div class="weekly-summary-winner-label">Winner</div>' : '';
  return `
    <div class="weekly-summary-match-team-col${sideClass}${winnerClass}">
      ${winnerLabel}
      <div class="weekly-summary-match-team-inner">${_weeklySummaryTeamHtml(team)}</div>
    </div>`;
}

function _weeklySummaryPlayerHtml(p) {
  const pointsClass = p.on_roster ? 'weekly-summary-points-rostered' : 'weekly-summary-points-neutral';
  const mvpClass = p.is_mvp ? 'weekly-summary-mvp' : '';
  const mvpLabel = p.is_mvp ? '<div class="weekly-summary-mvp-label">MVP</div>' : '';
  return `
    <div class="weekly-summary-player ${mvpClass}">
      ${mvpLabel}
      <img src="${p.avatar_url || ''}" alt="" style="width:32px;height:32px;border-radius:50%;" onerror="this.style.display='none'">
      <div>${playerLink(p.player_id, p.name)}</div>
      <div class="${pointsClass}">${p.points}</div>
    </div>`;
}

function _weeklySummaryMatchHtml(m, revealed) {
  const winnerRadiant = !!m.winner_team_id && m.winner_team_id === m.radiant_team_id;
  const winnerDire = !!m.winner_team_id && m.winner_team_id === m.dire_team_id;
  // Team names and the two player groups below them share the same
  // .weekly-summary-match-row grid (col 1 / col 3), so they line up in width
  // instead of the team names spanning the full row edge-to-edge.
  let html = `
    <div class="weekly-summary-match">
      <div class="weekly-summary-match-row">
        ${_weeklySummaryTeamColHtml(m.radiant_team, winnerRadiant, false)}
        <div class="weekly-summary-match-vs-cell">
          <span>vs</span>
          ${m.vod_url ? `<a class="stream-link" style="font-size:0.75rem;" href="${_escHtml(m.vod_url)}" target="_blank" rel="noopener noreferrer">VOD ↗</a>` : ''}
        </div>
        ${_weeklySummaryTeamColHtml(m.dire_team, winnerDire, true)}
      </div>`;
  if (revealed && m.players) {
    const team1Players = m.players.filter(p => p.team_id === m.radiant_team_id);
    const team2Players = m.players.filter(p => p.team_id === m.dire_team_id);
    html += `
      <div class="weekly-summary-match-row" style="margin-top:8px;">
        <div class="weekly-summary-match-players-col">${team1Players.map(_weeklySummaryPlayerHtml).join('')}</div>
        <div class="weekly-summary-match-players-col right">${team2Players.map(_weeklySummaryPlayerHtml).join('')}</div>
      </div>`;
  }
  html += `</div>`;
  return html;
}

function renderWeeklySummaryContent(data) {
  const content = document.getElementById('weeklySummaryContent');
  let html = '';
  if (!data.series.length) {
    html = '<p style="color:#888;">No matches played during this week.</p>';
  } else {
    html = data.series.map(s => `
      <div class="weekly-summary-series">
        ${s.matches.map(m => _weeklySummaryMatchHtml(m, data.revealed)).join('')}
      </div>`).join('');
  }
  if (!data.revealed) {
    html += `<div style="margin-top:16px;text-align:center;">
      <button onclick="revealWeeklySummary(${data.week_id})">Reveal results</button>
    </div>`;
  }
  content.innerHTML = html;
}

async function revealWeeklySummary(weekId) {
  try {
    const res = await fetch(`${API}/weekly-summary/${weekId}/reveal`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) return;
    renderWeeklySummaryContent(data);
    const week = _weeklySummaryWeeks.find(w => w.week_id === weekId);
    if (week) week.revealed = true;
  } catch (_) {}
}

async function markWeeklySummarySeen() {
  try {
    await fetch(`${API}/weekly-summary/seen`, { method: 'POST' });
    const badge = document.getElementById('weeklyReportBadge');
    if (badge) badge.style.display = 'none';
  } catch (_) {}
}
