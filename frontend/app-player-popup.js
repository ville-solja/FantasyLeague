// ---------------------------------------------------------------------------
// Player popup (issue 208, moved out of app-players.js). Opened from every
// player name and card. Sections, top to bottom: header (pips, seasons played,
// role chip), summary tiles (with the Rank tile, issue 230), form chart, points by source, league comparison,
// heroes, Accolades (issue 50), match history with per-match Details, bio.
// Everything comes from GET /players/{id}; the profile facts (career heroes, bio)
// load afterwards from GET /players/{id}/profile.
// ---------------------------------------------------------------------------

const _PARTIAL_STATS_TOOLTIP =
  "The replay has not been parsed, so wards, stuns, teamfight, runes and camps count as 0.";
// _NOT_SCORED_TOOLTIP is in app-players.js (the Schedule uses it too).
const _POPUP_TOP_HEROES = 6;
const _POPUP_SERIES = 5;         // stacked-bar colours before "Other"
const _POPUP_HISTORY_COLS = 12;

// Sections the empty state replaces (ids in index.html).
const _POPUP_SECTION_IDS = ["playerModalStats", "playerModalForm", "playerModalSources",
                            "playerModalCompare", "playerModalHeroes", "playerModalHistorySection"];

let _popupHighlightedRow = null;
let _popupPlayer = null;

async function openPlayerModal(playerId) {
  const modal = document.getElementById("playerModal");
  modal.classList.remove("hidden");
  document.getElementById("playerModalName").textContent = "Loading...";
  document.getElementById("playerModalTeam").innerHTML = "";
  document.getElementById("playerModalMeta").innerHTML = "";
  document.getElementById("playerModalAvatar").style.display = "none";
  document.getElementById("playerModalStats").innerHTML = "";
  document.getElementById("playerModalHistory").innerHTML = "";
  document.getElementById("playerModalStatus").textContent = "";
  const empty = document.getElementById("playerModalEmpty");
  if (empty) empty.hidden = true;
  for (const id of ["playerModalForm", "playerModalSources", "playerModalCompare", "playerModalHeroes"]) {
    const el = document.getElementById(id);
    if (el) { el.hidden = true; el.innerHTML = ""; }
  }
  const profileEl = document.getElementById("playerProfile");
  if (profileEl) { profileEl.style.display = "none"; profileEl.innerHTML = ""; }
  _popupHighlightedRow = null;
  _popupPlayer = null;
  renderPlayerAccolades(null);

  try {
    const res = await fetch(`${API}/players/${playerId}`);
    const p = await res.json();
    if (!res.ok) {
      document.getElementById("playerModalName").textContent = "";
      setStatus("playerModalStatus", p.detail || "Failed to load", false);
      return;
    }
    _popupPlayer = p;

    const avatar = document.getElementById("playerModalAvatar");
    const avatarUrl = _safeUrl(p.avatar_url);
    if (avatarUrl) { avatar.src = avatarUrl; avatar.style.display = ""; }

    document.getElementById("playerModalName").textContent = p.name;
    document.getElementById("playerModalTeam").innerHTML = p.team_id
      ? `<span class="entity-link" tabindex="0" role="button" onclick="closePlayerModal();openTeamModal(${p.team_id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();closePlayerModal();openTeamModal(${p.team_id})}">${_escHtml(p.team_name)}</span>`
      : _escHtml(p.team_name || "");

    renderPlayerPopup(p);
    renderPlayerAccolades(p);

    // Non-blocking profile fetch — modal shows immediately even if profile unavailable
    fetch(`${API}/players/${playerId}/profile`).then(async r => {
      if (!r.ok) return;
      const profile = await r.json();
      renderPlayerCareerHeroes(profile);
      renderPlayerProfile(profile);
    }).catch(() => {});
  } catch (e) {
    setStatus("playerModalStatus", e.message, false);
  }
}

/** Fills every issue 208 section of the popup from one GET /players/{id} response. */
function renderPlayerPopup(p) {
  const history = Array.isArray(p.match_history) ? p.match_history : [];
  document.getElementById("playerModalMeta").innerHTML = _popupMetaHtml(p);
  const empty = document.getElementById("playerModalEmpty");
  if (!history.length) {
    for (const id of _POPUP_SECTION_IDS) {
      const el = document.getElementById(id);
      if (el) el.hidden = true;
    }
    if (empty) { empty.textContent = "No matches yet this season."; empty.hidden = false; }
    return;
  }
  if (empty) empty.hidden = true;
  const fill = (id, html) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = html;
    el.hidden = !html;
  };
  fill("playerModalStats", _popupTilesHtml(p));
  fill("playerModalForm", _popupFormChartHtml(p));
  fill("playerModalSources", _popupSourcesHtml(p, _popupOwnCardModifiers(p.id)));
  fill("playerModalCompare", _popupComparisonHtml(p));
  fill("playerModalHeroes", _popupHeroesHtml(p));
  document.getElementById("playerModalHistory").innerHTML = history.map(_popupHistoryRowHtml).join("");
  const section = document.getElementById("playerModalHistorySection");
  if (section) section.hidden = false;
  _initAccoladeTips();
}

// ---- Helpers -------------------------------------------------------------

function _popupScored(p) {
  return (Array.isArray(p.match_history) ? p.match_history : []).filter(m => !m.excluded_from_scoring);
}

function _popupIsPartial(m) {
  return m.parse_status === "unparsed" || m.parse_status === "unparseable";
}

function _popupDate(ts) {
  return ts
    ? new Date(ts * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "2-digit"})
    : "—";
}

function _popupResultText(m) {
  return m.won === true ? "W" : m.won === false ? "L" : "";
}

function _popupResultWord(m) {
  return m.won === true ? "Win" : m.won === false ? "Loss" : "Result unknown";
}

function _popupNum(v, digits = 1) {
  return Number(v || 0).toFixed(digits);
}

// ---- Header ----------------------------------------------------------------

/** Seasons played (issue 50) and the Core / Support chip, computed from this
 * season's scored matches: Support when average wards >= 3 and GPM < 450. */
function _popupMetaHtml(p) {
  const parts = [];
  const seasons = Number(p.seasons_played) || 0;
  if (seasons) parts.push(`<span class="player-modal-seasons">${seasons} season${seasons === 1 ? "" : "s"} played</span>`);
  const role = _popupRoleChipHtml(p);
  if (role) parts.push(role);
  return parts.join("");
}

function _popupRoleChipHtml(p) {
  const scored = _popupScored(p);
  if (!scored.length) return "";
  const avg = key => scored.reduce((sum, m) => sum + (Number(m[key]) || 0), 0) / scored.length;
  const support = avg("obs_placed") >= 3 && avg("gold_per_min") < 450;
  return `<span class="status-badge player-role-chip" title="From this season's averages: Support when wards are 3 or more and GPM is under 450.">${support ? "Support" : "Core"}</span>`;
}

// ---- Summary tiles -------------------------------------------------------

function _popupTile(val, lbl, sub, cls = "") {
  return `<div class="player-modal-stat${cls ? ` ${cls}` : ""}"><div class="val">${val}</div><div class="lbl">${lbl}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

/** Issue 230: the last known rank as a statistic, "Legend 4" with
 * "OpenDota, <date>" underneath; "" for an unranked player. */
function _popupRankTile(p) {
  const medal = p.rank_tier ? rankMedalHtml(p.rank_tier, p.leaderboard_rank) : "";
  if (!medal) return "";
  const ts = Number(p.rank_fetched_at);
  const when = Number.isFinite(ts) && ts > 0 ? `, ${_popupDate(ts)}` : "";
  return _popupTile(medal, "Rank", _escHtml(`OpenDota${when}`), "player-modal-stat--rank");
}

function _popupTilesHtml(p) {
  const s = p.summary || {};
  const rank = s.avg_rank ? `#${_escHtml(s.avg_rank.rank)} of ${_escHtml(s.avg_rank.of)}` : "";
  const best = p.best_match;
  const tiles = [
    _popupTile(_escHtml(p.matches), "Matches", `${_escHtml(s.wins || 0)}–${_escHtml(s.losses || 0)}`),
    _popupTile(Number(p.avg_points).toFixed(1), "Avg pts", rank),
    _popupTile(Number(p.total_points).toFixed(1), "Total pts", ""),
    best ? _popupTile(Number(best.fantasy_points).toFixed(1), "Best match", best.opponent_team_name ? `vs ${_escHtml(best.opponent_team_name)}` : "") : "",
    _popupTile(_escHtml(s.mvps || 0), "MVPs", ""),
    _popupRankTile(p),
  ];
  const ranked = tiles[tiles.length - 1] ? " player-popup-tiles--ranked" : "";
  return `<div class="player-modal-stat-grid player-popup-tiles${ranked}">${tiles.join("")}</div>`;
}

// ---- Form chart ----------------------------------------------------------

function _popupBarTip(m) {
  const pts = m.excluded_from_scoring ? "Not scored" : `${Number(m.fantasy_points).toFixed(1)} pts`;
  const bits = [_popupDate(m.start_time), "vs " + (m.opponent_team_name || "—")];
  if (m.hero_name) bits.push(m.hero_name);
  bits.push(_popupResultWord(m), pts, `K/D/A ${m.kills ?? 0}/${m.deaths ?? 0}/${m.assists ?? 0}`);
  if (m.is_mvp) bits.push("MVP");
  if (!m.excluded_from_scoring && _popupIsPartial(m)) bits.push("Partial stats");
  return bits.join(" · ");
}

/** "12 matches, average 14.2, last 3 above average" (the chart's aria-label). */
function _popupFormSummary(p) {
  const scored = _popupScored(p);
  const n = (p.match_history || []).length;
  const avg = Number(p.avg_points || 0);
  let text = `${n} match${n === 1 ? "" : "es"}, average ${avg.toFixed(1)}`;
  if (scored.length) {
    // match_history is newest first, so the last matches are at the start.
    const last = scored.slice(0, 3);
    const above = last.filter(m => Number(m.fantasy_points) > avg).length;
    const k = last.length;
    if (above === k) text += `, last ${k} above average`;
    else if (above === 0) text += `, last ${k} below average`;
    else text += `, ${above} of last ${k} above average`;
  }
  return text;
}

function _popupFormChartHtml(p) {
  const history = (p.match_history || []).slice().reverse();  // oldest left
  if (!history.length) return "";
  const avg = Number(p.avg_points || 0);
  const league = Number(p.league_avg_points || 0);
  const top = Math.max(1, avg, league, ...history.map(m => Number(m.fantasy_points) || 0)) * 1.1;
  const pct = v => `${Math.max(0, Math.min(100, (Number(v) || 0) / top * 100)).toFixed(1)}%`;
  const frac = v => Math.max(0, Math.min(1, (Number(v) || 0) / top)).toFixed(3);

  const weeks = [];
  for (const m of history) {
    const label = m.week_label || "";
    const last = weeks[weeks.length - 1];
    if (last && last.label === label) last.matches.push(m);
    else weeks.push({ label, matches: [m] });
  }
  const bar = m => {
    const cls = ["form-bar"];
    if (m.excluded_from_scoring) cls.push("form-bar--ghost");
    else if (_popupIsPartial(m)) cls.push("form-bar--partial");
    const tip = _popupBarTip(m);
    const star = m.is_mvp ? `<span class="form-bar-star" aria-hidden="true">★</span>` : "";
    const result = m.won === true ? `<span class="form-bar-result form-bar-result--win" aria-hidden="true"></span>`
      : m.won === false ? `<span class="form-bar-result form-bar-result--loss" aria-hidden="true"></span>`
      : `<span class="form-bar-result" aria-hidden="true"></span>`;
    const id = Number(m.match_id);
    const height = pct(m.fantasy_points);
    return `<button type="button" class="${cls.join(" ")}" data-match-id="${id}" data-tip="${_escHtml(tip)}" aria-label="${_escHtml(tip)}" style="--h: ${height}" onclick="activatePlayerFormBar(${id})"><span class="form-bar-plot">${star}<span class="form-bar-fill"></span></span>${result}</button>`;
  };
  const groups = weeks.map(w => `
      <div class="form-week">
        <div class="form-week-bars">${w.matches.map(bar).join("")}</div>
        <div class="form-week-label">${_escHtml(w.label)}</div>
      </div>`).join("");
  const season = p.current_season ? `${_escHtml(p.current_season)} form` : "Season form";
  return `
    <h2>${season}</h2>
    <div class="form-chart" role="group" aria-label="${_escHtml(_popupFormSummary(p))}">
      <div class="form-chart-plot">
        <div class="form-ref form-ref--player" style="--y: ${frac(avg)}"><span class="form-ref-label">Avg ${avg.toFixed(1)}</span></div>
        <div class="form-ref form-ref--league" style="--y: ${frac(league)}"><span class="form-ref-label">League ${league.toFixed(1)}</span></div>
        ${groups}
      </div>
    </div>
    <p class="form-chart-legend">Bar height is fantasy points. ★ MVP · filled square win · hollow square loss · dashed bar not scored · hatched bar partial stats.</p>`;
}

/** A form chart bar was activated: scroll to that match's history row and
 * highlight it (only that row). */
function activatePlayerFormBar(matchId) {
  const row = document.getElementById(`playerMatchRow-${Number(matchId)}`);
  if (!row) return;
  if (_popupHighlightedRow && _popupHighlightedRow !== row) _popupHighlightedRow.classList.remove("is-highlighted");
  row.classList.add("is-highlighted");
  _popupHighlightedRow = row;
  if (typeof row.scrollIntoView === "function") {
    row.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }
}

// ---- Points by source ------------------------------------------------------

/** {stat: bonus_pct} of the viewer's own cards of this player, from the already
 * loaded My Team data (no request). Empty when logged out or not owned. */
function _popupOwnCardModifiers(playerId) {
  const out = {};
  if (typeof activeUserId === "undefined" || activeUserId == null) return out;
  const cards = typeof _rosterCards !== "undefined" && Array.isArray(_rosterCards) ? _rosterCards : [];
  for (const c of cards) {
    if (Number(c.player_id) !== Number(playerId)) continue;
    for (const mod of c.modifiers || []) {
      out[mod.stat] = Math.max(out[mod.stat] || 0, Number(mod.bonus_pct) || 0);
    }
  }
  return out;
}

function _popupSourcesHtml(p, ownMods = {}) {
  const sources = (p.points_sources || []).filter(s => Number(s.avg) > 0 || Number(s.league_avg) > 0);
  if (!_popupScored(p).length || !sources.length) {
    return `<h2>Points by source</h2><p class="player-popup-note">No scored matches yet.</p>`;
  }
  const ranked = sources.slice().sort((a, b) => Number(b.avg) - Number(a.avg));
  const seriesOf = new Map();
  ranked.filter(s => Number(s.avg) > 0).forEach((s, i) => seriesOf.set(s.key, i < _POPUP_SERIES ? String(i + 1) : "other"));
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
  const rows = ranked.map(s => {
    const series = seriesOf.get(s.key) || "none";
    return `
      <li class="sources-row">
        <span class="sources-swatch sources-seg--${series}" aria-hidden="true"></span>
        <span class="sources-label">${_escHtml(s.label)}</span>
        <span class="sources-track" aria-hidden="true"><span class="sources-fill" style="--w: ${pos(s.avg)}"></span><span class="sources-league" style="--x: ${pos(s.league_avg)}"></span></span>
        <span class="sources-avg">${_popupNum(s.avg)}</span>
        <span class="sources-share">${_popupNum(s.share)} %</span>
        <span class="visually-hidden">League average ${_popupNum(s.league_avg)}</span>
      </li>`;
  }).join("");
  const aria = ranked.filter(s => Number(s.share) > 0).map(s => `${s.label} ${_popupNum(s.share)} %`).join(", ");
  return `
    <h2>Points by source</h2>
    <div class="sources-bar" role="img" aria-label="${_escHtml(aria)}">${segments.join("")}</div>
    <div class="sources-head" aria-hidden="true"><span></span><span></span><span>Per match · <span class="sources-league-key"></span> league average</span><span>Avg</span><span>Share</span></div>
    <ol class="sources-list">${rows}</ol>
    ${_popupModifierHtml(p.modifier_values, ownMods)}`;
}

/** "A +10 % modifier is worth most on: Kills (+0.42 / match), GPM (+0.38), …" and,
 * when the viewer owns a card of this player, that card's modifiers highlighted. */
function _popupModifierHtml(mv, ownMods = {}) {
  const stats = mv && Array.isArray(mv.stats) ? mv.stats : [];
  if (!stats.length) return "";
  const bonus = Number(mv.bonus_pct) || 0;
  const top = stats.slice(0, 3).map((s, i) =>
    `${_escHtml(s.label)} (+${_popupNum(s.value, 2)}${i === 0 ? " / match" : ""})`).join(", ");
  const own = Object.keys(ownMods || {});
  const list = stats.map(s => {
    const pct = ownMods[s.stat];
    if (pct != null) {
      const worth = (Number(s.base) || 0) * pct / 100;
      return `<li class="modifier-item modifier-item--own">${_escHtml(s.label)} +${_escHtml(pct)} % <span class="modifier-value">+${worth.toFixed(2)} / match</span></li>`;
    }
    return `<li class="modifier-item">${_escHtml(s.label)} <span class="modifier-value">+${_popupNum(s.value, 2)}</span></li>`;
  }).join("");
  const ownNote = own.length ? `<p class="modifier-own-note">${statusBadgeHtml("Your card")} Your card's modifiers are marked.</p>` : "";
  return `
    <p class="modifier-line">A +${_escHtml(bonus)} % modifier is worth most on: ${top}</p>
    ${ownNote}
    <ul class="modifier-list${own.length ? " modifier-list--owned" : ""}">${list}</ul>`;
}

// ---- League comparison -----------------------------------------------------

function _popupCompareValue(key, v) {
  if (key === "teamfight_participation") return `${Math.round((Number(v) || 0) * 100)} %`;
  if (key === "gold_per_min" || key === "last_hits") return String(Math.round(Number(v) || 0));
  return _popupNum(v);
}

function _popupCompareRank(key, s) {
  const pctl = Math.max(0, Math.min(100, Number(s.percentile) || 0));
  if (s.lower_is_better && key === "deaths") return `Fewer deaths than ${pctl} % of players`;
  return pctl >= 50 ? `Top ${Math.max(1, 100 - pctl)} %` : `Bottom ${Math.max(1, pctl)} %`;
}

function _popupComparisonHtml(p) {
  const lc = p.league_comparison;
  if (!lc || !lc.stats) {
    return `<h2>Compared with the league</h2><p class="player-popup-note">Not enough matches to compare yet.</p>`;
  }
  const rows = Object.entries(lc.stats).map(([key, s]) => {
    const pctl = Math.max(0, Math.min(100, Number(s.percentile) || 0));
    return `
      <li class="compare-row">
        <span class="compare-label">${_escHtml(s.label)}${s.lower_is_better ? ` <span class="compare-hint">lower is better</span>` : ""}</span>
        <span class="compare-value">${_escHtml(_popupCompareValue(key, s.value))}</span>
        <span class="compare-track" title="League median ${_escHtml(_popupCompareValue(key, s.median))}" aria-hidden="true"><span class="compare-median" style="--x: 50%"></span><span class="compare-dot" style="--x: ${pctl}%"></span></span>
        <span class="compare-rank">${_escHtml(_popupCompareRank(key, s))}</span>
      </li>`;
  }).join("");
  return `
    <h2>Compared with the league</h2>
    <p class="player-popup-note">vs ${_escHtml(lc.population)} players with 3 or more scored matches. The tick is the league median.</p>
    <ol class="compare-list">${rows}</ol>`;
}

// ---- Heroes ----------------------------------------------------------------

function _popupHeroTile(h) {
  const name = h.hero_name || `Hero ${h.hero_id}`;
  const icon = h.icon_url
    ? `<img draggable="false" class="hero-icon" src="${_escHtml(_safeUrl(h.icon_url))}" alt="" onerror="this.style.display='none'" />`
    : `<span class="hero-icon hero-icon-placeholder" aria-hidden="true"></span>`;
  return `<li class="hero-tile">${icon}<span class="hero-tile-name">${_escHtml(name)}</span><span class="hero-tile-stats">${_escHtml(h.games)} game${h.games === 1 ? "" : "s"} · ${_escHtml(h.wins)}–${_escHtml(h.losses)} · ${Number(h.avg_points).toFixed(1)} avg</span></li>`;
}

function _popupHeroesHtml(p) {
  const heroes = Array.isArray(p.heroes) ? p.heroes : [];
  const top = heroes.slice(0, _POPUP_TOP_HEROES).map(_popupHeroTile).join("");
  const rest = heroes.slice(_POPUP_TOP_HEROES).map(_popupHeroTile).join("");
  const more = rest
    ? `<ul class="hero-grid" id="playerHeroesMore" hidden>${rest}</ul>
       <button type="button" class="ghost hero-show-all" aria-expanded="false" aria-controls="playerHeroesMore" data-count="${heroes.length}" onclick="togglePlayerHeroes(this)">Show all (${heroes.length})</button>`
    : "";
  const season = heroes.length
    ? `<ul class="hero-grid">${top}</ul>${more}`
    : `<p class="player-popup-note">No hero data for this season yet.</p>`;
  return `
    <h2>Heroes</h2>
    ${season}
    <div id="playerCareerHeroes" class="hero-career" hidden></div>`;
}

function togglePlayerHeroes(btn) {
  const more = document.getElementById("playerHeroesMore");
  if (!more || !btn) return;
  const open = btn.getAttribute("aria-expanded") !== "true";
  more.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  btn.textContent = open ? "Show fewer" : `Show all (${btn.getAttribute("data-count") || ""})`;
}

/** Career heroes from the profile facts (OpenDota, admin-run crawl): shown only when
 * facts exist, with their update date. */
function _popupCareerHeroesHtml(profile) {
  const facts = profile && profile.facts;
  const heroes = facts && Array.isArray(facts.top_heroes_alltime) ? facts.top_heroes_alltime : [];
  if (!heroes.length) return "";
  const updated = profile.facts_fetched_at
    ? new Date(Number(profile.facts_fetched_at) * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "numeric"})
    : "";
  const items = heroes.slice(0, _POPUP_TOP_HEROES).map(h => {
    const wr = h.win_rate !== undefined && h.win_rate !== null ? `, ${_escHtml(Math.round(Number(h.win_rate) * 100))} % won` : "";
    return `<li><span class="hero-career-name">${_escHtml(h.hero_name)}</span> <span class="hero-career-stats">${_escHtml(h.games)} games${wr}</span></li>`;
  }).join("");
  return `<h3 class="player-bio-eyebrow">Career (OpenDota${updated ? `, updated ${_escHtml(updated)}` : ""})</h3><ul class="hero-career-list">${items}</ul>`;
}

function renderPlayerCareerHeroes(profile) {
  const el = document.getElementById("playerCareerHeroes");
  if (!el) return;
  const html = _popupCareerHeroesHtml(profile);
  el.innerHTML = html;
  el.hidden = !html;
  const section = document.getElementById("playerModalHeroes");
  if (html && section && _popupPlayer && (_popupPlayer.match_history || []).length) section.hidden = false;
}

// ---- Match history -----------------------------------------------------------

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

/** Every stat of one match, including the ones the table leaves out. */
function _popupMatchStats(m) {
  return [
    ["Kills", m.kills ?? 0],
    ["Deaths", m.deaths ?? 0],
    ["Assists", m.assists ?? 0],
    ["Last hits", m.last_hits ?? 0],
    ["Denies", m.denies ?? 0],
    ["GPM", Math.round(Number(m.gold_per_min) || 0)],
    ["Observer wards", m.obs_placed ?? 0],
    ["Sentry wards", m.sen_placed ?? 0],
    ["Tower damage", m.tower_damage ?? 0],
    ["Towers", m.towers_killed ?? 0],
    ["Roshan", m.roshan_kills ?? 0],
    ["Teamfight", `${Math.round((Number(m.teamfight_participation) || 0) * 100)} %`],
    ["Camps stacked", m.camps_stacked ?? 0],
    ["Runes", m.rune_pickups ?? 0],
    ["First blood", m.firstblood_claimed ? "Yes" : "No"],
    ["Stuns", `${_popupNum(m.stuns)} s`],
    ["Duration", _formatGameDuration(m.duration)],
  ];
}

function _popupDetailsHtml(m) {
  const stats = _popupMatchStats(m).map(([k, v]) =>
    `<div class="history-stat"><dt>${_escHtml(k)}</dt><dd>${_escHtml(v)}</dd></div>`).join("");
  const labels = {};
  for (const s of (_popupPlayer && _popupPlayer.points_sources) || []) labels[s.key] = s.label;
  const parts = Object.entries(m.points_breakdown || {})
    .filter(([key, v]) => Number(v) !== 0 || (key === "mvp_bonus" && m.is_mvp))
    .map(([key, v]) => `<li><span>${_escHtml(labels[key] || _POPUP_SOURCE_LABELS[key] || key)}</span><span class="history-breakdown-pts">${_popupNum(v)}</span></li>`).join("");
  const total = m.excluded_from_scoring
    ? `<li class="history-breakdown-total"><span>Not scored</span><span class="history-breakdown-pts">—</span></li>`
    : `<li class="history-breakdown-total"><span>Fantasy points</span><span class="history-breakdown-pts">${Number(m.fantasy_points).toFixed(1)}</span></li>`;
  return `
    <div class="history-details">
      <dl class="history-stats">${stats}</dl>
      <div class="history-breakdown">
        <h3 class="player-bio-eyebrow">Points by source</h3>
        <ol class="history-breakdown-list">${parts}${total}</ol>
      </div>
    </div>`;
}

// Labels for points_breakdown keys, used when the response's points_sources is absent.
const _POPUP_SOURCE_LABELS = {
  kills: "Kills", assists: "Assists", farm: "Farm", gpm: "GPM", vision: "Vision",
  objectives: "Objectives", teamfight: "Teamfight", stuns: "Stuns",
  jungle_runes: "Jungle and runes", first_blood: "First blood", survival: "Survival",
  mvp_bonus: "MVP bonus",
};

function _popupHistoryRowHtml(m) {
  const id = Number(m.match_id);
  const date = _popupDate(m.start_time);
  const mvpStar = m.is_mvp ? '<span class="history-mvp-star" title="MVP">★</span><span class="visually-hidden">MVP</span>' : '';
  const opponent = m.opponent_team_id ? teamLink(m.opponent_team_id, m.opponent_team_name) : (_escHtml(m.opponent_team_name) || "—");
  const hero = m.hero_icon_url
    ? `<img draggable="false" class="hero-icon" src="${_escHtml(_safeUrl(m.hero_icon_url))}" alt="${_escHtml(m.hero_name || "")}" title="${_escHtml(m.hero_name || "")}" onerror="this.style.display='none'" />`
    : (m.hero_name ? _escHtml(m.hero_name) : "");
  return `<tr class="history-row" id="playerMatchRow-${id}">
          <td class="hc-mvp">${mvpStar}</td>
          <td class="hc-date">${date}</td>
          <td class="hc-hero">${hero}</td>
          <td class="hc-result">${_popupResultText(m)}</td>
          <td class="hc-pts">${_matchPointsCellHtml(m)}</td>
          <td class="hc-kad">${m.kills}/${m.assists}/${m.deaths}</td>
          <td class="hc-gpm">${Math.round(m.gold_per_min)}</td>
          <td class="hc-wards">${m.obs_placed ?? 0}</td>
          <td class="hc-tower">${m.tower_damage ?? 0}</td>
          <td class="hc-opp">${opponent}</td>
          <td class="hc-link"><a class="stream-link" href="https://www.opendota.com/matches/${m.match_id}" target="_blank" rel="noopener noreferrer" aria-label="Match on OpenDota">↗</a></td>
          <td class="hc-details"><button type="button" class="ghost history-details-btn" aria-expanded="false" aria-controls="playerMatchDetails-${id}" onclick="togglePlayerMatchDetails(this)">Details</button></td>
        </tr>
        <tr class="history-details-row" id="playerMatchDetails-${id}" hidden><td colspan="${_POPUP_HISTORY_COLS}">${_popupDetailsHtml(m)}</td></tr>`;
}

function togglePlayerMatchDetails(btn) {
  if (!btn) return;
  const panel = document.getElementById(btn.getAttribute("aria-controls"));
  if (!panel) return;
  const open = btn.getAttribute("aria-expanded") !== "true";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  panel.hidden = !open;
}

// ---- Accolades (issue 50) ----------------------------------------------------

/**
 * Issue 50: the popup's Accolades section. Pips in the header; a "Holo unlocked"
 * banner for past champions; counts; since issue 230 the Played summary line
 * ("Played 7 seasons · S4–S16", the seasons and the live season's matches in a
 * disclosure) and a timeline by season, newest first, each season listing its
 * accolades as detail lines ("S15 Div 1 Champion · with Team").
 */
function renderPlayerAccolades(p) {
  const pipsEl = document.getElementById("playerModalPips");
  const section = document.getElementById("playerModalAccolades");
  const list = p && Array.isArray(p.accolades) ? p.accolades : [];
  // Issue 217: the linked user's tag pips come before the accolade pips.
  const tags = p && p.id != null && typeof playerTags === "function" ? playerTags(p.id) : [];
  const tagPips = typeof tagPipsHtml === "function" ? tagPipsHtml(tags) : "";
  if (pipsEl) pipsEl.innerHTML = tagPips + accoladePipsHtml(list);
  if (!section) return;
  if (!list.length) {
    section.hidden = true;
    section.innerHTML = "";
    if (tagPips) refreshAccoladeIcons();
    return;
  }
  const champions = list.filter(a => a.kind === "champion").length;
  // Issue 233: runner-up and third place show in the timeline, not as season awards.
  const awards = list.filter(a => !ACCOLADE_TEAM_KINDS.includes(a.kind) && a.kind !== "played").length;
  const seasons = accoladePlayedSeasons(list).length;
  const played = accoladePlayedLine(list, { season: p.current_season, matches: p.current_season_matches });
  const bySeason = new Map();
  list.slice().sort(_accoladeNewestFirst).forEach(a => {
    const line = accoladeDetailLine(a);
    if (!line) return;
    if (!bySeason.has(a.season)) bySeason.set(a.season, []);
    bySeason.get(a.season).push(line);
  });
  const timeline = [...bySeason.values()].map(lines => `
      <li class="player-accolades-season"><ul class="card-details-list">${lines.join("")}</ul></li>`).join("");
  const banner = p.holo_unlocked
    ? `<div class="player-accolades-holo"><strong>Holo unlocked.</strong> A past champion: their Legendary cards can be drawn as Holo.</div>`
    : "";
  section.innerHTML = `
    <h2 id="playerAccoladesTitle">Accolades</h2>
    ${banner}
    <div class="player-modal-stat-grid">
      <div class="player-modal-stat"><div class="val">${champions}</div><div class="lbl">Champion titles</div></div>
      <div class="player-modal-stat"><div class="val">${awards}</div><div class="lbl">Season awards</div></div>
      <div class="player-modal-stat"><div class="val">${seasons}</div><div class="lbl">Seasons played</div></div>
    </div>
    ${played ? `<ul class="card-details-list player-accolades-played">${played}</ul>` : ""}
    ${timeline ? `<ol class="player-accolades-timeline">${timeline}</ol>` : ""}`;
  section.hidden = false;
  refreshAccoladeIcons();
}

// ---- Profile facts and bio (unchanged, last) -----------------------------------

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

  // Career heroes moved to the Heroes section (issue 208).
  const heroes = `<div style="margin-top:14px;">
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
