let _weeklySummaryWeeks = [];
let _weeklySummaryActiveWeekId = null;
// card_id -> roster card of the week on screen, for the thumbnail's card viewer.
let _weeklySummaryRosterCards = {};
let _weeklyRecapPromptWeek = null;

async function checkWeeklySummaryHighlight() {
  try {
    const res = await fetch(`${API}/weekly-summary`);
    if (!res.ok) return;
    const data = await res.json();
    _weeklySummaryWeeks = data.weeks || [];
    const badge = document.getElementById('weeklyReportBadge');
    if (badge) badge.style.display = data.has_unseen ? '' : 'none';
    maybeShowWeeklyRecapPrompt(data);
  } catch (_) {}
}

async function openWeeklySummary(weekId) {
  document.getElementById('weeklySummaryModal').classList.remove('hidden');
  await loadWeeklySummaryList(weekId);
  await markWeeklySummarySeen();
}

function closeWeeklySummary() {
  _stopRecap();
  document.getElementById('weeklySummaryModal').classList.add('hidden');
}

function _weeklySummaryMessage(text, isError) {
  return `<p class="weekly-summary-empty${isError ? ' err' : ''}">${_escHtml(text)}</p>`;
}

function _setWeeklySummaryColumns(rosterHtml, resultsHtml) {
  document.getElementById('weeklySummaryRoster').innerHTML = rosterHtml;
  document.getElementById('weeklySummaryContent').innerHTML = resultsHtml;
  document.getElementById('weeklySummaryRosterTotal').textContent = '';
  document.getElementById('weeklySummaryRosterMeta').textContent = '';
  document.getElementById('weeklySummaryResultsMeta').textContent = '';
}

async function loadWeeklySummaryList(weekId) {
  try {
    const res = await fetch(`${API}/weekly-summary`);
    const data = await res.json();
    if (!res.ok) { _setWeeklySummaryColumns('', _weeklySummaryMessage(data.detail, true)); return; }
    _weeklySummaryWeeks = data.weeks || [];
    renderWeeklySummaryTabs();
    if (_weeklySummaryWeeks.length) {
      const wanted = _weeklySummaryWeeks.find(w => w.week_id === weekId);
      if (wanted) await selectWeeklySummaryTab(wanted.week_id);
      else await selectWeeklySummaryTab(_weeklySummaryWeeks[0].week_id);
    } else {
      document.getElementById('weeklySummaryTabs').innerHTML = '';
      _setWeeklySummaryColumns('', _weeklySummaryMessage('No weekly reports available yet.'));
      _updateWeeklySummaryRevealFooter();
    }
  } catch (e) {
    _setWeeklySummaryColumns('', _weeklySummaryMessage(e.message, true));
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
  _updateWeeklySummaryRevealFooter();
}

function _markActiveWeeklySummaryTab(weekId) {
  [...document.getElementById('weeklySummaryTabs').children].forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.weekId, 10) === weekId);
  });
}

async function selectWeeklySummaryTab(weekId) {
  _stopRecap();
  const weekChanged = _weeklySummaryActiveWeekId !== weekId;
  _weeklySummaryActiveWeekId = weekId;
  _markActiveWeeklySummaryTab(weekId);
  if (weekChanged) {
    _setWeeklySummaryColumns(_weeklySummaryMessage('Loading…'), _weeklySummaryMessage('Loading…'));
    document.getElementById('weeklySummaryRoster').scrollTop = 0;
    document.getElementById('weeklySummaryContent').scrollTop = 0;
  }
  try {
    const res = await fetch(`${API}/weekly-summary/${weekId}`);
    const data = await res.json();
    if (!res.ok) { _setWeeklySummaryColumns('', _weeklySummaryMessage(data.detail, true)); return; }
    renderWeeklySummaryContent(data);
  } catch (e) {
    _setWeeklySummaryColumns('', _weeklySummaryMessage(e.message, true));
  }
}

function _weeklySummaryGameDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric"}) : '';
}

// ---------------------------------------------------------------------------
// My roster column (issue #151)
// ---------------------------------------------------------------------------

function _recapPts(x) {
  return Number(x || 0).toFixed(1);
}

function _recapPct(x) {
  return String(Number(x || 0));
}

// mvpStep: the card's breakdown step for this game's MVP bonus (issue #152), if any.
function _weeklySummaryGameHtml(g, mvpStep, pending) {
  const result = g.won == null ? ''
    : `<span class="weekly-summary-game-result ${g.won ? 'win' : 'loss'}">${g.won ? 'WIN' : 'LOSS'}</span>`;
  const bonus = mvpStep
    ? ` <span class="recap-mvp-bonus">+${_escHtml(Number(mvpStep.points || 0).toFixed(1))}</span>`
    : '';
  const mvp = g.is_mvp
    ? `<span class="weekly-summary-game-mvp${pending && mvpStep ? ' pending' : ''}"><span>MVP</span>${bonus}</span>`
    : '';
  const pts = g.scored
    ? `<span class="weekly-summary-game-pts">${Number(g.points).toFixed(1)}</span>`
    : '<span class="weekly-summary-game-pts not-scored">Not scored</span>';
  const opponent = g.opponent_team_id ? teamLink(g.opponent_team_id, g.opponent_name || 'Unknown') : 'Unknown';
  return `
    <li class="weekly-summary-game" data-match-id="${Number(g.match_id)}">
      <span class="weekly-summary-game-date">${_escHtml(_weeklySummaryGameDate(g.start_time))}</span>
      <span class="weekly-summary-game-opp">vs ${opponent}</span>
      <span class="weekly-summary-game-num">G${_escHtml(g.game_number)}</span>
      ${result}${mvp}
      ${pts}
    </li>`;
}

// One breakdown chip (issue #152). pending: a dashed placeholder whose points the
// reveal animation fills in; otherwise lit with its final points.
function _recapChipHtml(step, index, pending) {
  const state = pending ? 'pending' : 'lit';
  return `<span class="recap-chip ${state}" data-step="${Number(index)}">${_escHtml(String(step.label || '').toUpperCase())} +${_escHtml(_recapPct(step.pct))}%<span class="recap-chip-pts"> +${_escHtml(Number(step.points || 0).toFixed(1))}</span></span>`;
}

// pending (issue #152): the card as the reveal animation inserts it, with its chips,
// rarity caption and MVP bonuses still to be revealed and its total at 0.
function _weeklySummaryRosterCardHtml(c, revealed, pending = false) {
  const rarity = String(c.card_type || '');
  const breakdown = revealed && c.breakdown ? c.breakdown : null;
  const steps = breakdown ? (breakdown.steps || []) : [];
  const rarityStep = steps.find(st => st.kind === 'rarity');
  const rarityCaption = rarityStep
    ? `<div class="weekly-summary-roster-rarity-cap${pending ? ' pending' : ''}" data-rarity="${_escHtml(rarity)}">+${_escHtml(_recapPct(rarityStep.pct))}% +${_escHtml(Number(rarityStep.points || 0).toFixed(1))}</div>`
    : '';
  // The player's avatar (Steam "full", 184px) with a rarity-coloured border, not the
  // card image: the full card shrunk to thumbnail size blurs and its modifier text is
  // unreadable. Clicking opens the card viewer with the full card. Initials sit behind
  // the avatar and show when there is none or it fails to load.
  const avatar = _safeUrl(c.avatar_url);
  const initials = String(c.player_name || '?').trim().slice(0, 2).toUpperCase();
  const thumb = `
    <div class="weekly-summary-roster-thumb-col" data-rarity="${_escHtml(rarity)}">
      <button type="button" class="weekly-summary-roster-thumb" data-rarity="${_escHtml(rarity)}"
              onclick="_weeklySummaryShowCard(${Number(c.card_id)})"
              aria-label="Open card ${_escHtml(c.player_name)}">
        <span class="weekly-summary-roster-initials" aria-hidden="true">${_escHtml(initials)}</span>
        ${avatar ? `<img class="weekly-summary-roster-avatar" src="${_escHtml(avatar)}" alt="" loading="lazy" onerror="this.remove()" />` : ''}
      </button>
      <span class="weekly-summary-roster-thumb-rarity" aria-hidden="true">${_escHtml(rarity.toUpperCase())}</span>
      ${rarityCaption}
    </div>`;
  const names = `
      <div class="weekly-summary-roster-names">
        <div class="weekly-summary-roster-player">${playerLink(c.player_id, c.player_name)}</div>
        <div class="weekly-summary-roster-team">${teamLink(c.team_id, c.team_name || 'No team')}</div>
      </div>`;
  if (!revealed) {
    return `
    <article class="weekly-summary-roster-card">
      ${thumb}
      <div class="weekly-summary-roster-main">
        <div class="weekly-summary-roster-top">${names}</div>
      </div>
    </article>`;
  }
  let stateClass = '';
  let statusTag = '';
  let note = '';
  if (c.subbed_in) {
    stateClass = ' subbed-in';
    statusTag = '<span class="weekly-summary-tag state">SUBBED IN</span>';
    note = `<div class="weekly-summary-roster-note">From your bench, for ${_escHtml(c.subbed_in_for || 'a card')}, who did not play this week</div>`;
  } else if (c.subbed_out) {
    stateClass = ' subbed-out';
    statusTag = '<span class="weekly-summary-tag state">NOT COUNTED</span>';
    const sub = Object.values(_weeklySummaryRosterCards).find(x => x.subbed_in && x.subbed_in_for === c.player_name);
    note = `<div class="weekly-summary-roster-note">No matches this week. Replaced by ${_escHtml(sub ? sub.player_name : 'a bench card')}</div>`;
  }
  // Tag row, left to right in the order the bonuses are added: RAW, modifiers, status.
  let chips = '';
  if (breakdown) {
    chips += `<span class="recap-chip ${pending ? 'pending' : 'lit'}" data-step="raw">RAW <span class="recap-chip-raw" aria-hidden="true">${_escHtml(pending ? '0.0' : _recapPts(breakdown.raw))}</span><span class="recap-sr">${_escHtml(_recapPts(breakdown.raw))}</span></span>`;
    steps.forEach((st, i) => { if (st.kind === 'modifier') chips += _recapChipHtml(st, i, pending); });
  }
  const mvpSteps = {};
  steps.forEach(st => { if (st.kind === 'mvp') mvpSteps[st.match_id] = st; });
  const games = (c.games || []).length
    ? `<ul class="weekly-summary-games">${c.games.map(g => _weeklySummaryGameHtml(g, mvpSteps[g.match_id], pending)).join('')}</ul>`
    : '<div class="weekly-summary-roster-note">No games this week</div>';
  // The counting number is aria-hidden; the final points are in the accessible text
  // from the start, so screen readers never hear the count.
  const shown = pending ? '0.0' : _recapPts(c.week_points);
  return `
    <article class="weekly-summary-roster-card${stateClass}" data-card-id="${Number(c.card_id)}">
      ${thumb}
      <div class="weekly-summary-roster-main">
        <div class="weekly-summary-roster-top">
          ${names}
          <div class="weekly-summary-roster-pts"><span class="recap-total" aria-hidden="true">${_escHtml(shown)}</span><span class="recap-unit" aria-hidden="true">pts</span><span class="recap-sr">${_escHtml(Number(c.week_points || 0).toFixed(1))} points</span></div>
        </div>
        <div class="weekly-summary-roster-tags">${chips}${statusTag}</div>
        ${note}
        ${games}
      </div>
    </article>`;
}

function _weeklySummaryRosterHtml(roster, revealed) {
  const cards = (roster && roster.cards) || [];
  _weeklySummaryRosterCards = {};
  cards.forEach(c => { _weeklySummaryRosterCards[c.card_id] = c; });
  if (!cards.length) return _weeklySummaryMessage('No cards on your roster this week.');
  if (!revealed) {
    return `<p class="weekly-summary-roster-hint">Reveal results to see your points</p>
      ${cards.map(c => _weeklySummaryRosterCardHtml(c, false)).join('')}`;
  }
  const counted = cards.filter(c => c.counted);
  const didNotPlay = cards.filter(c => c.subbed_out);
  let html = counted.map(c => _weeklySummaryRosterCardHtml(c, true)).join('');
  if (didNotPlay.length) {
    html += `<div class="weekly-summary-roster-group">Did not play</div>
      ${didNotPlay.map(c => _weeklySummaryRosterCardHtml(c, true)).join('')}`;
  }
  return html;
}

function _renderWeeklySummaryRosterHeader(data) {
  const roster = data.roster || {cards: []};
  const cards = roster.cards || [];
  const total = document.getElementById('weeklySummaryRosterTotal');
  const meta = document.getElementById('weeklySummaryRosterMeta');
  if (data.revealed) {
    const counted = cards.filter(c => c.counted).length;
    const subs = cards.filter(c => c.subbed_in).length;
    total.textContent = `Week total ${Number(roster.week_total || 0).toFixed(1)} pts`;
    meta.textContent = `${counted} counted · ${subs} ${subs === 1 ? 'substitution' : 'substitutions'}`;
  } else {
    total.textContent = '';
    meta.textContent = `${cards.length} ${cards.length === 1 ? 'card' : 'cards'}`;
  }
}

function _weeklySummaryShowCard(cardId) {
  const card = _weeklySummaryRosterCards[cardId];
  if (!card) return;
  const footer = card.week_points != null ? `${Number(card.week_points).toFixed(1)} wk pts` : '';
  showCard({...card, id: card.card_id}, footer);
}

// ---------------------------------------------------------------------------
// Reveal animation (issue #152)
// ---------------------------------------------------------------------------

// runId: every wait and tween captures it and stops when it changes, so Skip, a
// week tab switch and closing the report (which all bump it) stop the animation.
// cancels: the pending timers and animation frames, cleared on stop.
let _recapAnimation = {runId: 0, weekId: null, playing: false, data: null, cancels: new Map()};
let _recapCancelSeq = 0;

const _RECAP_SLOT_MS = 340;
const _RECAP_SLIDE_MS = 420;
const _RECAP_STEP_MS = 700;
const _RECAP_TOTAL_MS = 600;

function _recapStorageKey() {
  return `weeklyRecapPlayed:${activeUserId ?? 'anon'}`;
}

function _recapPlayedWeeks() {
  try {
    const ids = JSON.parse(localStorage.getItem(_recapStorageKey()) || '[]');
    return Array.isArray(ids) ? ids : [];
  } catch (_) {
    return [];
  }
}

function _markRecapPlayed(weekId) {
  try {
    const ids = _recapPlayedWeeks();
    if (!ids.includes(weekId)) ids.push(weekId);
    localStorage.setItem(_recapStorageKey(), JSON.stringify(ids.slice(-200)));
  } catch (_) {}
}

function _recapAlive(run) {
  return run === _recapAnimation.runId;
}

function _recapWait(run, ms) {
  if (!_recapAlive(run)) return Promise.resolve(false);
  return new Promise(resolve => {
    const key = ++_recapCancelSeq;
    const id = setTimeout(() => {
      _recapAnimation.cancels.delete(key);
      resolve(_recapAlive(run));
    }, ms);
    _recapAnimation.cancels.set(key, () => { clearTimeout(id); resolve(false); });
  });
}

// requestAnimationFrame tween: onFrame(eased 0..1) each frame for ms milliseconds.
function _recapTween(run, ms, ease, onFrame) {
  if (!_recapAlive(run)) return Promise.resolve(false);
  return new Promise(resolve => {
    const key = ++_recapCancelSeq;
    let frame = 0;
    let start = null;
    const tick = now => {
      if (!_recapAlive(run)) { _recapAnimation.cancels.delete(key); resolve(false); return; }
      if (start === null) start = now;
      const t = Math.min(1, (now - start) / ms);
      onFrame(ease(t));
      if (t < 1) { frame = requestAnimationFrame(tick); return; }
      _recapAnimation.cancels.delete(key);
      resolve(true);
    };
    frame = requestAnimationFrame(tick);
    _recapAnimation.cancels.set(key, () => { cancelAnimationFrame(frame); resolve(false); });
  });
}

const _recapEaseIn = t => t * t * t;
const _recapEaseOut = t => 1 - Math.pow(1 - t, 3);

// Restart a CSS animation class on el.
function _recapRestartClass(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

function _recapFloat(anchor, points, rarity) {
  const f = document.createElement('span');
  f.className = 'recap-float';
  f.setAttribute('aria-hidden', 'true');
  if (rarity) f.dataset.rarity = rarity;
  f.textContent = `+${_recapPts(points)}`;
  f.addEventListener('animationend', () => f.remove());
  anchor.appendChild(f);
}

function _updateRecapButtons() {
  const skip = document.getElementById('weeklyRecapSkip');
  const replay = document.getElementById('weeklyRecapReplay');
  if (!skip || !replay) return;
  const data = _recapAnimation.data;
  const playable = !!(data && data.revealed && data.week_id === _weeklySummaryActiveWeekId
    && ((data.roster && data.roster.cards) || []).some(c => c.counted && c.breakdown));
  skip.classList.toggle('hidden', !_recapAnimation.playing);
  replay.classList.toggle('hidden', _recapAnimation.playing || !playable || _prefersReducedMotion());
}

// Stops a running animation at once: bumps the run id and clears every pending
// timer and animation frame. The caller renders whatever comes next.
function _stopRecap() {
  _recapAnimation.runId += 1;
  _recapAnimation.cancels.forEach(cancel => cancel());
  _recapAnimation.cancels.clear();
  _recapAnimation.playing = false;
  const body = document.getElementById('weeklySummaryRoster');
  if (body) body.removeAttribute('aria-busy');
  _updateRecapButtons();
}

// Runs after a revealed week's columns render: plays once per week per browser,
// never with reduced motion; otherwise the finished (static) state stays.
function _maybePlayRecap(weekId, data) {
  _updateRecapButtons();
  if (!data || !data.revealed) return;
  const cards = (data.roster && data.roster.cards) || [];
  if (!cards.some(c => c.counted && c.breakdown)) return;
  if (_prefersReducedMotion()) return;
  if (_recapPlayedWeeks().includes(weekId)) return;
  _playRecap(data);
}

function skipWeeklyRecap() {
  const data = _recapAnimation.data;
  _stopRecap();
  if (!data) return;
  _markRecapPlayed(data.week_id);
  document.getElementById('weeklySummaryRoster').innerHTML =
    _weeklySummaryRosterHtml(data.roster || {cards: []}, data.revealed);
  _renderWeeklySummaryRosterHeader(data);
  _updateRecapButtons();
}

function replayWeeklyRecap() {
  const data = _recapAnimation.data;
  if (!data || !data.revealed || _prefersReducedMotion()) return;
  _playRecap(data);
}

async function _playRecap(data) {
  _stopRecap();
  const run = _recapAnimation.runId;
  _recapAnimation.weekId = data.week_id;
  _recapAnimation.playing = true;
  const roster = data.roster || {cards: []};
  const body = document.getElementById('weeklySummaryRoster');
  const total = document.getElementById('weeklySummaryRosterTotal');
  const cards = roster.cards || [];
  const counted = cards.filter(c => c.counted);
  const didNotPlay = cards.filter(c => c.subbed_out);
  _weeklySummaryRosterHtml(roster, true);  // fills the card lookup for thumbnails
  body.innerHTML = '';
  body.setAttribute('aria-busy', 'true');
  body.scrollTop = 0;
  let weekTotal = 0;
  total.textContent = `Week total ${_recapPts(0)} pts`;
  _updateRecapButtons();

  for (let i = counted.length - 1; i >= 0; i--) {
    const card = counted[i];
    if (!await _recapRevealCard(run, body, card)) return;
    const from = weekTotal;
    weekTotal += Number(card.week_points || 0);
    const to = i === 0 ? Number(roster.week_total || 0) : weekTotal;
    if (!await _recapTween(run, _RECAP_TOTAL_MS, _recapEaseOut,
      e => { total.textContent = `Week total ${_recapPts(from + (to - from) * e)} pts`; })) return;
  }
  if (!_recapAlive(run)) return;
  if (didNotPlay.length) {
    body.insertAdjacentHTML('beforeend', `<div class="weekly-summary-roster-group">Did not play</div>
      ${didNotPlay.map(c => _weeklySummaryRosterCardHtml(c, true)).join('')}`);
  }
  total.textContent = `Week total ${_recapPts(roster.week_total)} pts`;
  _recapAnimation.playing = false;
  body.removeAttribute('aria-busy');
  _markRecapPlayed(data.week_id);
  _updateRecapButtons();
}

// One counted card: open its slot at the top, slide it in from the left, count up
// its raw points, then play each breakdown step. Resolves false when cancelled.
async function _recapRevealCard(run, body, card) {
  const slot = document.createElement('div');
  slot.className = 'recap-slot';
  slot.innerHTML = _weeklySummaryRosterCardHtml(card, true, true);
  const el = slot.firstElementChild;
  el.classList.add('recap-current', 'recap-slide');
  body.prepend(slot);
  slot.style.height = '0px';
  void slot.offsetHeight;
  slot.style.height = `${el.offsetHeight + parseFloat(getComputedStyle(el).marginBottom || 0)}px`;
  if (!await _recapWait(run, _RECAP_SLOT_MS)) return false;
  slot.style.height = '';
  el.classList.add('in');
  if (!await _recapWait(run, _RECAP_SLIDE_MS)) return false;
  slot.classList.add('open');  // stop clipping, so the current-card glow shows

  // Raw count-up: accelerating, the number grows and glows; RAW chip highlighted
  // with the running value for the whole count.
  const breakdown = card.breakdown || {raw: card.week_points, steps: []};
  const raw = Number(breakdown.raw || 0);
  const num = el.querySelector('.recap-total');
  const rawChip = el.querySelector('.recap-chip[data-step="raw"]');
  const rawValue = el.querySelector('.recap-chip-raw');
  rawChip.classList.remove('pending');
  rawChip.classList.add('hl');
  const countMs = Math.min(Math.max(1000 + raw * 35, 1000), 3000);
  const counted = await _recapTween(run, countMs, _recapEaseIn, e => {
    const v = _recapPts(raw * e);
    num.textContent = v;
    rawValue.textContent = v;
    num.style.transform = `scale(${1 + 0.25 * e})`;
    num.style.textShadow = `0 0 ${Math.round(16 * e)}px var(--accent)`;
  });
  if (!counted) return false;
  num.textContent = _recapPts(raw);
  rawValue.textContent = _recapPts(raw);
  num.style.transform = '';
  num.style.textShadow = '';
  if (!await _recapWait(run, 200)) return false;
  rawChip.classList.remove('hl');
  rawChip.classList.add('lit');

  // Steps in breakdown order: rarity, modifiers left to right, then MVP per game.
  // The card total jumps to each new value at once, with a pop and a floating "+points".
  let running = raw;
  const ptsBox = el.querySelector('.weekly-summary-roster-pts');
  const steps = breakdown.steps || [];
  for (let s = 0; s < steps.length; s++) {
    const step = steps[s];
    let target = null;
    let rarity = null;
    if (step.kind === 'rarity') {
      target = el.querySelector('.weekly-summary-roster-thumb-col');
      rarity = target.dataset.rarity;
      target.classList.add('recap-rarity-glow');
      const cap = el.querySelector('.weekly-summary-roster-rarity-cap');
      if (cap) cap.classList.remove('pending');
    } else if (step.kind === 'modifier') {
      target = el.querySelector(`.recap-chip[data-step="${s}"]`);
      if (target) { target.classList.remove('pending'); target.classList.add('hl'); }
    } else if (step.kind === 'mvp') {
      target = el.querySelector(`.weekly-summary-game[data-match-id="${Number(step.match_id)}"]`);
      if (target) {
        target.classList.add('recap-mvp-active');
        const tag = target.querySelector('.weekly-summary-game-mvp');
        if (tag) { tag.classList.remove('pending'); tag.classList.add('hl'); }
      }
    }
    running += Number(step.points || 0);
    num.textContent = s === steps.length - 1 ? _recapPts(card.week_points) : _recapPts(running);
    _recapRestartClass(num, 'recap-pop');
    _recapFloat(ptsBox, step.points, rarity);
    if (!await _recapWait(run, _RECAP_STEP_MS)) return false;
    if (target) {
      target.classList.remove('recap-rarity-glow', 'recap-mvp-active', 'hl');
      if (step.kind === 'modifier') target.classList.add('lit');
      const tag = step.kind === 'mvp' ? target.querySelector('.weekly-summary-game-mvp') : null;
      if (tag) tag.classList.remove('hl');
    }
  }
  num.textContent = _recapPts(card.week_points);
  el.classList.remove('recap-current', 'recap-slide', 'in');
  slot.replaceWith(el);
  return true;
}

// ---------------------------------------------------------------------------
// Match results column
// ---------------------------------------------------------------------------

function _weeklySummaryTeamHtml(team) {
  if (!team) return '<span class="weekly-summary-unknown">Unknown</span>';
  // Team crests are usually non-square (wordmarks, rectangular badges), so — unlike
  // the circular player avatars — this stays a plain rounded box sized large enough
  // to actually read, rather than cropping the logo into a tiny circle.
  const logoUrl = team.logo_url && (team.logo_url.startsWith('/') ? team.logo_url : _safeUrl(team.logo_url));
  const logo = logoUrl
    ? `<img class="weekly-summary-team-logo" src="${_escHtml(logoUrl)}" alt="" onerror="this.style.display='none'">`
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

function _weeklySummaryPlayerHtml(p, subbedInPlayerIds) {
  // Issue #151: a player on the user's counted roster gets a filled "YOUR CARD"
  // tile showing the user's card points for that game instead of match points.
  const owned = p.card_points != null;
  const ownedClass = owned ? ' weekly-summary-owned' : '';
  const ownedLabel = owned
    ? `<div class="weekly-summary-owned-label">${subbedInPlayerIds.has(p.player_id) ? 'YOUR SUB' : 'YOUR CARD'}</div>`
    : '';
  const pointsClass = owned ? 'weekly-summary-points-rostered' : 'weekly-summary-points-neutral';
  const mvpClass = p.is_mvp ? ' weekly-summary-mvp' : '';
  const mvpLabel = p.is_mvp ? '<div class="weekly-summary-mvp-label">MVP</div>' : '';
  const avatar = _safeUrl(p.avatar_url);
  let pts = '—';
  if (owned) pts = Number(p.card_points).toFixed(1);
  else if (p.points != null) pts = Number(p.points).toFixed(1);
  return `
    <div class="weekly-summary-player${mvpClass}${ownedClass}">
      ${mvpLabel}${ownedLabel}
      ${avatar ? `<img class="weekly-summary-avatar" src="${_escHtml(avatar)}" alt="" onerror="this.style.display='none'">` : ''}
      <div>${playerLink(p.player_id, p.name)}</div>
      <div class="${pointsClass}">${_escHtml(pts)}</div>
    </div>`;
}

function _weeklySummaryMatchHtml(m, revealed, subbedInPlayerIds) {
  const winnerRadiant = !!m.winner_team_id && m.winner_team_id === m.radiant_team_id;
  const winnerDire = !!m.winner_team_id && m.winner_team_id === m.dire_team_id;
  // Played-on date — shown regardless of reveal state, like the team names and
  // VOD link. Same format the player profile match history uses (app-players.js).
  const playedOn = m.start_time
    ? new Date(m.start_time * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "2-digit"})
    : '';
  const vod = _safeUrl(m.vod_url);
  // Team names and the two player groups below them share the same
  // .weekly-summary-match-row grid (col 1 / col 3), so they line up in width
  // instead of the team names spanning the full row edge-to-edge.
  let html = `
    <div class="weekly-summary-match">
      <div class="weekly-summary-match-row">
        ${_weeklySummaryTeamColHtml(m.radiant_team, winnerRadiant, false)}
        <div class="weekly-summary-match-vs-cell">
          <span>vs</span>
          ${playedOn ? `<span class="weekly-summary-match-date">${_escHtml(playedOn)}</span>` : ''}
          ${m.excluded_from_scoring ? '<span class="badge common">Not scored</span>' : ''}
          ${vod ? `<a class="stream-link weekly-summary-vod" href="${_escHtml(vod)}" target="_blank" rel="noopener noreferrer">VOD ↗</a>` : ''}
        </div>
        ${_weeklySummaryTeamColHtml(m.dire_team, winnerDire, true)}
      </div>`;
  if (revealed && m.players) {
    const team1Players = m.players.filter(p => p.team_id === m.radiant_team_id);
    const team2Players = m.players.filter(p => p.team_id === m.dire_team_id);
    const tile = p => _weeklySummaryPlayerHtml(p, subbedInPlayerIds);
    html += `
      <div class="weekly-summary-match-row weekly-summary-match-players">
        <div class="weekly-summary-match-players-col">${team1Players.map(tile).join('')}</div>
        <div class="weekly-summary-match-players-col right">${team2Players.map(tile).join('')}</div>
      </div>`;
  }
  html += `</div>`;
  return html;
}

function renderWeeklySummaryContent(data) {
  const content = document.getElementById('weeklySummaryContent');
  const roster = data.roster || {cards: []};
  const subbedInPlayerIds = new Set((roster.cards || []).filter(c => c.subbed_in).map(c => c.player_id));
  document.getElementById('weeklySummaryRoster').innerHTML = _weeklySummaryRosterHtml(roster, data.revealed);
  _renderWeeklySummaryRosterHeader(data);
  _recapAnimation.data = data;

  const gameCount = data.series.reduce((n, s) => n + s.matches.length, 0);
  document.getElementById('weeklySummaryResultsMeta').textContent =
    `${data.series.length} series · ${gameCount} ${gameCount === 1 ? 'game' : 'games'}`;
  let html = '';
  if (!data.series.length) {
    html = _weeklySummaryMessage('No matches played during this week.');
  } else {
    html = data.series.map(s => `
      <div class="weekly-summary-series">
        ${s.matches.map(m => _weeklySummaryMatchHtml(m, data.revealed, subbedInPlayerIds)).join('')}
      </div>`).join('');
  }
  content.innerHTML = html;
  // Issue #129: bench substitutions run some hours after the week ends; until then
  // the "on roster" marks may still change. Shown in the roster column header.
  if (data.revealed && data.substitutions_pending) {
    const note = document.createElement('p');
    note.className = 'weekly-summary-subs-pending';
    note.textContent = `Bench substitutions are made ${data.substitution_delay_hours} hours after the week ends; roster marks may change.`;
    document.getElementById('weeklySummaryRosterMeta').appendChild(note);
  }
  _maybePlayRecap(data.week_id, data);
}

// Shows the docked reveal footer whenever at least one currently-listed week is
// not yet revealed; hides it once everything listed has been revealed. Called
// from renderWeeklySummaryTabs() and after a reveal-all completes.
function _updateWeeklySummaryRevealFooter() {
  const footer = document.getElementById('weeklySummaryRevealFooter');
  if (!footer) return;
  const anyUnrevealed = _weeklySummaryWeeks.some(w => w.revealed === false);
  footer.classList.toggle('hidden', !anyUnrevealed);
}

async function revealAllWeeklySummaries() {
  try {
    const res = await fetch(`${API}/weekly-summary/reveal-all`, { method: 'POST' });
    if (!res.ok) return;
    _weeklySummaryWeeks.forEach(w => { w.revealed = true; });
    _updateWeeklySummaryRevealFooter();
    if (_weeklySummaryActiveWeekId != null) {
      await selectWeeklySummaryTab(_weeklySummaryActiveWeekId);
    }
  } catch (_) {}
}

async function markWeeklySummarySeen() {
  try {
    await fetch(`${API}/weekly-summary/seen`, { method: 'POST' });
    const badge = document.getElementById('weeklyReportBadge');
    if (badge) badge.style.display = 'none';
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// "Recap is ready" popup (issue #151)
// ---------------------------------------------------------------------------

function _weeklyRecapOtherOverlayOpen() {
  return [...document.querySelectorAll('.modal-overlay, .reveal-overlay')]
    .some(el => el.id !== 'weeklyRecapPrompt' && !el.classList.contains('hidden')
                && getComputedStyle(el).display !== 'none');
}

// Shown once per newest report week. Nothing is marked when it is skipped, so a
// later page load shows it instead.
function maybeShowWeeklyRecapPrompt(data) {
  if (!data || !data.show_prompt || !data.latest_week) return;
  if (_weeklyRecapOtherOverlayOpen()) return;
  if (typeof _tour !== 'undefined' && _tour) return;
  if (activeMustChangePassword) return;
  _weeklyRecapPromptWeek = data.latest_week;
  const label = String(data.latest_week.label ?? '');
  const title = /^week\b/i.test(label) ? label : `Week ${label}`;
  document.getElementById('weeklyRecapPromptTitle').textContent = `${title} recap is ready`;
  document.getElementById('weeklyRecapPrompt').classList.remove('hidden');
  // After the generic modal focus handler (app-init.js), which focuses the X.
  setTimeout(() => document.getElementById('weeklyRecapPromptOpen').focus(), 0);
}

function _hideWeeklyRecapPrompt() {
  document.getElementById('weeklyRecapPrompt').classList.add('hidden');
}

// Close, X, Esc (data-close) and a backdrop click: announced, but not seen.
async function dismissWeeklyRecapPrompt() {
  _hideWeeklyRecapPrompt();
  try {
    await fetch(`${API}/weekly-summary/prompted`, { method: 'POST' });
  } catch (_) {}
}

// "Open recap": opens the report on the announced week; openWeeklySummary then
// marks it seen (POST /weekly-summary/seen also marks it announced).
async function openWeeklyRecapFromPrompt() {
  const week = _weeklyRecapPromptWeek;
  _hideWeeklyRecapPrompt();
  await openWeeklySummary(week ? week.week_id : undefined);
}

document.getElementById('weeklyRecapPrompt')?.addEventListener('keydown', function(e) {
  if (e.key !== 'Tab') return;
  const focusables = [...this.querySelectorAll('button:not([disabled])')];
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault(); last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault(); first.focus();
  } else if (!this.contains(document.activeElement)) {
    e.preventDefault(); first.focus();
  }
});
