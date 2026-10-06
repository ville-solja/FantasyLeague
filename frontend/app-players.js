let _playersData = [];
let _playerSort = { col: null, dir: "desc" };

async function loadPlayers() {
  try {
    const res = await fetch(`${API}/players`);
    const rows = await res.json();
    if (!res.ok) throw new Error(rows.detail || "Failed to load");
    _playersData = rows;
    // The player's sort stays across refreshes (issue #159), so an unchanged
    // refresh leaves the table as it is.
    _initPlayerSortHeaders();
    renderPlayers(_getFilteredPlayers());
    _renderMvpLeaderboard();
    setStatus("playersStatus", `${rows.length} players`);
  } catch (e) {
    setStatus("playersStatus", e.message, false);
  }
}

function _renderMvpLeaderboard() {
  const tbody = document.getElementById("mvpLeaderboardBody");
  if (!tbody) return;
  const ranked = _playersData
    .filter(p => (p.mvp_count || 0) > 0)
    .sort((a, b) => b.mvp_count - a.mvp_count)
    .slice(0, 10);
  if (!ranked.length) {
    renderIfChanged(tbody, "<tr><td colspan='3' style='color:#444'>No MVPs awarded yet</td></tr>");
    return;
  }
  renderIfChanged(tbody, ranked.map((p, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><img src="${_escHtml(_safeUrl(p.avatar_url))}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(p.id, p.name)}</td>
      <td>${p.mvp_count}</td>
    </tr>`).join(""));
}

function _getFilteredPlayers() {
  const q = document.getElementById("playersSearch").value.toLowerCase();
  return _playersData.filter(p =>
    p.name.toLowerCase().includes(q) || (p.team_name || "").toLowerCase().includes(q)
  );
}

function filterPlayers() {
  renderPlayers(_getFilteredPlayers());
}

function _sortPlayers(rows) {
  if (!_playerSort.col) return rows;
  const col = _playerSort.col;
  const asc = _playerSort.dir === "asc";
  return [...rows].sort((a, b) => {
    const av = a[col], bv = b[col];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = typeof av === "string"
      ? av.localeCompare(bv)
      : av - bv;
    return asc ? cmp : -cmp;
  });
}

function _initPlayerSortHeaders() {
  const head = document.getElementById("playersTableHead");
  if (!head) return;
  head.querySelectorAll("th[data-col]").forEach(th => {
    th.classList.add("sortable");
    th.classList.remove("sort-asc", "sort-desc");
    if (_playerSort.col === th.getAttribute("data-col")) {
      th.classList.add(_playerSort.dir === "asc" ? "sort-asc" : "sort-desc");
    }
    th.onclick = () => {
      const col = th.getAttribute("data-col");
      if (_playerSort.col === col) {
        _playerSort.dir = _playerSort.dir === "asc" ? "desc" : "asc";
      } else {
        _playerSort.col = col;
        _playerSort.dir = th.getAttribute("data-default-dir") || "desc";
      }
      head.querySelectorAll("th").forEach(h => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(_playerSort.dir === "asc" ? "sort-asc" : "sort-desc");
      renderPlayers(_getFilteredPlayers());
    };
  });
}

function renderPlayers(rows) {
  const sorted = _sortPlayers(rows);
  const tbody = document.getElementById("playersBody");
  if (!sorted.length) {
    renderIfChanged(tbody, "<tr><td colspan='6' style='color:#444'>No players found</td></tr>");
    return;
  }
  renderIfChanged(tbody, sorted.map(p => `
    <tr>
      <td><img src="${_escHtml(_safeUrl(p.avatar_url))}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(p.id, p.name)}</td>
      <td>${p.team_id ? teamLink(p.team_id, p.team_name) : (_escHtml(p.team_name) || "—")}</td>
      <td>${p.matches}</td>
      <td>${Number(p.avg_points).toFixed(1)}</td>
      <td>${Number(p.total_points).toFixed(1)}</td>
      <td>${p.mvp_count}</td>
    </tr>`).join(""));
}

async function loadTeams() {
  try {
    const res = await fetch(`${API}/teams`);
    const rows = await res.json();
    if (!res.ok) throw new Error(rows.detail || "Failed to load");
    const tbody = document.getElementById("teamsBody");
    if (!rows.length) {
      renderIfChanged(tbody, "<tr><td colspan='3' style='color:#444'>No teams found</td></tr>");
      setStatus("teamsStatus", "");
      return;
    }
    renderIfChanged(tbody, rows.map(t => `
      <tr>
        <td>${teamLink(t.id, t.name)}</td>
        <td>${t.matches}</td>
        <td>${t.player_count}</td>
      </tr>`).join(""));
    setStatus("teamsStatus", `${rows.length} teams`);
  } catch (e) {
    setStatus("teamsStatus", e.message, false);
  }
}

async function openPlayerModal(playerId) {
  const modal = document.getElementById("playerModal");
  modal.classList.remove("hidden");
  document.getElementById("playerModalName").textContent = "Loading...";
  document.getElementById("playerModalTeam").innerHTML = "";
  document.getElementById("playerModalAvatar").style.display = "none";
  document.getElementById("playerModalStats").innerHTML = "";
  document.getElementById("playerModalHistory").innerHTML = "";
  document.getElementById("playerModalStatus").textContent = "";
  const profileEl = document.getElementById("playerProfile");
  if (profileEl) { profileEl.style.display = "none"; profileEl.innerHTML = ""; }

  try {
    const res = await fetch(`${API}/players/${playerId}`);
    const p = await res.json();
    if (!res.ok) {
      document.getElementById("playerModalName").textContent = "";
      setStatus("playerModalStatus", p.detail || "Failed to load", false);
      return;
    }

    const avatar = document.getElementById("playerModalAvatar");
    const avatarUrl = _safeUrl(p.avatar_url);
    if (avatarUrl) { avatar.src = avatarUrl; avatar.style.display = ""; }

    document.getElementById("playerModalName").textContent = p.name;
    document.getElementById("playerModalTeam").innerHTML = p.team_id
      ? `<span class="entity-link" tabindex="0" role="button" onclick="closePlayerModal();openTeamModal(${p.team_id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();closePlayerModal();openTeamModal(${p.team_id})}">${_escHtml(p.team_name)}</span>`
      : _escHtml(p.team_name || "");

    document.getElementById("playerModalStats").innerHTML = `
      <div class="player-modal-stat-grid">
        <div class="player-modal-stat"><div class="val">${p.matches}</div><div class="lbl">Matches</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.avg_points).toFixed(1)}</div><div class="lbl">Avg pts</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.total_points).toFixed(1)}</div><div class="lbl">Total pts</div></div>
        ${p.best_match ? `<div class="player-modal-stat"><div class="val">${Number(p.best_match.fantasy_points).toFixed(1)}</div><div class="lbl">Best match</div></div>` : ""}
      </div>`;

    if (!p.match_history.length) {
      document.getElementById("playerModalHistory").innerHTML =
        "<tr><td colspan='9' style='color:#444'>No matches yet</td></tr>";
    } else {
      document.getElementById("playerModalHistory").innerHTML = p.match_history.map(m => {
        const date = m.start_time
          ? new Date(m.start_time * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "2-digit"})
          : "—";
        const mvpStar = m.is_mvp ? '<span style="font-size:0.85rem;color:#f5c842;">★</span>' : '';
        const opponent = m.opponent_team_id ? teamLink(m.opponent_team_id, m.opponent_team_name) : (_escHtml(m.opponent_team_name) || "—");
        return `<tr>
          <td>${mvpStar}</td>
          <td>${date}</td>
          <td>${_matchPointsCellHtml(m)}</td>
          <td>${m.kills}/${m.assists}/${m.deaths}</td>
          <td>${Math.round(m.gold_per_min)}</td>
          <td>${m.obs_placed ?? 0}</td>
          <td>${m.tower_damage ?? 0}</td>
          <td>${opponent}</td>
          <td><a class="stream-link" href="https://www.opendota.com/matches/${m.match_id}" target="_blank" rel="noopener noreferrer">↗</a></td>
        </tr>`;
      }).join("");
    }

    // Non-blocking profile fetch — modal shows immediately even if profile unavailable
    fetch(`${API}/players/${playerId}/profile`).then(async r => {
      if (!r.ok) return;
      renderPlayerProfile(await r.json());
    }).catch(() => {});
  } catch (e) {
    setStatus("playerModalStatus", e.message, false);
  }
}

const _PARTIAL_STATS_TOOLTIP =
  "The replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0.";
const _NOT_SCORED_TOOLTIP = "An admin excluded this match from scoring. It adds no fantasy points.";

// Fantasy pts cell for one match-history row: the points plus a "Partial stats"
// marker for unparsed matches, or a dash plus "Not scored" for excluded ones.
function _matchPointsCellHtml(m) {
  if (m.excluded_from_scoring) {
    return `— <span class="badge common" title="${_escHtml(_NOT_SCORED_TOOLTIP)}">Not scored</span>`;
  }
  const pts = _escHtml(Number(m.fantasy_points).toFixed(1));
  if (m.parse_status === "unparsed" || m.parse_status === "unparseable") {
    return `${pts} <span class="badge common" title="${_escHtml(_PARTIAL_STATS_TOOLTIP)}">Partial stats</span>`;
  }
  return pts;
}

function renderPlayerProfile(profile) {
  const facts = profile && profile.facts;
  if (!facts) return;
  const el = document.getElementById("playerProfile");
  if (!el) return;

  const statGrid = `
    <div class="player-modal-stat-grid" style="margin-top:8px;">
      <div class="player-modal-stat"><div class="val">${_escHtml(facts.kanaliiga_seasons)}</div><div class="lbl">Seasons</div></div>
      <div class="player-modal-stat"><div class="val">${_escHtml(Number(facts.avg_kills).toFixed(1))}</div><div class="lbl">Avg K</div></div>
      <div class="player-modal-stat"><div class="val">${_escHtml(Number(facts.avg_deaths).toFixed(1))}</div><div class="lbl">Avg D</div></div>
      <div class="player-modal-stat"><div class="val">${_escHtml(Number(facts.avg_assists).toFixed(1))}</div><div class="lbl">Avg A</div></div>
      <div class="player-modal-stat"><div class="val">${_escHtml(Math.round(facts.avg_gpm))}</div><div class="lbl">Avg GPM</div></div>
      <div class="player-modal-stat"><div class="val">${_escHtml(Number(facts.avg_wards).toFixed(1))}</div><div class="lbl">Avg wards</div></div>
      <div class="player-modal-stat"><div class="val">${_escHtml(facts.role_tendency)}</div><div class="lbl">Role</div></div>
    </div>`;

  function heroLine(h) {
    return h.win_rate !== undefined
      ? `<span style="color:#aaa">${_escHtml(h.hero_name)}</span> <span style="color:#555;font-size:0.78rem;">(${_escHtml(h.games)}g, ${_escHtml(Math.round(h.win_rate*100))}%wr)</span>`
      : `<span style="color:#aaa">${_escHtml(h.hero_name)}</span> <span style="color:#555;font-size:0.78rem;">(${_escHtml(h.games)}g)</span>`;
  }
  function heroSection(label, heroes, limit) {
    const items = (heroes || []).slice(0, limit).map(heroLine).join(", ") || "—";
    return `<div style="margin-bottom:6px;"><span class="player-bio-eyebrow">${label}</span><br><span style="font-size:var(--fs-sm);">${items}</span></div>`;
  }

  const heroes = `<div style="margin-top:14px;">
    ${heroSection("Career heroes", facts.top_heroes_alltime, 5)}
    ${heroSection("Tournament heroes", facts.tournament_heroes, 5)}
    ${heroSection("Recent pub heroes", facts.recent_pub_heroes, 5)}
  </div>`;

  const bioSection = profile.bio_text
    ? `<div style="margin-top:14px;padding:10px 14px;background:#0f1a0f;border:1px solid #1a3a1a;border-radius:6px;font-size:0.85rem;color:#aaa;line-height:1.6;white-space:pre-wrap;">${_escHtml(profile.bio_text)}</div>`
    : "";

  el.innerHTML = statGrid + heroes + bioSection;
  el.style.display = "block";
}

function closePlayerModal() {
  document.getElementById("playerModal").classList.add("hidden");
}

async function openTeamModal(teamId) {
  const modal = document.getElementById("teamModal");
  modal.classList.remove("hidden");
  document.getElementById("teamModalName").textContent = "Loading...";
  document.getElementById("teamModalMeta").textContent = "";
  document.getElementById("teamModalPlayers").innerHTML = "";
  document.getElementById("teamModalStatus").textContent = "";

  try {
    const res = await fetch(`${API}/teams/${teamId}`);
    const t = await res.json();
    if (!res.ok) {
      document.getElementById("teamModalName").textContent = "";
      setStatus("teamModalStatus", t.detail || "Failed to load", false);
      return;
    }

    document.getElementById("teamModalName").textContent = t.name;
    document.getElementById("teamModalMeta").textContent = `${t.matches} matches`;

    if (!t.players.length) {
      document.getElementById("teamModalPlayers").innerHTML =
        "<tr><td colspan='4' style='color:#444'>No players found</td></tr>";
    } else {
      document.getElementById("teamModalPlayers").innerHTML = t.players.map(p => `
        <tr>
          <td><img src="${_escHtml(_safeUrl(p.avatar_url))}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" /><span class="entity-link" tabindex="0" role="button" onclick="closeTeamModal();openPlayerModal(${p.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();closeTeamModal();openPlayerModal(${p.id})}">${_escHtml(p.name)}</span></td>
          <td>${p.matches}</td>
          <td>${Number(p.avg_points).toFixed(1)}</td>
          <td>${Number(p.total_points).toFixed(1)}</td>
        </tr>`).join("");
    }
  } catch (e) {
    setStatus("teamModalStatus", e.message, false);
  }
}

function closeTeamModal() {
  document.getElementById("teamModal").classList.add("hidden");
}

function _formatGameDuration(seconds) {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function _gameHeroIconsHtml(heroUrls) {
  return (heroUrls || []).map(url => url
    ? `<img class="hero-icon" src="${_escHtml(_safeUrl(url))}" title="" onerror="this.style.display='none'" />`
    : `<span class="hero-icon hero-icon-placeholder"></span>`
  ).join("");
}

// ---------------------------------------------------------------------------
// Schedule tab (issue #156): Right now strip, week strip, hide mode.
// ---------------------------------------------------------------------------

// Kept across quiet refreshes (issue #159), so a refresh keeps the player's place.
let _schedWeekKey = null;      // selected week; null follows the current week
let _schedDivision = "all";
const _schedOpenGames = new Set();
let _schedWeeks = [];
let _schedHiddenKeysByWeek = [];
let _schedRevealedKeysByWeek = []; // revealed on this tab (not via the Weekly Report)
let _schedRerender = null;     // re-renders the last /schedule response
let _schedHideMem = null;      // hide mode, read from storage on first use
let _schedRevealedMem = null;  // Set of revealed series keys, read on first use
// Markup carries a short hash of each series key, not the key itself: a key made
// of match ids would give away a hidden series' game count in view-source.
let _schedKeyById = new Map();

const _SCHED_REVEALED_MAX = 500;
// A live game marks a series only when it started within this window of the
// series' time, so an earlier meeting of the same two teams is not marked live.
const _SCHED_LIVE_WINDOW = 12 * 3600;

// Hide mode is on unless the player turned it off ("0"); blocked storage counts as on.
function _schedHideOn() {
  if (_schedHideMem === null) {
    try {
      _schedHideMem = localStorage.getItem("kc_schedule_hide") !== "0";
    } catch (_) {
      _schedHideMem = true;
    }
  }
  return _schedHideMem;
}

function toggleScheduleHide() {
  _schedHideMem = !_schedHideOn();
  try {
    localStorage.setItem("kc_schedule_hide", _schedHideMem ? "1" : "0");
  } catch (_) {}
  if (_schedRerender) _schedRerender();
}

function _schedRevealedKeys() {
  if (_schedRevealedMem === null) {
    _schedRevealedMem = new Set();
    try {
      const stored = JSON.parse(localStorage.getItem("kc_schedule_revealed") || "[]");
      if (Array.isArray(stored)) stored.forEach(k => _schedRevealedMem.add(String(k)));
    } catch (_) {}
  }
  return _schedRevealedMem;
}

// Adds keys as the most recent reveals; only the newest 500 are kept.
function _schedReveal(keys) {
  const set = _schedRevealedKeys();
  for (const k of keys) {
    set.delete(String(k));
    set.add(String(k));
  }
  while (set.size > _SCHED_REVEALED_MAX) set.delete(set.values().next().value);
  try {
    localStorage.setItem("kc_schedule_revealed", JSON.stringify([...set]));
  } catch (_) {}
  if (_schedRerender) _schedRerender();
}

function _schedKeyId(key) {
  let h = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16);
}

// Undo for reveals made on this tab: the keys go back to hidden.
function _schedUnreveal(keys) {
  const set = _schedRevealedKeys();
  for (const k of keys) set.delete(String(k));
  try {
    localStorage.setItem("kc_schedule_revealed", JSON.stringify([...set]));
  } catch (_) {}
  if (_schedRerender) _schedRerender();
}

function revealScheduleSeries(id) {
  const key = _schedKeyById.get(String(id));
  if (key) _schedReveal([key]);
}

function revealScheduleWeek(i) {
  _schedReveal(_schedHiddenKeysByWeek[i] || []);
}

function hideScheduleWeekAgain(i) {
  _schedUnreveal(_schedRevealedKeysByWeek[i] || []);
}

// A redraw replaces the buttons, so focus would fall back to the page. Controls
// carry data-focus; after a redraw the same control (or its successor) gets focus.
function _schedFocusTarget() {
  try {
    const el = document.activeElement;
    if (el && el.closest && el.closest("#tab-schedule") && el.getAttribute("data-focus")) return el;
  } catch (_) {}
  return null;
}

function _schedRestoreFocus(prev) {
  try {
    if (!prev || prev.isConnected) return;
    const key = prev.getAttribute("data-focus");
    const id = key.slice(key.indexOf("-") + 1);
    const tries = [key];
    if (key.startsWith("reveal-")) tries.push(`games-${id}`, "latest-games");
    if (key.startsWith("latest-")) tries.push("latest-games", "latest-reveal");
    if (key === "reveal-week") tries.push("hide-week");
    if (key === "hide-week") tries.push("reveal-week");
    tries.push("week-title");
    for (const k of tries) {
      const el = [...document.querySelectorAll(`#tab-schedule [data-focus="${k}"]`)][0];
      if (el) { el.focus({ preventScroll: true }); return; }
    }
  } catch (_) {}
}

function selectScheduleWeek(i) {
  const w = _schedWeeks[i];
  if (!w) return;
  _schedWeekKey = w.key;
  if (_schedRerender) _schedRerender();
}

function scheduleThisWeek() {
  _schedWeekKey = null;
  if (_schedRerender) _schedRerender();
}

function setScheduleDivision(div) {
  _schedDivision = div === "div1" || div === "div2" ? div : "all";
  if (_schedRerender) _schedRerender();
}

function toggleScheduleGames(id) {
  const key = _schedKeyById.get(String(id));
  if (!key) return;
  if (_schedOpenGames.has(key)) _schedOpenGames.delete(key);
  else _schedOpenGames.add(key);
  if (_schedRerender) _schedRerender();
}

// Latest result card: open the series' week with its games unfolded.
function showScheduleLatestGames(id, i) {
  const key = _schedKeyById.get(String(id));
  if (!key) return;
  _schedOpenGames.add(key);
  _schedDivision = "all";
  selectScheduleWeek(i);
  const row = [...document.querySelectorAll("#scheduleContent [data-series-key]")]
    .find(el => el.dataset.seriesKey === String(id));
  let reduce = false;
  try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_) {}
  if (row) row.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  const btn = [...document.querySelectorAll(`#tab-schedule [data-focus="games-${id}"]`)][0];
  if (btn) btn.focus({ preventScroll: true });
}

// Weeks the logged-in player revealed in the Weekly Report. Read only, never
// written; logged out or on any failure it is an empty set.
async function _schedFetchReportReveals() {
  if (!activeUsername) return new Set();
  try {
    const res = await fetch(`${API}/weekly-summary`);
    if (!res.ok) return new Set();
    const data = await res.json();
    return new Set((data.weeks || []).filter(w => w.revealed).map(w => w.week_id));
  } catch (_) {
    return new Set();
  }
}

// Actual start once played, planned time before that (unix seconds).
function seriesTime(s) {
  const r = s && s.series_result;
  if (r && r.start_time) return r.start_time;
  const t = Date.parse((s && s.datetime_iso) || "");
  return Number.isNaN(t) ? null : Math.floor(t / 1000);
}

// Stable across refreshes: the series' match ids, or team1|team2|datetime_iso.
function seriesKey(s) {
  const ids = (s.series_result && s.series_result.match_ids) || [];
  if (ids.length) return ids.map(Number).sort((a, b) => a - b).join(",");
  return [s.team1 || "", s.team2 || "", s.datetime_iso || ""].join("|");
}

function _schedPad2(n) {
  return String(n).padStart(2, "0");
}

function _schedClock(ts) {
  const d = new Date(ts * 1000);
  return `${_schedPad2(d.getHours())}:${_schedPad2(d.getMinutes())}`;
}

function _schedDayMonth(ts) {
  const d = new Date(ts * 1000);
  return `${d.getDate()}.${d.getMonth() + 1}.`;
}

const _SCHED_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// English weekday, Finnish day-month order: "Mon 5.10." (with year: "Mon 5.10.2026").
function _schedDayLabel(ts, withYear) {
  const d = new Date(ts * 1000);
  return `${_SCHED_WEEKDAYS[d.getDay()]} ${_schedDayMonth(ts)}${withYear ? d.getFullYear() : ""}`;
}

// Monday-start calendar weeks covering the series' own dates (no fantasy weeks defined).
function calendarWeeks(series) {
  const times = series.map(seriesTime).filter(t => t != null);
  if (!times.length) return [];
  const monday = ts => {
    const d = new Date(ts * 1000);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d;
  };
  const first = monday(Math.min(...times));
  const last = monday(Math.max(...times));
  const weeks = [];
  for (const d = new Date(first); d <= last; d.setDate(d.getDate() + 7)) {
    const start = Math.floor(d.getTime() / 1000);
    const next = new Date(d);
    next.setDate(next.getDate() + 7);
    const sunday = new Date(next);
    sunday.setDate(sunday.getDate() - 1);
    weeks.push({
      key: `cal:${start}`,
      week_id: null,
      label: `${_schedDayMonth(start)}–${_schedDayMonth(Math.floor(sunday.getTime() / 1000))}`,
      start_time: start,
      end_time: Math.floor(next.getTime() / 1000),
    });
  }
  return weeks;
}

// Index of the week a series belongs to: the week containing its time, else the
// last week starting before it, else the first week. -1 only when there are no weeks.
function assignWeek(s, weeks) {
  if (!weeks.length) return -1;
  const t = seriesTime(s);
  if (t == null) return 0;
  let earlier = -1;
  for (let i = 0; i < weeks.length; i++) {
    const w = weeks[i];
    if (w.start_time <= t && t < w.end_time) return i;
    if (w.start_time <= t) earlier = i;
  }
  return earlier >= 0 ? earlier : 0;
}

// The week containing now; between weeks the next to start; after the season the last.
function currentWeekIndex(weeks, now) {
  if (!weeks.length) return -1;
  const containing = weeks.findIndex(w => w.start_time <= now && now < w.end_time);
  if (containing >= 0) return containing;
  const next = weeks.findIndex(w => w.start_time > now);
  return next >= 0 ? next : weeks.length - 1;
}

function _schedLiveEntry(s, live) {
  if (!s.team1_id || !s.team2_id || !Array.isArray(live)) return null;
  const a = Math.min(s.team1_id, s.team2_id);
  const b = Math.max(s.team1_id, s.team2_id);
  const t = seriesTime(s);
  return live.find(l => Array.isArray(l.team_ids) && l.team_ids[0] === a && l.team_ids[1] === b
    && (t == null || l.started_at == null || Math.abs(t - l.started_at) <= _SCHED_LIVE_WINDOW)) || null;
}

function _schedResultHidden(s, ctx) {
  return !!ctx.hide
    && !ctx.revealed.has(seriesKey(s))
    && !(ctx.weekId != null && ctx.reportWeeks.has(ctx.weekId));
}

// live, then upcoming, then noresult (past date, no games found), then hidden
// (hide mode on, not revealed here or in the Weekly Report), else shown.
// Live, upcoming and noresult never depend on hide mode.
function rowState(s, ctx) {
  if (_schedLiveEntry(s, ctx.live)) return "live";
  if (s.match_status !== "past") return "upcoming";
  if (!s.series_result) return "noresult";
  if (_schedResultHidden(s, ctx)) return "hidden";
  return "shown";
}

// Relative countdown, computed at render time ("in 1 h 20 min", "in 2 days").
function _schedCountdown(t, now) {
  const secs = t - now;
  if (secs < 60) return "starting now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `in ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return mins % 60 ? `in ${hours} h ${mins % 60} min` : `in ${hours} h`;
  const days = Math.max(1, Math.round(secs / 86400));
  return `in ${days} ${days === 1 ? "day" : "days"}`;
}

// Channel name from a stream URL, shown before the watch button: twitch.tv/kanaliiga
// → "kanaliiga", youtube.com/@kanaliiga → "kanaliiga", anything else → its host.
function _schedStreamerName(url) {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^(www|m)\./, "");
    const seg = u.pathname.split("/").filter(Boolean)[0] || "";
    if (/(^|\.)(twitch\.tv|kick\.com)$/.test(host) && seg && seg !== "videos") return seg;
    if (/(^|\.)youtube\.com$/.test(host) && seg.startsWith("@")) return seg.slice(1);
    return host;
  } catch (_) {
    return "";
  }
}

// How far a week is from the current one, in plain words: "This week", "Next week",
// "In 2 weeks". Weeks start on Monday.
function _schedWeeksAway(ts, now) {
  const monday = t => {
    const d = new Date(t * 1000);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime();
  };
  const n = Math.round((monday(ts) - monday(now)) / (7 * 86400000));
  if (n <= 0) return "This week";
  if (n === 1) return "Next week";
  return `In ${n} weeks`;
}

function _schedWeekShort(w) {
  const m = /^week\s*(\d+)$/i.exec(String(w.label || "").trim());
  return m ? `W${m[1]}` : String(w.label || "");
}

async function loadSchedule() {
  const content = document.getElementById("scheduleContent");
  const staleEl = document.getElementById("scheduleStale");
  const nowEl = document.getElementById("scheduleNow");
  const weeksEl = document.getElementById("scheduleWeeks");
  // Issue #159: the placeholder shows only on the very first load; a refresh keeps
  // the fixtures on screen until the new ones replace them, and a failed refresh
  // keeps them too (the error goes to the status line).
  const firstLoad = content.innerHTML.trim() === "";
  if (firstLoad) renderIfChanged(content, "<span class='schedule-empty'>Loading...</span>");
  const clearStrips = () => {
    _schedRerender = null;
    renderIfChanged(weeksEl, "");
    renderIfChanged(nowEl, "");
    nowEl.style.display = "none";
  };
  try {
    // Issue #156: weeks revealed in the Weekly Report, fetched once per load.
    const reportWeeksReq = _schedFetchReportReveals();
    const res = await fetch(`${API}/schedule`);
    const data = await res.json();
    if (!res.ok) { setStatus("scheduleStatus", data.detail || "Failed to load", false); if (firstLoad) renderIfChanged(content, ""); return; }
    const reportWeeks = await reportWeeksReq;

    if (data.stale) {
      staleEl.textContent = `Cached data from ${data.cached_at ? new Date(data.cached_at).toLocaleString() : "unknown"}`;
      staleEl.style.display = "";
    } else {
      staleEl.style.display = "none";
    }
    if (data.error && !data.weeks?.length && !data.extra_results?.length) {
      clearStrips();
      renderIfChanged(content, `<span class="schedule-empty">${_escHtml(data.error)}</span>`);
      setStatus("scheduleStatus", "");
      return;
    }
    if (!data.weeks?.length && !data.extra_results?.length) {
      clearStrips();
      renderIfChanged(content, "<span class='schedule-empty'>No schedule data available.</span>");
      setStatus("scheduleStatus", "");
      return;
    }

    const allSeries = [];
    for (const week of (data.weeks || [])) {
      for (const s of (week.div1 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div1", feedWeek: week.label});
      for (const s of (week.div2 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div2", feedWeek: week.label});
    }
    for (const s of (data.extra_results || [])) allSeries.push(s);

    // Fantasy weeks when defined, otherwise Monday-start calendar weeks.
    const weeks = (data.fantasy_weeks || []).length
      ? data.fantasy_weeks.map(w => ({...w, key: `fw:${w.week_id}`}))
      : calendarWeeks(allSeries);
    const byWeek = weeks.map(() => []);
    const weekOf = new Map();
    for (const s of allSeries) {
      const i = assignWeek(s, weeks);
      if (i < 0) continue;
      byWeek[i].push(s);
      weekOf.set(s, i);
    }
    const live = data.live || [];

    const domKey = key => {
      const id = _schedKeyId(key);
      _schedKeyById.set(id, key);
      return _escHtml(id);
    };
    const teamHtml = (id, name) => id ? teamLink(id, name) : (_escHtml(name) || "—");
    const divText = s => s.division === "div1" ? "Div 1" : s.division === "div2" ? "Div 2" : "";
    const divBadge = s => s.division === "div1"
      ? `<span class="badge badge-division div1">Div 1</span>`
      : s.division === "div2"
      ? `<span class="badge badge-division div2">Div 2</span>`
      : `<span class="badge-division"></span>`;
    // Opens in a new tab: an arrow icon (the ↗ glyph renders tiny in the display face).
    const extIcon = `<svg class="ext-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg>`;
    // The streamer (the feed's label, else the channel from the URL) goes before the button.
    const streamerHtml = s => {
      const name = s.stream_label || _schedStreamerName(s.stream_url);
      return name ? `<span class="stream-name" title="${_escHtml(name)}">${_escHtml(name)}</span>` : "";
    };
    const streamLink = (s, fallback, cls = "stream-link") => s.stream_url
      ? `${streamerHtml(s)}<a class="${cls}" href="${_escHtml(_safeUrl(s.stream_url))}" target="_blank" rel="noopener">${_escHtml(fallback)}${extIcon}</a>`
      : "";
    const streamLabel = s => s.stream_label ? `<span class="series-stream-label">${_escHtml(s.stream_label)}</span>` : "";
    // Upcoming fixtures always show who streams it and a Watch button. With no stream
    // URL yet the button is greyed out (not a link) and the streamer reads "Caster TBD"
    // unless the feed named one.
    const upcomingWatch = (s, fallback, cls) => {
      if (s.stream_url) return streamLink(s, fallback, cls);
      const name = s.stream_label || "Caster TBD";
      const tbdCls = s.stream_label ? "" : " tbd";
      return `<span class="stream-name${tbdCls}">${_escHtml(name)}</span>`
        + `<span class="${cls} is-disabled" aria-disabled="true" title="No stream link yet">${_escHtml(fallback)}${extIcon}</span>`;
    };
    const winClasses = r => [
      r.team1_wins > r.team2_wins ? " win" : r.team1_wins < r.team2_wins ? " loss" : "",
      r.team2_wins > r.team1_wins ? " win" : r.team2_wins < r.team1_wins ? " loss" : "",
    ];
    const scoreHtml = r => `<span class="series-score">${_escHtml(r.team1_wins)}–${_escHtml(r.team2_wins)}</span>`;
    // Every row ends in the same two slots (link, button) so links and buttons line up.
    const linksHtml = (link, btn) =>
      `<span class="series-links"><span class="series-link-slot">${link}</span><span class="series-btn-slot">${btn}</span></span>`;

    const timeCell = (s, state) => {
      if (state === "upcoming" || state === "live" || state === "noresult") {
        if (s.scheduled === false) return `<span class="series-time tbd">Time TBD</span>`;
        if (s.time) return `<span class="series-time">${_escHtml(s.time)}</span>`;
      }
      const t = seriesTime(s);
      return t != null ? `<span class="series-time">${_escHtml(_schedClock(t))}</span>` : "";
    };

    const gameRowsHtml = games => `<div class="series-games">${games.map((g, i) => `
        <div class="game-row">
          <span class="game-row-num">G${i + 1}${g.excluded_from_scoring ? ` <span class="badge common" title="${_escHtml(_NOT_SCORED_TOOLTIP)}">Not scored</span>` : ""}</span>
          <span class="game-row-heroes">${_gameHeroIconsHtml(g.team1_heroes)}</span>
          <span class="game-row-score">${_escHtml(g.team1_kills)}–${_escHtml(g.team2_kills)}</span>
          <span class="game-row-heroes right">${_gameHeroIconsHtml(g.team2_heroes)}</span>
          <span class="game-row-meta">
            ${g.mvp_player_id ? `<span class="game-row-mvp-star" aria-label="MVP">★</span> ${playerLink(g.mvp_player_id, g.mvp_player_name)}` : ""}
            <span class="game-row-duration">${_formatGameDuration(g.duration)}</span>
            <a class="stream-link" href="https://www.opendota.com/matches/${Number(g.match_id)}" target="_blank" rel="noopener noreferrer" aria-label="Game ${i + 1} on OpenDota">↗</a>
          </span>
        </div>`).join("")}</div>`;

    // Hidden rows output no score, game count or game markup at all, so nothing
    // leaks to view-source or screen readers. Team names are plain text here: the
    // team popup lists results.
    const hiddenRow = (s, key, meta) => {
      const id = domKey(key);
      return `<div class="series-row result-hidden" data-series-key="${id}">
        ${meta}
        <span class="series-team">${(_escHtml(s.team1) || "—")}</span>
        <span class="series-played">Played</span>
        <span class="series-team right">${(_escHtml(s.team2) || "—")}</span>
        ${linksHtml("", `<button type="button" class="secondary series-btn" data-key="${id}" data-focus="reveal-${id}" onclick="revealScheduleSeries(this.dataset.key)">Reveal</button>`)}
      </div>`;
    };

    const seriesRow = (s, state, ctx) => {
      const key = seriesKey(s);
      const r = s.series_result;
      const meta = `<span class="series-meta">${timeCell(s, state)}${divBadge(s)}</span>`;
      if (state === "hidden") return hiddenRow(s, key, meta);
      const t1 = teamHtml(s.team1_id, s.team1);
      const t2 = teamHtml(s.team2_id, s.team2);
      if (state === "shown") {
        const [c1, c2] = winClasses(r);
        const games = r.games || [];
        const open = _schedOpenGames.has(key);
        const id = domKey(key);
        const gamesBtn = games.length
          ? `<button type="button" class="secondary series-btn" aria-expanded="${open}" data-key="${id}" data-focus="games-${id}" onclick="toggleScheduleGames(this.dataset.key)">${games.length} ${games.length === 1 ? "game" : "games"}</button>`
          : "";
        return `<div class="series-row past" data-series-key="${id}">
        ${meta}
        <span class="series-team${c1}">${t1}</span>
        ${scoreHtml(r)}
        <span class="series-team right${c2}">${t2}</span>
        ${linksHtml(streamLink(s, "Stream"), gamesBtn)}
      </div>${games.length && open ? gameRowsHtml(games) : ""}`;
      }
      if (state === "live") {
        // A partly played live series follows hide mode like any other result.
        const partHidden = r && _schedResultHidden(s, ctx);
        const partial = r && !partHidden ? scoreHtml(r) : "";
        return `<div class="series-row live" data-series-key="${domKey(key)}">
        ${meta}
        <span class="series-team">${partHidden ? (_escHtml(s.team1) || "—") : t1}</span>
        <span class="series-live"><span class="live-tag">Live</span>${partial}</span>
        <span class="series-team right">${partHidden ? (_escHtml(s.team2) || "—") : t2}</span>
        ${linksHtml(streamLink(s, "Watch live") || streamLabel(s), "")}
      </div>`;
      }
      if (state === "noresult") {
        // Past its date but no games were found for it: not upcoming, no score.
        return `<div class="series-row past no-games" data-series-key="${domKey(key)}">
        ${meta}
        <span class="series-team">${t1}</span>
        <span class="series-played">No result</span>
        <span class="series-team right">${t2}</span>
        ${linksHtml(streamLink(s, "Stream") || streamLabel(s), "")}
      </div>`;
      }
      return `<div class="series-row" data-series-key="${domKey(key)}">
        ${meta}
        <span class="series-team">${t1}</span>
        <span class="series-score no-result">vs</span>
        <span class="series-team right">${t2}</span>
        ${linksHtml(upcomingWatch(s, "Watch", "stream-link"), "")}
      </div>`;
    };

    function _seriesDateLabel(s) {
      const t = seriesTime(s);
      if (t == null) return "Unknown date";
      return _schedDayLabel(t, true);
    }

    function _groupByDate(series) {
      const groups = [], index = {};
      for (const s of series) {
        const key = _seriesDateLabel(s);
        if (!index[key]) { index[key] = []; groups.push({key, items: index[key]}); }
        index[key].push(s);
      }
      return groups;
    }

    const nowLineHtml = now => {
      const label = `${_SCHED_WEEKDAYS[new Date(now * 1000).getDay()]} ${_schedClock(now)}`;
      return `<div class="schedule-now-line" role="separator" aria-label="Now"><span>Now · ${_escHtml(label)}</span></div>`;
    };

    // Teams centred on the middle cell, like the rows; meta left and action right in the foot.
    const nowCard = (kind, eyebrow, t1, mid, t2, meta, action) => `<div class="now-card ${kind}">
        <div class="now-card-eyebrow">${kind === "live" ? `<span class="live-dot" aria-hidden="true"></span>` : ""}${eyebrow}</div>
        <div class="now-card-teams"><span class="now-team">${t1}</span>${mid}<span class="now-team right">${t2}</span></div>
        <div class="now-card-foot"><span class="now-card-meta">${meta}</span>${action}</div>
      </div>`;
    const vsHtml = `<span class="now-vs">vs</span>`;

    const nowStripHtml = (now, stateOf) => {
      const cards = [];
      const liveSeries = allSeries.find(s => stateOf.get(s) === "live");
      if (liveSeries) {
        const s = liveSeries;
        const entry = _schedLiveEntry(s, live);
        const started = (s.series_result && s.series_result.start_time) || (entry && entry.started_at);
        const meta = [divText(s), started ? `Started ${_schedClock(started)}` : ""].filter(Boolean).join(" · ");
        const plain = !!s.series_result;
        cards.push(nowCard("live", "Live now",
          plain ? (_escHtml(s.team1) || "—") : teamHtml(s.team1_id, s.team1), vsHtml,
          plain ? (_escHtml(s.team2) || "—") : teamHtml(s.team2_id, s.team2),
          _escHtml(meta),
          s.stream_url ? `<span class="now-card-watch">${streamLink(s, "Watch live", "now-card-link")}</span>` : ""));
      }
      // Next up: the next three timed series as compact rows; the countdown is to the first.
      const nextList = allSeries
        .filter(s => stateOf.get(s) === "upcoming" && s.scheduled !== false && seriesTime(s) > now)
        .sort((a, b) => seriesTime(a) - seriesTime(b))
        .slice(0, 3);
      // Fewer than three timed series: fill with one summary row per coming feed week
      // ("Week 5") whose fixtures have no time yet; "View week" opens where they are listed.
      const untimed = new Map();
      for (const s of allSeries) {
        if (stateOf.get(s) !== "upcoming" || s.scheduled !== false || !weekOf.has(s)) continue;
        const label = s.feedWeek || _schedWeekShort(weeks[weekOf.get(s)]);
        const g = untimed.get(label) || { label, n: 0, t: seriesTime(s), i: weekOf.get(s) };
        g.n += 1;
        g.t = Math.min(g.t, seriesTime(s));
        untimed.set(label, g);
      }
      const tbdWeeks = [...untimed.values()].sort((a, b) => a.t - b.t).slice(0, 3 - nextList.length);
      if (nextList.length || tbdWeeks.length) {
        const t = nextList.length ? seriesTime(nextList[0]) : null;
        const tbdRows = tbdWeeks.map(({ label, n, t: wt, i }) => `<div class="next-row next-tbd">
          <span class="next-when"><span class="next-time">${_escHtml(label)}</span><span class="next-div">${_escHtml(_schedDayLabel(wt, false))}</span></span>
          <span class="next-summary"><strong>${_escHtml(_schedWeeksAway(wt, now))}</strong> · ${n} ${n === 1 ? "match" : "matches"}, times to be announced</span>
          <span class="next-watch"><button type="button" class="secondary now-card-btn next-view" data-focus="next-week-${_escHtml(label)}" onclick="selectScheduleWeek(${i})">View week</button></span>
        </div>`).join("");
        const rows = nextList.map(s => {
          const st = seriesTime(s);
          const t1 = teamHtml(s.team1_id, s.team1);
          const t2 = teamHtml(s.team2_id, s.team2);
          return `<div class="next-row">
          <span class="next-when"><span class="next-time">${_escHtml(_SCHED_WEEKDAYS[new Date(st * 1000).getDay()])} ${_escHtml(_schedClock(st))}</span><span class="next-div">${_escHtml(divText(s))}</span></span>
          <span class="next-teams"><span class="now-team">${t1}</span><span class="now-vs">vs</span><span class="now-team right">${t2}</span></span>
          <span class="next-watch">${upcomingWatch(s, "Watch", "now-card-link")}</span>
        </div>`;
        }).join("");
        const label = "Next up";
        cards.push(`<div class="now-card next">
        <div class="now-card-eyebrow">${label}${t != null ? `<span class="now-countdown">${_escHtml(_schedCountdown(t, now))}</span>` : ""}</div>
        <div class="next-list">${rows}${tbdRows}</div>
      </div>`);
      }
      const latest = allSeries
        .filter(s => stateOf.get(s) === "hidden" || stateOf.get(s) === "shown")
        .sort((a, b) => seriesTime(b) - seriesTime(a))[0];
      if (latest) {
        const s = latest;
        const key = seriesKey(s);
        const id = domKey(key);
        const meta = [divText(s), _schedDayLabel(seriesTime(s), false)].filter(Boolean).join(" · ");
        if (stateOf.get(s) === "hidden") {
          cards.push(nowCard("latest", "Latest result",
            (_escHtml(s.team1) || "—"), vsHtml, (_escHtml(s.team2) || "—"),
            `${_escHtml(meta)} · Result hidden`,
            `<button type="button" class="secondary now-card-btn" data-key="${id}" data-focus="latest-reveal" onclick="revealScheduleSeries(this.dataset.key)">Reveal</button>`));
        } else {
          const r = s.series_result;
          const [c1, c2] = winClasses(r);
          const games = r.games || [];
          const t1 = teamHtml(s.team1_id, s.team1);
          const t2 = teamHtml(s.team2_id, s.team2);
          cards.push(nowCard("latest", "Latest result",
            `<span class="${c1.trim()}">${t1}</span>`, scoreHtml(r),
            `<span class="${c2.trim()}">${t2}</span>`,
            _escHtml(meta),
            games.length ? `<button type="button" class="secondary now-card-btn" data-key="${id}" data-focus="latest-games" onclick="showScheduleLatestGames(this.dataset.key, ${weekOf.get(s)})">Games</button>` : ""));
        }
      }
      return cards.join("");
    };

    const weekStripHtml = (sel, current) => {
      if (!weeks.length) return "";
      const chips = weeks.map((w, i) => {
        const cls = i === current ? "current" : i < current ? "played" : "upcoming";
        const date = w.week_id != null ? _schedDayMonth(w.start_time) : "";
        return `<button type="button" class="schedule-week-chip ${cls}${i === sel ? " selected" : ""}"${i === current ? ` aria-current="date"` : ""} aria-pressed="${i === sel}" data-focus="week-${i}" onclick="selectScheduleWeek(${i})">
          <span class="schedule-week-chip-name">${_escHtml(_schedWeekShort(w))}</span>
          ${date ? `<span class="schedule-week-chip-date">${_escHtml(date)}</span>` : ""}
          ${i === current ? `<span class="schedule-week-chip-tag">This week</span>` : ""}
          ${_schedHiddenKeysByWeek[i].length ? `<span class="schedule-week-chip-marker" title="Has hidden results"><span class="visually-hidden">Has hidden results</span></span>` : ""}
        </button>`;
      }).join("");
      return `<button type="button" class="schedule-week-arrow" aria-label="Previous week" data-focus="week-prev" onclick="selectScheduleWeek(${sel - 1})"${sel <= 0 ? " disabled" : ""}>‹</button>
        <div class="schedule-week-chips">${chips}</div>
        <button type="button" class="schedule-week-arrow" aria-label="Next week" data-focus="week-next" onclick="selectScheduleWeek(${sel + 1})"${sel >= weeks.length - 1 ? " disabled" : ""}>›</button>
        <button type="button" class="secondary schedule-this-week" data-focus="this-week" onclick="scheduleThisWeek()"${sel === current ? " disabled" : ""}>This week</button>`;
    };

    const weekPanelHtml = (sel, current, now, stateOf, ctxOf) => {
      const w = weeks[sel];
      if (!w) return "<span class='schedule-empty'>No dated matches found.</span>";
      const list = byWeek[sel];
      const ctx = ctxOf(sel);
      const hidden = _schedHiddenKeysByWeek[sel];
      const revealedHere = _schedRevealedKeysByWeek[sel];
      const reportRevealed = ctx.hide && w.week_id != null && reportWeeks.has(w.week_id)
        && list.some(s => s.match_status === "past" && s.series_result);
      const range = `${_schedDayMonth(w.start_time)}–${_schedDayMonth(w.end_time - 1)}`;
      const note = reportRevealed
        ? `<span class="schedule-week-note">Revealed in your Weekly Report</span>`
        : (hidden.length
          ? `<button type="button" class="secondary series-btn" data-focus="reveal-week" onclick="revealScheduleWeek(${sel})">Reveal week</button>`
          : "")
        + (revealedHere.length
          ? `<button type="button" class="secondary series-btn" data-focus="hide-week" onclick="hideScheduleWeekAgain(${sel})">Hide week again</button>`
          : "");
      const divChips = [["all", "All"], ["div1", "Div 1"], ["div2", "Div 2"]].map(([v, label]) =>
        `<button type="button" class="schedule-div-chip${_schedDivision === v ? " active" : ""}" aria-pressed="${_schedDivision === v}" data-focus="div-${v}" onclick="setScheduleDivision('${v}')">${label}</button>`
      ).join("");
      const header = `<div class="schedule-week-hd">
        <div class="schedule-week-title"><h3 tabindex="-1" data-focus="week-title">${_escHtml(w.label)}</h3>${w.week_id != null ? `<span class="schedule-week-range">${_escHtml(range)}</span>` : ""}</div>
        <div class="schedule-week-tools">${note}<div class="schedule-div-filter" role="group" aria-label="Division">${divChips}</div></div>
      </div>`;

      const shown = list.filter(s => _schedDivision === "all" || s.division === _schedDivision);
      if (!list.length) return header + "<p class='schedule-empty'>No matches this week.</p>";
      if (!shown.length) return header + "<p class='schedule-empty'>No matches for this division this week.</p>";

      // "Time TBD" fixtures have no real time; they close the week in their own group.
      const isTbd = s => s.scheduled === false && !s.series_result;
      const dated = shown.filter(s => !isTbd(s)).sort((a, b) => seriesTime(a) - seriesTime(b));
      const tbd = shown.filter(isTbd);
      let nowPending = sel === current;
      let html = header;
      for (const g of _groupByDate(dated)) {
        let group = "";
        g.items.forEach((s, idx) => {
          if (nowPending && seriesTime(s) > now) {
            if (idx === 0) html += nowLineHtml(now);
            else group += nowLineHtml(now);
            nowPending = false;
          }
          group += seriesRow(s, stateOf.get(s), ctx);
        });
        html += `<div class="schedule-day"><div class="schedule-date-hd">${_escHtml(g.key)}</div>${group}</div>`;
      }
      if (nowPending) html += nowLineHtml(now);
      if (tbd.length) {
        html += `<div class="schedule-day"><div class="schedule-date-hd">Time TBD</div>${tbd.map(s => seriesRow(s, stateOf.get(s), ctx)).join("")}</div>`;
      }
      return html;
    };

    const render = () => {
      const prevFocus = _schedFocusTarget();
      const now = Math.floor(Date.now() / 1000);
      _schedKeyById = new Map();
      const hide = _schedHideOn();
      const revealed = _schedRevealedKeys();
      const ctxOf = i => ({live, hide, revealed, reportWeeks, weekId: weeks[i] ? weeks[i].week_id : null});
      const stateOf = new Map();
      _schedRevealedKeysByWeek = byWeek.map(() => []);
      _schedHiddenKeysByWeek = byWeek.map((list, i) => {
        const ctx = ctxOf(i);
        const keys = [];
        for (const s of list) {
          const state = rowState(s, ctx);
          stateOf.set(s, state);
          if (state === "hidden") keys.push(seriesKey(s));
          // Shown only because it was revealed on this tab: "Hide week again" can undo it.
          else if (state === "shown" && hide && revealed.has(seriesKey(s))
                   && !(ctx.weekId != null && reportWeeks.has(ctx.weekId))) {
            _schedRevealedKeysByWeek[i].push(seriesKey(s));
          }
        }
        return keys;
      });
      _schedWeeks = weeks;
      const current = currentWeekIndex(weeks, now);
      let sel = weeks.findIndex(w => w.key === _schedWeekKey);
      if (sel < 0) sel = current;

      const toggle = document.getElementById("scheduleHideToggle");
      if (toggle) toggle.setAttribute("aria-pressed", hide ? "true" : "false");
      const nowHtml = nowStripHtml(now, stateOf);
      renderIfChanged(nowEl, nowHtml);
      nowEl.style.display = nowHtml ? "" : "none";
      if (renderIfChanged(weeksEl, weekStripHtml(sel, current))) {
        const strip = weeksEl.querySelector(".schedule-week-chips");
        const chip = weeksEl.querySelector(".schedule-week-chip.selected");
        if (strip && chip) strip.scrollLeft = chip.offsetLeft - (strip.clientWidth - chip.offsetWidth) / 2;
      }
      renderIfChanged(content, weekPanelHtml(sel, current, now, stateOf, ctxOf));
      _schedRestoreFocus(prevFocus);
    };
    _schedRerender = render;
    render();

    setStatus("scheduleStatus", "");
  } catch (e) {
    console.error("loadSchedule failed:", e);
    setStatus("scheduleStatus", "Couldn't load the schedule. Refresh to try again.", false);
    if (firstLoad) renderIfChanged(content, "");
  }
}

function showPlayerPreview(name, avatarUrl) {
  const preview = document.getElementById("profilePlayerPreview");
  document.getElementById("profilePlayerName").textContent = name || "";
  const avatar = document.getElementById("profilePlayerAvatar");
  const safeAvatar = _safeUrl(avatarUrl);
  if (safeAvatar) { avatar.src = safeAvatar; avatar.style.display = ""; }
  else { avatar.style.display = "none"; }
  preview.style.display = name ? "flex" : "none";
}
