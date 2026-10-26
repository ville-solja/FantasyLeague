// History tab (issue 50): one panel per season, newest first, with the Div 1 and Div 2
// champion teams (and, since issue 233, the runner-up and third place teams) and the
// season awards as chips, and a hall of fame ranked by titles.
// Served by GET /history/seasons (public, no user ids).

const _HISTORY_AWARDS = [
  { kind: "most_points", unit: "pts" },
  { kind: "best_average", unit: "avg" },
  { kind: "best_match", unit: "pts" },
  { kind: "fantasy_winner", unit: "pts" },
];

// The live season's label: its champions become Holo-eligible only from the next season.
let _historyCurrentSeason = "";

async function loadHistory() {
  const seasonsEl = document.getElementById("historySeasons");
  const fameEl = document.getElementById("historyFame");
  try {
    const res = await fetch(`${API}/history/seasons`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load");
    _historyCurrentSeason = data.current_season || "";
    const seasons = data.seasons || [];
    if (!seasons.length) {
      renderIfChanged(seasonsEl, `<div class="panel history-empty">No season history yet.</div>`);
      renderIfChanged(fameEl, `<p class="history-empty-note">No titles yet.</p>`);
    } else {
      renderIfChanged(seasonsEl, seasons.map(_historySeasonHtml).join(""));
      renderIfChanged(fameEl, _historyFameHtml(data.hall_of_fame || []));
    }
    refreshAccoladeIcons();
    setStatus("historyStatus", "");
  } catch (e) {
    setStatus("historyStatus", e.message, false);
  }
}

function _historyValue(v, unit) {
  return v == null || !Number.isFinite(Number(v)) ? "" : `${Number(v).toFixed(1)} ${unit}`;
}

/** Issue 233: the division's runner-up and third place teams, "" when none is recorded. */
function _historyPlacementsHtml(season, division) {
  const placed = (season.placements && season.placements[division]) || {};
  const rows = ["runner_up", "third_place"].map(kind => {
    const team = placed[kind];
    if (!team) return "";
    const chip = accoladeChipsHtml([{ kind, division, season: season.season_label,
                                      season_short: season.season_short, team_name: team.team_name }]);
    return `<div class="history-placement">${chip}<span class="history-placement-team">${_escHtml(team.team_name || "")}</span></div>`;
  }).join("");
  return rows ? `<div class="history-placements">${rows}</div>` : "";
}

/** `placements`: the division's runner-up and third place markup (issue 233), shown
 * under the champion. */
function _historyChampionHtml(season, division, team, placements = "") {
  const chip = accoladeChipsHtml([{ kind: "champion", division, season: season.season_label,
                                    season_short: season.season_short, team_name: team && team.team_name }]);
  if (!team) {
    return `<div class="history-champion">${chip}<p class="history-champion-none">No champion recorded</p>${placements}</div>`;
  }
  // Holo needs a champion title from a season before the current one.
  const badge = season.season_label === _historyCurrentSeason
    ? statusBadgeHtml("Holo from next season", "Champions of the current season can be drawn as Holo from next season")
    : statusBadgeHtml("Holo", "Past champions' Legendary cards can be drawn as Holo");
  const players = team.players.map(p => `
        <li class="history-champion-player"><span>${_escHtml(p.name)}</span>${badge}</li>`).join("");
  return `<div class="history-champion">${chip}
      <div class="history-champion-team">${_escHtml(team.team_name)}</div>
      <ul class="history-champion-players">${players}</ul>
      ${placements}
    </div>`;
}

function _historyAwardsHtml(season) {
  const rows = _HISTORY_AWARDS.map(({ kind, unit }) => {
    const winners = (season.awards && season.awards[kind]) || [];
    if (!winners.length) return "";
    const chip = accoladeChipsHtml([{ kind, season: season.season_label, season_short: season.season_short }]);
    const names = winners.map(w => _escHtml(w.player_name || w.username || "")).join(", ");
    const value = _historyValue(winners[0].value, unit);
    return `<div class="history-award-row">${chip}<span class="history-award-name">${names}</span><span class="history-award-value">${_escHtml(value)}</span></div>`;
  }).join("");
  return rows || `<p class="history-champion-none">No awards recorded</p>`;
}

function _historySeasonHtml(season) {
  const champs = season.champions || {};
  const played = season.played_count
    ? `<p class="history-played">${season.played_count} players played</p>` : "";
  return `<section class="panel history-season">
    <h2>${_escHtml(season.season_label)}</h2>
    <div class="history-champions">
      ${_historyChampionHtml(season, "div1", champs.div1, _historyPlacementsHtml(season, "div1"))}
      ${_historyChampionHtml(season, "div2", champs.div2, _historyPlacementsHtml(season, "div2"))}
    </div>
    <h3 class="history-sub">Awards</h3>
    <div class="history-awards">${_historyAwardsHtml(season)}</div>
    ${played}
  </section>`;
}

function _historyFameHtml(fame) {
  if (!fame.length) return `<p class="history-empty-note">No titles yet.</p>`;
  return fame.map((f, i) => `
    <div class="history-fame-row">
      <span class="history-fame-rank">${i + 1}</span>
      <span class="history-fame-name">${_escHtml(f.player_name)}</span>
      <span class="history-fame-pips">${accoladePipsHtml(f.accolades, { omitPlayed: true })}</span>
      <span class="history-fame-count" title="Titles">${f.titles}</span>
    </div>`).join("");
}
