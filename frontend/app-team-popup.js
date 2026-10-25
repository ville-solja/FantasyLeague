// ---------------------------------------------------------------------------
// Team popup (issue 211, moved out of app-players.js). Opened from every team
// name (teamLink). Sections, top to bottom: header (logo, name, division and
// season, title chips), summary tiles, season results (form strip, series,
// upcoming), roster, points by source against the average team, heroes.
// Everything comes from GET /teams/{id}; no scoring maths happens here.
// ---------------------------------------------------------------------------

// Sections the empty state hides (ids in index.html, in display order).
const _TEAM_SECTION_IDS = ["teamModalStats", "teamModalResults", "teamModalRoster",
                           "teamModalSources", "teamModalHeroes"];
const _TEAM_SERIES = 5;          // stacked-bar colours before "Other"
const _TEAM_DIVISION_LABELS = { div1: "Div 1", div2: "Div 2" };
// Roster columns that sort ascending first; every other column starts descending.
const _TEAM_ROSTER_ASC = ["name", "role"];

let _teamPopup = null;
let _teamRosterSort = { col: "total_points", dir: "desc" };

async function openTeamModal(teamId) {
  const modal = document.getElementById("teamModal");
  modal.classList.remove("hidden");
  document.getElementById("teamModalName").textContent = "Loading...";
  document.getElementById("teamModalMeta").innerHTML = "";
  document.getElementById("teamModalTitles").innerHTML = "";
  document.getElementById("teamModalLogo").innerHTML = "";
  document.getElementById("teamModalStatus").textContent = "";
  const empty = document.getElementById("teamModalEmpty");
  if (empty) empty.hidden = true;
  for (const id of _TEAM_SECTION_IDS) {
    const el = document.getElementById(id);
    if (el) { el.hidden = true; el.innerHTML = ""; }
  }
  _teamPopup = null;
  _teamRosterSort = { col: "total_points", dir: "desc" };

  try {
    const res = await fetch(`${API}/teams/${Number(teamId)}`);
    const t = await res.json();
    if (!res.ok) {
      document.getElementById("teamModalName").textContent = "";
      setStatus("teamModalStatus", t.detail || "Failed to load", false);
      return;
    }
    renderTeamPopup(t);
  } catch (e) {
    setStatus("teamModalStatus", e.message, false);
  }
}

function closeTeamModal() {
  document.getElementById("teamModal").classList.add("hidden");
}

/** Fills every section of the popup from one GET /teams/{id} response. */
function renderTeamPopup(t) {
  _teamPopup = t;
  document.getElementById("teamModalName").textContent = t.name || "";
  document.getElementById("teamModalLogo").innerHTML = _teamLogoHtml(t.name, t.logo_url, "team-logo--lg");
  document.getElementById("teamModalMeta").innerHTML = _teamMetaHtml(t);
  document.getElementById("teamModalTitles").innerHTML = _teamTitleChipsHtml(t.titles);

  const fill = (id, html) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = html;
    el.hidden = !html;
  };
  const empty = document.getElementById("teamModalEmpty");
  const games = Number((t.summary || {}).games) || 0;
  if (!games) {
    for (const id of _TEAM_SECTION_IDS) fill(id, "");
    // Upcoming fixtures still show: they say when the team plays first.
    if ((t.upcoming || []).length) fill("teamModalResults", _teamResultsHtml(t));
    if (empty) { empty.textContent = "No matches yet this season."; empty.hidden = false; }
  } else {
    if (empty) empty.hidden = true;
    fill("teamModalStats", _teamTilesHtml(t));
    fill("teamModalResults", _teamResultsHtml(t));
    fill("teamModalRoster", _teamRosterHtml(t));
    fill("teamModalSources", _teamSourcesHtml(t));
    fill("teamModalHeroes", _teamHeroesHtml(t));
  }
  _initAccoladeTips();
  refreshAccoladeIcons();
}

// ---- Helpers -------------------------------------------------------------

function _teamNum(v, digits = 1) {
  return Number(v || 0).toFixed(digits);
}

/** The team logo, or the design system's monogram chip when there is none. */
function _teamLogoHtml(name, url, cls = "") {
  const extra = cls ? ` ${cls}` : "";
  if (_safeUrl(url)) {
    return `<img draggable="false" class="team-logo${extra}" src="${_escHtml(_safeUrl(url))}" alt="" onerror="this.style.display='none'" />`;
  }
  const mono = String(name || "").replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase();
  return `<span class="team-logo team-logo--mono${extra}" aria-hidden="true">${_escHtml(mono)}</span>`;
}

function _teamDivisionLabel(div) {
  return _TEAM_DIVISION_LABELS[div] || "";
}

/** mm:ss from seconds (rounded); "—" when unknown. */
function _teamGameLength(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "—";
  return _formatGameDuration(Math.round(Number(seconds)));
}

function _teamRecordText(w, l, d) {
  return `${Number(w) || 0}–${Number(l) || 0}${Number(d) ? `–${Number(d)}` : ""}`;
}

// ---- Header ----------------------------------------------------------------

/** "Div 1 · Season 17" (either part left out when unknown). */
function _teamMetaHtml(t) {
  const parts = [_teamDivisionLabel(t.division), t.season || ""].filter(Boolean);
  return parts.length ? `<span class="team-popup-division">${_escHtml(parts.join(" · "))}</span>` : "";
}

/** One accolade chip per title ("S16 Div 1 Champion"), newest first. */
function _teamTitleChipsHtml(titles) {
  return accoladeChipsHtml(Array.isArray(titles) ? titles : []);
}

// ---- Summary tiles -------------------------------------------------------

function _teamTile(val, lbl, sub) {
  return `<div class="player-modal-stat"><div class="val">${val}</div><div class="lbl">${lbl}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function _teamTilesHtml(t) {
  const s = t.summary || {};
  const series = Number(s.series_wins) + Number(s.series_losses) + Number(s.series_draws || 0);
  const tiles = [
    _teamTile(_escHtml(_teamRecordText(s.series_wins, s.series_losses, s.series_draws)), "Series W–L",
              series ? "" : "No series yet"),
    _teamTile(_escHtml(_teamRecordText(s.wins, s.losses)), "Games W–L", `${_escHtml(s.games || 0)} games`),
    _teamTile(_teamNum(s.points_per_game), "Pts per game", "Five players combined"),
    _teamTile(_escHtml(_teamGameLength(s.avg_game_length)), "Avg game", ""),
    _teamTile(_escHtml(s.mvps || 0), "MVPs", ""),
  ];
  return `<div class="player-modal-stat-grid player-popup-tiles">${tiles.join("")}</div>`;
}

// ---- Season results --------------------------------------------------------

const _TEAM_RESULT_WORDS = { W: "Won", L: "Lost", D: "Drew" };
const _TEAM_RESULT_SHAPES = { W: "win", L: "loss", D: "draw" };

function _teamSeriesWords(s) {
  const opp = (s.opponent && s.opponent.name) || "—";
  const week = s.week ? `, ${s.week}` : "";
  return `${_TEAM_RESULT_WORDS[s.result] || "Played"} ${_teamRecordText(s.wins, s.losses)} against ${opp}${week}`;
}

/** A result chip: the letter as text, a shape class (filled win, hollow loss,
 * dashed draw) and the full result as its label, so colour is never alone. */
function _teamResultChipHtml(s, extraCls = "") {
  const shape = _TEAM_RESULT_SHAPES[s.result] || "draw";
  const words = _teamSeriesWords(s);
  return `<span class="team-result team-result--${shape}${extraCls}" role="img" aria-label="${_escHtml(words)}" title="${_escHtml(words)}">${_escHtml(s.result || "")}</span>`;
}

function _teamOpponentHtml(o) {
  o = o || {};
  const link = o.id ? teamLink(o.id, o.name) : (_escHtml(o.name) || "—");
  return `<span class="team-series-opp">${_teamLogoHtml(o.name, o.logo_url, "team-logo--sm")}${link}</span>`;
}

function _teamUpcomingWhen(s) {
  const iso = String(s.datetime_iso || "");
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso);
  if (!m) return _escHtml([s.date, s.time].filter(Boolean).join(" ")) || "Date to be set";
  const date = `${Number(m[3])}.${Number(m[2])}.`;
  return s.scheduled === false || !m[4] ? `Week of ${date}` : `${date} ${m[4]}:${m[5]}`;
}

function _teamStreamHtml(s) {
  if (!_safeUrl(s.stream_url)) return "";
  return `<a class="stream-link" href="${_escHtml(_safeUrl(s.stream_url))}" target="_blank" rel="noopener noreferrer">Stream ↗</a>`;
}

function _teamResultsHtml(t) {
  const series = Array.isArray(t.series) ? t.series : [];
  const upcoming = Array.isArray(t.upcoming) ? t.upcoming : [];
  if (!series.length && !upcoming.length) {
    return `<h2>Season results</h2><p class="player-popup-note">No series in the schedule yet.</p>`;
  }
  const form = series.length
    ? `<div class="team-form" role="group" aria-label="${_escHtml(`Form: ${series.map(s => s.result).join(" ")}`)}">${series.map(s => _teamResultChipHtml(s)).join("")}</div>`
    : "";
  const played = series.map(s => `
      <li class="team-series-row">
        <span class="team-series-week">${_escHtml(s.week_short || s.week || "")}</span>
        ${_teamOpponentHtml(s.opponent)}
        <span class="team-series-score">${_escHtml(_teamRecordText(s.wins, s.losses))}</span>
        <span class="team-series-result">${_teamResultChipHtml(s)}</span>
      </li>`).join("");
  const next = upcoming.map(s => `
      <li class="team-series-row team-series-row--upcoming">
        <span class="team-series-week">${_escHtml(s.week_short || s.week || "")}</span>
        ${_teamOpponentHtml(s.opponent)}
        <span class="team-series-when">${_teamUpcomingWhen(s)}</span>
        <span class="team-series-result">${_teamStreamHtml(s)}</span>
      </li>`).join("");
  return `
    <h2>Season results</h2>
    ${form}
    ${played ? `<ol class="team-series-list">${played}</ol>` : ""}
    ${next ? `<h3 class="player-bio-eyebrow">Upcoming</h3><ol class="team-series-list">${next}</ol>` : ""}`;
}

// ---- Roster ----------------------------------------------------------------

const _TEAM_ROSTER_COLS = [
  ["name", "Player"], ["role", "Role"], ["games", "Games"], ["avg_points", "Avg pts"],
  ["total_points", "Total pts"], ["share", "Share"], ["owned_pct", "Owned"],
];

function _teamSortRoster(players, sort) {
  const col = sort.col;
  const asc = sort.dir === "asc";
  return players.slice().sort((a, b) => {
    const av = a[col], bv = b[col];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
    return asc ? cmp : -cmp;
  });
}

/** A roster column header was activated: sort by it, or flip the direction. */
function sortTeamRoster(col) {
  if (_teamRosterSort.col === col) {
    _teamRosterSort.dir = _teamRosterSort.dir === "asc" ? "desc" : "asc";
  } else {
    _teamRosterSort = { col, dir: _TEAM_ROSTER_ASC.includes(col) ? "asc" : "desc" };
  }
  const el = document.getElementById("teamModalRoster");
  if (el && _teamPopup) {
    el.innerHTML = _teamRosterHtml(_teamPopup);
    refreshAccoladeIcons();
  }
}

function _teamRosterHeadHtml() {
  return _TEAM_ROSTER_COLS.map(([col, label]) => {
    const on = _teamRosterSort.col === col;
    const cls = on ? ` sort-${_teamRosterSort.dir}` : "";
    const aria = on ? (_teamRosterSort.dir === "asc" ? "ascending" : "descending") : "none";
    return `<th scope="col" class="sortable${cls}" data-col="${col}" aria-sort="${aria}" tabindex="0" onclick="sortTeamRoster('${col}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();sortTeamRoster('${col}')}">${label}</th>`;
  }).join("");
}

/** "Owned by N %", or "—" while the server withholds ownership (too few managers). */
function _teamOwnedText(pct) {
  if (pct == null || !Number.isFinite(Number(pct))) return "—";
  return `Owned by ${_escHtml(Math.round(Number(pct)))} %`;
}

function _teamRosterRowHtml(p) {
  const id = Number(p.id);
  const pips = (typeof tagPipsHtml === "function" ? tagPipsHtml(p.tags || []) : "")
    + accoladePipsHtml(p.accolades || [], { omitPlayed: true });
  const role = p.role
    ? `<span class="status-badge player-role-chip" title="From this season's averages: Support when wards are 3 or more and GPM is under 450.">${_escHtml(p.role)}</span>`
    : "";
  const share = Math.max(0, Math.min(100, Number(p.share) || 0));
  return `<tr class="team-roster-row">
          <td class="tr-player" data-label="Player"><img draggable="false" class="team-roster-avatar" src="${_escHtml(_safeUrl(p.avatar_url))}" alt="" onerror="this.style.display='none'" /><span class="entity-link" tabindex="0" role="button" onclick="closeTeamModal();openPlayerModal(${id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();closeTeamModal();openPlayerModal(${id})}">${_escHtml(p.name)}</span>${pips ? `<span class="team-roster-pips">${pips}</span>` : ""}</td>
          <td class="tr-role" data-label="Role">${role}</td>
          <td class="tr-games" data-label="Games">${_escHtml(p.games)} / ${_escHtml(p.team_games)}</td>
          <td class="tr-avg" data-label="Avg pts">${Number(p.avg_points || 0).toFixed(1)}</td>
          <td class="tr-total" data-label="Total pts">${Number(p.total_points || 0).toFixed(1)}</td>
          <td class="tr-share" data-label="Share"><span class="team-share"><span class="team-share-track" aria-hidden="true"><span class="team-share-fill" style="--w: ${share}%"></span></span><span class="team-share-pct">${_teamNum(p.share)} %</span></span></td>
          <td class="tr-owned" data-label="Owned">${_teamOwnedText(p.owned_pct)}</td>
        </tr>`;
}

function _teamRosterHtml(t) {
  const players = Array.isArray(t.players) ? t.players : [];
  if (!players.length) return `<h2>Roster</h2><p class="player-popup-note">No players yet this season.</p>`;
  const main = _teamSortRoster(players.filter(p => !p.also_played), _teamRosterSort);
  const also = _teamSortRoster(players.filter(p => p.also_played), _teamRosterSort);
  const alsoRows = also.length
    ? `<tr class="team-roster-group"><th colspan="${_TEAM_ROSTER_COLS.length}" scope="colgroup">Also played</th></tr>${also.map(_teamRosterRowHtml).join("")}`
    : "";
  return `
    <h2>Roster</h2>
    <p class="player-popup-note">Share is the player's part of the team's points. Owned is the share of managers holding an active card of the player${t.ownership_hidden ? "; it shows once at least 10 managers have cards" : ""}.</p>
    <div class="team-roster-wrap">
      <table class="team-roster">
        <thead><tr>${_teamRosterHeadHtml()}</tr></thead>
        <tbody>${main.map(_teamRosterRowHtml).join("")}${alsoRows}</tbody>
      </table>
    </div>`;
}

// ---- Points by source ------------------------------------------------------

function _teamSourcesHtml(t) {
  const sources = (t.points_sources || []).filter(s => Number(s.avg) > 0 || Number(s.league_avg) > 0);
  if (!sources.some(s => Number(s.avg) > 0)) {
    return `<h2>Where the points come from</h2><p class="player-popup-note">No scored matches yet.</p>`;
  }
  const ranked = sources.slice().sort((a, b) => Number(b.avg) - Number(a.avg));
  const seriesOf = new Map();
  ranked.filter(s => Number(s.avg) > 0).forEach((s, i) => seriesOf.set(s.key, i < _TEAM_SERIES ? String(i + 1) : "other"));
  const segments = [];
  let other = 0;
  for (const s of ranked) {
    if (!(Number(s.share) > 0)) continue;
    if (seriesOf.get(s.key) === "other") { other += Number(s.share); continue; }
    segments.push(`<span class="sources-seg sources-seg--${seriesOf.get(s.key)}" style="--w: ${Number(s.share)}%" title="${_escHtml(s.label)} ${_escHtml(s.share)} %"></span>`);
  }
  if (other > 0) segments.push(`<span class="sources-seg sources-seg--other" style="--w: ${other}%" title="Other ${other.toFixed(1)} %"></span>`);
  const scale = Math.max(...ranked.map(s => Math.max(Number(s.avg) || 0, Number(s.league_avg) || 0)), 0.1);
  const pos = v => `${Math.min(100, (Number(v) || 0) / scale * 100).toFixed(1)}%`;
  const rows = ranked.map(s => `
      <li class="sources-row">
        <span class="sources-swatch sources-seg--${seriesOf.get(s.key) || "none"}" aria-hidden="true"></span>
        <span class="sources-label">${_escHtml(s.label)}</span>
        <span class="sources-track" aria-hidden="true"><span class="sources-fill" style="--w: ${pos(s.avg)}"></span><span class="sources-league" style="--x: ${pos(s.league_avg)}"></span></span>
        <span class="sources-avg">${_teamNum(s.avg)}</span>
        <span class="sources-share">${_teamNum(s.share)} %</span>
        <span class="visually-hidden">Average team ${_teamNum(s.league_avg)}</span>
      </li>`).join("");
  const aria = ranked.filter(s => Number(s.share) > 0).map(s => `${s.label} ${_teamNum(s.share)} %`).join(", ");
  return `
    <h2>Where the points come from</h2>
    <div class="sources-bar" role="img" aria-label="${_escHtml(aria)}">${segments.join("")}</div>
    <div class="sources-head" aria-hidden="true"><span></span><span></span><span>Per team game · <span class="sources-league-key"></span> average team</span><span>Avg</span><span>Share</span></div>
    <ol class="sources-list">${rows}</ol>
    ${_teamModifierHtml(t.modifier_values)}`;
}

/** "A +10 % modifier pays most on this team's players: Kills, GPM, Assists". */
function _teamModifierHtml(mv) {
  const stats = mv && Array.isArray(mv.stats) ? mv.stats : [];
  if (!stats.length) return "";
  const top = stats.slice(0, 3).map(s => _escHtml(s.label)).join(", ");
  return `<p class="modifier-line">A +${_escHtml(Number(mv.bonus_pct) || 0)} % modifier pays most on this team's players: ${top}</p>`;
}

// ---- Heroes ----------------------------------------------------------------

function _teamHeroTile(h) {
  const name = h.hero_name || `Hero ${h.hero_id}`;
  const icon = h.icon_url
    ? `<img draggable="false" class="hero-icon" src="${_escHtml(_safeUrl(h.icon_url))}" alt="" onerror="this.style.display='none'" />`
    : `<span class="hero-icon hero-icon-placeholder" aria-hidden="true"></span>`;
  const players = (h.players || []).map(p => `${_escHtml(p.name)}${Number(p.games) > 1 ? ` (${_escHtml(p.games)})` : ""}`).join(", ");
  return `<li class="hero-tile">${icon}<span class="hero-tile-name">${_escHtml(name)}</span><span class="hero-tile-stats">${_escHtml(h.games)} game${h.games === 1 ? "" : "s"} · ${_escHtml(h.wins)}–${_escHtml(h.losses)}</span>${players ? `<span class="hero-tile-players">${players}</span>` : ""}</li>`;
}

function _teamHeroesHtml(t) {
  const heroes = Array.isArray(t.heroes) ? t.heroes : [];
  const body = heroes.length
    ? `<ul class="hero-grid">${heroes.map(_teamHeroTile).join("")}</ul>`
    : `<p class="player-popup-note">No hero data for this season yet.</p>`;
  return `<h2>Heroes</h2>${body}`;
}
