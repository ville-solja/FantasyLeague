async function loadSeasonArchives() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/leaderboard/seasons`);
    const rows = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", rows.detail, false);
    const tbody = document.getElementById("seasonArchivesBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No archived seasons yet</td></tr>";
      return;
    }
    tbody.innerHTML = "";
    rows.forEach(s => {
      const tr = document.createElement("tr");
      const archived = new Date(s.archived_at * 1000).toLocaleString();
      tr.innerHTML = `<td>${_escHtml(s.season_label)}</td><td style="font-size:0.8rem;">${archived}</td><td>${s.user_count}</td>`;
      tbody.appendChild(tr);
    });
  } catch (e) {
    setStatus("seasonLifecycleStatus", e.message, false);
  }
}

// Issue 50: End Season opens a dialog that shows the awards and the Played count and
// asks for the Div 1 and Div 2 winning teams (players pre-ticked, a stand-in can be
// unticked, a player added by OpenDota id), then the typed END SEASON confirmation.
let _endSeasonPreview = null;

/**
 * Team <option>s for a division picker: that division's teams first (from the league
 * of their matches, "Lower" = Div 2), then every other team, since a team can play in
 * both. Shared by the End Season dialog and Mark champions.
 */
function teamOptionsForDivision(teams, division) {
  const inDiv = t => t.division === division || (t.divisions || []).includes(division);
  const opt = t => `<option value="${t.team_id}">${_escHtml(t.team_name)}</option>`;
  const first = teams.filter(inDiv), rest = teams.filter(t => !inDiv(t));
  if (!first.length || !rest.length) return teams.map(opt).join("");
  const label = division === "div2" ? "Div 2" : "Div 1";
  return `<optgroup label="${label}">${first.map(opt).join("")}</optgroup><optgroup label="Other teams">${rest.map(opt).join("")}</optgroup>`;
}
const _endSeasonPicks = { div1: [], div2: [] };   // [{account_id, name, checked}]

const _END_SEASON_AWARDS = [
  { kind: "most_points", name: "Most Points" },
  { kind: "best_average", name: "Best Average" },
  { kind: "best_match", name: "Best Single Match" },
  { kind: "most_mvps", name: "Most MVPs" },
  { kind: "fantasy_winner", name: "Fantasy Winner" },
];

async function endSeason() {
  const typed = document.getElementById("endSeasonLabel").value.trim();
  setStatus("seasonLifecycleStatus", "");
  try {
    const query = typed ? `?season_label=${encodeURIComponent(typed)}` : "";
    const res = await fetch(`${API}/admin/season/accolades-preview${query}`);
    const data = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", data.detail, false);
    _endSeasonPreview = data;
  } catch (e) {
    return setStatus("seasonLifecycleStatus", e.message, false);
  }
  const p = _endSeasonPreview;
  // Prefilled with the live season's label (current_season_label: the monitored leagues'
  // OpenDota names) unless the admin typed one beside the button; editable either way.
  document.getElementById("endSeasonDialogLabel").value = typed || p.season_label || "";
  document.getElementById("endSeasonAwards").innerHTML = _END_SEASON_AWARDS.map(({ kind, name }) => {
    const winners = (p.awards && p.awards[kind]) || [];
    const who = winners.length
      ? winners.map(w => _escHtml(w.player_name || w.username || "")).join(", ")
      : "None";
    // Issue 248: Most MVPs shows a whole count ("3 MVPs"); the others are points.
    const value = !winners.length || winners[0].value == null ? ""
      : (kind === "most_mvps" ? accoladeValueText(kind, winners[0].value) : `${Number(winners[0].value).toFixed(1)}`);
    return `<div class="end-season-award-row"><span>${name}</span><span>${who}</span><span class="end-season-num">${_escHtml(value)}</span></div>`;
  }).join("");
  document.getElementById("endSeasonPlayed").textContent = p.played_count
    ? `Played: ${p.played_count} players with a scored match`
    : "No scored matches: no awards or Played rows will be recorded.";
  ["div1", "div2"].forEach(div => {
    document.getElementById(`endSeasonTeam_${div}`).innerHTML = `<option value="">No champion yet</option>` + teamOptionsForDivision(p.teams || [], div);
    _endSeasonPicks[div] = [];
    _renderEndSeasonPlayers(div);
  });
  _applyEndSeasonRecorded(p.recorded, document.getElementById("endSeasonDialogLabel").value.trim());
  setStatus("endSeasonDialogStatus", "");
  endSeasonPartChanged();
  document.getElementById("endSeasonModal").classList.remove("hidden");
}

// Issue 133: End Season's parts. A part whose accolades the label already has (granted
// by hand, say) starts unticked, so End Season doesn't record near-duplicates.
const _END_SEASON_PARTS = [
  { part: "awards", key: "awards", noun: "awards" },
  { part: "champions", key: "champion", noun: "champion rows" },
  { part: "played", key: "played", noun: "Played rows" },
];

function _applyEndSeasonRecorded(recorded, label) {
  _END_SEASON_PARTS.forEach(({ part, key, noun }) => {
    const n = (recorded && recorded[key]) || 0;
    document.getElementById(`endSeasonPart_${part}`).checked = n === 0;
    document.getElementById(`endSeasonRecorded_${part}`).textContent =
      n ? `${n} ${noun} already recorded for ${label}` : "";
  });
  document.getElementById("endSeasonPart_summary").checked = true;
}

let _endSeasonLabelTimer = null;

/** Re-reads the already-recorded counts for the label being typed (debounced). */
function endSeasonLabelChanged() {
  clearTimeout(_endSeasonLabelTimer);
  _endSeasonLabelTimer = setTimeout(async () => {
    const label = document.getElementById("endSeasonDialogLabel").value.trim();
    if (!label) return;
    try {
      const res = await fetch(`${API}/admin/season/accolades-preview?season_label=${encodeURIComponent(label)}`);
      const data = await res.json();
      if (!res.ok || document.getElementById("endSeasonDialogLabel").value.trim() !== label) return;
      _applyEndSeasonRecorded(data.recorded, label);
      endSeasonPartChanged();
    } catch (e) {
      setStatus("endSeasonDialogStatus", e.message, false);
    }
  }, 400);
}

function _endSeasonParts() {
  const on = part => document.getElementById(`endSeasonPart_${part}`).checked;
  return { record_awards: on("awards"), record_champions: on("champions"),
           record_played: on("played"), store_summary: on("summary") };
}

/** With Record champions off, the champion pickers are hidden and none are sent. */
function endSeasonPartChanged() {
  document.getElementById("endSeasonChampsBlock").hidden = !_endSeasonParts().record_champions;
  _updateEndSeasonWarning();
}

function closeEndSeasonDialog() {
  document.getElementById("endSeasonModal").classList.add("hidden");
}

function _endSeasonTeam(div) {
  const id = parseInt(document.getElementById(`endSeasonTeam_${div}`).value, 10);
  return ((_endSeasonPreview && _endSeasonPreview.teams) || []).find(t => t.team_id === id) || null;
}

/** Picking a team pre-ticks the players who played for it this season. */
function endSeasonPickTeam(div) {
  const team = _endSeasonTeam(div);
  _endSeasonPicks[div] = team ? team.players.map(p => ({ account_id: p.account_id, name: p.name, checked: true })) : [];
  _renderEndSeasonPlayers(div);
  _updateEndSeasonWarning();
}

function _renderEndSeasonPlayers(div) {
  document.getElementById(`endSeasonPlayers_${div}`).innerHTML = _endSeasonPicks[div].map((p, i) => `
    <label class="end-season-player"><input type="checkbox" ${p.checked ? "checked" : ""} onchange="endSeasonTogglePlayer('${div}', ${i}, this.checked)" /> ${_escHtml(p.name)} <span class="accolade-admin-id">${_escHtml(String(p.account_id))}</span></label>`).join("");
}

function endSeasonTogglePlayer(div, i, checked) {
  if (_endSeasonPicks[div][i]) _endSeasonPicks[div][i].checked = checked;
  _updateEndSeasonWarning();
}

function endSeasonAddPlayer(div) {
  const input = document.getElementById(`endSeasonAdd_${div}`);
  const raw = input.value.trim();
  if (!/^\d+$/.test(raw) || Number(raw) <= 0 || !Number.isSafeInteger(Number(raw))) {
    return setStatus("endSeasonDialogStatus", "OpenDota id must be a positive whole number", false);
  }
  const id = Number(raw);
  if (_endSeasonPicks[div].some(p => p.account_id === id)) return;
  let name = `Player ${id}`;
  for (const t of (_endSeasonPreview && _endSeasonPreview.teams) || []) {
    const hit = t.players.find(p => p.account_id === id);
    if (hit) { name = hit.name; break; }
  }
  _endSeasonPicks[div].push({ account_id: id, name, checked: true });
  input.value = "";
  _renderEndSeasonPlayers(div);
  _updateEndSeasonWarning();
}

/** [{division, team_name, player_account_ids}] for the divisions with a team and ticked players. */
function _endSeasonChampions() {
  if (!_endSeasonParts().record_champions) return [];
  return ["div1", "div2"].map(div => {
    const team = _endSeasonTeam(div);
    const ids = _endSeasonPicks[div].filter(p => p.checked).map(p => p.account_id);
    return team && ids.length ? { division: div, team_name: team.team_name, player_account_ids: ids } : null;
  }).filter(Boolean);
}

function _updateEndSeasonWarning() {
  document.getElementById("endSeasonChampWarning").hidden =
    !_endSeasonParts().record_champions || _endSeasonChampions().length > 0;
}

async function confirmEndSeason() {
  const label = document.getElementById("endSeasonDialogLabel").value.trim();
  if (!label) return setStatus("endSeasonDialogStatus", "Enter a season label", false);
  const parts = _endSeasonParts();
  const champions = _endSeasonChampions();
  const champNote = !parts.record_champions || champions.length ? "" : " No champions recorded; add them in Player management.";
  closeEndSeasonDialog();
  const confirmText = await typedConfirm("season_end", `Archive the current standings and record the chosen parts of the season as "${label}".${champNote}`);
  if (confirmText === null) return;
  try {
    const res = await adminFetch(`${API}/admin/season/end`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({season_label: label, champions,
                            record_awards: parts.record_awards, record_champions: parts.record_champions,
                            record_played: parts.record_played, store_summary: parts.store_summary,
                            confirm: confirmText}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", data.detail, false);
    const extra = data.note ? ` ${data.note}.` : (data.warning ? ` ${data.warning}.` : "");
    const summary = data.summary ? `, summary of ${data.summary.players} players and ${data.summary.teams} teams` : "";
    const detail = `${data.archived_users} users, ${data.accolades} accolades, ${data.champions} champions${summary}`;
    setStatus("seasonLifecycleStatus", `Archived "${data.season_label}" (${detail}).${extra}`);
    document.getElementById("endSeasonLabel").value = "";
    loadSeasonArchives();
    if (typeof loadSeasonAccolades === "function") loadSeasonAccolades();
    showEndSeasonResult(data.season_label, `Recorded: ${detail}.${extra}`);
  } catch (e) {
    setStatus("seasonLifecycleStatus", e.message, false);
  }
}

// Issue 133: End Season deletes nothing, so its result leads on to Reset Season.
function endSeasonResultText(label) {
  return `Season ${label} archived. The season's data is still live: continue to Reset Season to start the next season.`;
}

function showEndSeasonResult(label, detail) {
  document.getElementById("endSeasonResultText").textContent = endSeasonResultText(label);
  document.getElementById("endSeasonResultDetail").textContent = detail || "";
  document.getElementById("endSeasonResultModal").classList.remove("hidden");
}

function closeEndSeasonResult() {
  document.getElementById("endSeasonResultModal").classList.add("hidden");
}

function continueToSeasonReset() {
  closeEndSeasonResult();
  openSeasonResetConfirm();
}

const _RESET_TABLE_NAMES = {
  matches: "Matches", player_match_stats: "Player game stats", card_match_points: "Stored card points",
  match_bans: "Hero bans", weeks: "Weeks", weekly_roster_entries: "Weekly roster entries",
  twitch_mvp: "Twitch MVPs", twitch_token_drops: "Twitch token drops", players: "Players (Player Pool)",
  teams: "Teams", cards: "Cards", card_modifiers: "Card modifiers", own_player_card_grants: "Own-card grants",
  weekly_summaries: "Weekly Reports", weekly_summary_reveals: "Weekly Report reveals",
  weekly_summary_seen: "Weekly Report seen marks", live_matches: "Live games", match_timings: "Match timings",
  twitch_presence: "Twitch viewer heartbeats", leagues_unmonitored: "Leagues unmonitored",
  demo_clock_override: "Demo clock override",
  season_archive: "Season standings archive", season_accolades: "Accolades (history)",
  season_player_stats: "Season player summaries", season_team_results: "Season team results",
  audit_logs: "Audit log", user_tags: "User tags", tag_definitions: "Tag definitions",
  finals_brackets: "Finals brackets", finals_predictions: "Finals predictions",
  team_signups: "Team signups", promo_codes: "Promo codes", token_grant_events: "Token grant events",
  notifications: "Notifications", weights: "Scoring weights", player_profiles: "Player profiles",
  twitch_mvp_polls: "Twitch vote polls", twitch_pending_tokens: "Pending vote tokens",
};

function _resetName(key) {
  return _RESET_TABLE_NAMES[key] || key.replace(/_/g, " ");
}

/** The Reset dialog's Deleted and Kept lists from GET /admin/season/reset-preview. */
function seasonResetPreviewLists(p) {
  const del = p.delete || {};
  const deleted = Object.keys(del)
    .filter(k => k !== "users_tokens_reset" && del[k] > 0)
    .map(k => `${_resetName(k)}: ${del[k]}`);
  deleted.push(`${del.users_tokens_reset || 0} users' tokens reset to ${p.initial_tokens}`);
  const keep = p.keep || {};
  const kept = [`User accounts: ${del.users_tokens_reset || 0}`].concat(
    Object.keys(keep).filter(k => keep[k] > 0).map(k => `${_resetName(k)}: ${keep[k]}`));
  kept.push(`Season backup named after "${p.season_label}"`);
  return { deleted, kept };
}

let _seasonResetPreview = null;

/**
 * Issue 133: a season ended before the summary existed (Season 16) has none; Reset
 * would lose its player and team results, so the dialog offers to save it first.
 */
function seasonResetSummaryHtml(p) {
  if (!p || !p.archived) return "";
  const label = _escHtml(p.season_label);
  if (p.has_summary) {
    return `<p>Season summary stored: ${p.summary_players} players, ${p.summary_teams} teams.</p>`;
  }
  return `<p class="end-season-warning">Season ${label} has no stored summary. Save it before resetting, or its player and team results are lost.</p>`
    + `<button type="button" class="secondary" id="seasonResetSaveSummaryBtn" onclick="saveSeasonSummary()">Save season summary</button>`;
}

async function saveSeasonSummary() {
  const label = _seasonResetPreview && _seasonResetPreview.season_label;
  if (!label) return;
  const confirmText = await typedConfirm("season_summary", `Store the player and team summary of "${label}" from the live data.`);
  if (confirmText === null) return;
  const status = document.getElementById("seasonResetModalStatus");
  try {
    const res = await adminFetch(`${API}/admin/season/summary`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({season_label: label, confirm: confirmText}),
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail;
      return;
    }
    status.textContent = `Saved the summary of ${data.season_label}: ${data.players} players, ${data.teams} teams.`;
    await openSeasonResetConfirm(true);
  } catch (e) {
    status.textContent = e.message;
  }
}

function _renderSeasonResetPreview(p) {
  _seasonResetPreview = p;
  document.getElementById("seasonResetSummary").innerHTML = seasonResetSummaryHtml(p);
  const lists = seasonResetPreviewLists(p);
  const li = items => items.map(t => `<li>${_escHtml(t)}</li>`).join("");
  document.getElementById("seasonResetDeleteList").innerHTML = li(lists.deleted);
  document.getElementById("seasonResetKeepList").innerHTML = li(lists.kept);
  const warn = document.getElementById("seasonResetWarning");
  warn.textContent = p.warning || "";
  warn.hidden = !p.warning;
}

async function openSeasonResetConfirm(keepStatus) {
  document.getElementById("seasonResetConfirmInput").value = "";
  if (!keepStatus) document.getElementById("seasonResetModalStatus").textContent = "";
  document.getElementById("seasonResetSummary").innerHTML = "";
  document.getElementById("seasonResetDeleteList").innerHTML = "<li>Loading…</li>";
  document.getElementById("seasonResetKeepList").innerHTML = "<li>Loading…</li>";
  document.getElementById("seasonResetWarning").hidden = true;
  document.getElementById("seasonResetModal").style.display = "flex";
  try {
    const res = await fetch(`${API}/admin/season/reset-preview`);
    const data = await res.json();
    if (!res.ok) {
      document.getElementById("seasonResetModalStatus").textContent = data.detail;
      return;
    }
    _renderSeasonResetPreview(data);
  } catch (e) {
    document.getElementById("seasonResetModalStatus").textContent = e.message;
  }
}

function closeSeasonResetConfirm() {
  document.getElementById("seasonResetModal").style.display = "none";
}

/** The reset's result line: what was deleted, and the season backup's file name. */
function seasonResetResultText(data) {
  const counts = data.counts || {};
  const deleted = Object.keys(counts)
    .filter(k => k !== "users_tokens_reset" && counts[k] > 0)
    .map(k => `${counts[k]} ${_resetName(k).toLowerCase()}`);
  return `Season reset complete. Deleted: ${deleted.length ? deleted.join(", ") : "nothing"}; `
    + `${counts.users_tokens_reset || 0} users' tokens reset to ${data.initial_tokens}. `
    + `Season backup: ${data.backup_file}`;
}

async function confirmSeasonReset() {
  const typed = document.getElementById("seasonResetConfirmInput").value.trim();
  if (typed.toUpperCase() !== ADMIN_CONFIRM_PHRASES.season_reset) {
    document.getElementById("seasonResetModalStatus").textContent = `Type "${ADMIN_CONFIRM_PHRASES.season_reset}" to confirm.`;
    return;
  }
  try {
    const res = await adminFetch(`${API}/admin/season/reset`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({force: false, confirm: typed}),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById("seasonResetModalStatus").textContent = data.detail;
      return;
    }
    closeSeasonResetConfirm();
    setStatus("seasonLifecycleStatus", seasonResetResultText(data));
    loadSeasonArchives();
    loadAdminWeeks();
    loadLeagues();
    if (typeof loadBackups === "function") loadBackups();
  } catch (e) {
    document.getElementById("seasonResetModalStatus").textContent = e.message;
  }
}

// ---------------------------------------------------------------------------
// Issue #237: Season Finals card. Our Div 1 standings with tiebreak notes, the
// bracket state, the lock and its source, each series' result and source, the
// fixtures-site cross-check (informational only), and the admin steps: order a
// shared tie, Pause predictions, Close now and Set result.
// ---------------------------------------------------------------------------

let _adminFinals = null;
let _finalsTieOrder = [];

const _FINALS_STATE_LABELS = {
  projected: "Projected (group series remain)",
  waiting_for_tiebreak: "Waiting for a tiebreak decision",
  set: "Set: predictions open",
  locked: "Locked",
  decided: "Decided",
};
const _FINALS_LOCK_LABELS = {
  live: "first semi game seen live",
  ingested: "first semi game ingested",
  admin: "closed by an admin",
  feed_time: "fixtures feed start time",
};

async function loadAdminFinals() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/finals`);
    const data = await res.json();
    if (!res.ok) return setStatus("adminFinalsStatus", data.detail, false);
    _adminFinals = data;
    _finalsTieOrder = (data.suggestion || (data.tied || []).map(t => t.team_id)).slice();
    renderAdminFinals();
  } catch (e) {
    setStatus("adminFinalsStatus", e.message, false);
  }
}

function _adminFinalsTeamName(id) {
  const row = ((_adminFinals && _adminFinals.standings) || []).find(r => r.team_id === id);
  if (row) return row.name;
  for (const s of (_adminFinals && _adminFinals.bracket && _adminFinals.bracket.series) || []) {
    const t = (s.teams || []).find(x => x.team_id === id);
    if (t) return t.name;
  }
  return `Team ${id}`;
}

function _adminFinalsTieHtml(d) {
  if (!(d.tied || []).length) return "";
  const hint = d.suggestion ? `<p class="admin-panel-note">Ordered as the fixtures site has them (a hint only).</p>` : "";
  const items = _finalsTieOrder.map((id, i) => `
    <li class="finals-tie-item"><span>${i + 1}. ${_escHtml(_adminFinalsTeamName(id))}</span>
      <button type="button" class="secondary" aria-label="Move up" onclick="moveFinalsTie(${i}, -1)" ${i === 0 ? "disabled" : ""}>↑</button>
      <button type="button" class="secondary" aria-label="Move down" onclick="moveFinalsTie(${i}, 1)" ${i === _finalsTieOrder.length - 1 ? "disabled" : ""}>↓</button></li>`).join("");
  return `<h4 class="admin-panel-subtitle">Resolve the tie</h4>${hint}<ol class="finals-tie-list">${items}</ol>
    <button type="button" onclick="saveFinalsTiebreak(this)">Save order and set the bracket</button>`;
}

function _adminFinalsSeriesHtml(b) {
  const rows = (b.series || []).map(s => {
    const teams = (s.teams || []).map(t => _escHtml(t.team_id ? t.name : t.slot || "")).join(" vs ");
    const score = Array.isArray(s.score) ? `${Number(s.score[0])}–${Number(s.score[1])}` : "—";
    const winner = s.winner ? `<span class="mark-winner">${_escHtml(_adminFinalsTeamName(s.winner))}</span>` : "—";
    const options = (s.teams || []).filter(t => t.team_id)
      .map(t => `<option value="${Number(t.team_id)}">${_escHtml(t.name)}</option>`).join("");
    const setter = options
      ? `<select id="finalsResult_${s.key}" aria-label="Winner of ${_escHtml(s.label)}">${options}</select> <button type="button" class="secondary" onclick="setFinalsResult('${s.key}', this)">Set result</button>`
      : "";
    return `<tr><td>${_escHtml(s.label)}</td><td>${teams}</td><td>${score}${s.live ? ' <span class="live-tag">Live</span>' : ""}</td><td>${winner}</td><td>${_escHtml(s.source || "—")}</td><td>${setter}</td></tr>`;
  }).join("");
  return `<div class="admin-table-wrap"><table><thead><tr><th>Series</th><th>Teams</th><th>Score</th><th>Winner</th><th>Source</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderAdminFinals() {
  const d = _adminFinals;
  const el = document.getElementById("adminFinalsBody");
  if (!d || !el) return;
  const b = d.bracket;
  const facts = [`<li>State: <strong>${_escHtml(_FINALS_STATE_LABELS[d.state] || d.state)}</strong></li>`,
                 `<li>${Number(d.played)}/${Number(d.total)} group series played</li>`];
  if (b) {
    const lock = b.locked_at
      ? `${new Date(b.locked_at * 1000).toLocaleString()} (${_escHtml(_FINALS_LOCK_LABELS[b.lock_source] || b.lock_source || "")})`
      : "not yet";
    facts.push(`<li>Seeds: ${b.seed_source === "admin_tiebreak" ? "admin tiebreak" : "standings"}; predictions: ${Number(b.prediction_count)}${b.paused ? " (paused)" : ""}</li>`);
    facts.push(`<li>Locked: ${lock}</li>`);
  }
  const cc = d.cross_check || {};
  const ccText = !cc.reachable ? "Fixtures site not reachable; nothing depends on it."
    : cc.differs ? `Differs: the fixtures site's seeds 1–4 are ${(cc.site_top4 || []).map(n => _escHtml(n)).join(", ")}.`
    : "Matches our seeds 1–4.";
  facts.push(`<li class="${cc.differs ? "finals-cross-check--differs" : ""}">Fixtures-site cross-check: ${ccText}</li>`);
  const table = (d.standings || []).map(r => {
    const seriesPoints = Number(r.points);  // league table points (2/1/0 per series), whole numbers, not fantasy points
    return `<tr><td>${Number(r.rank)}${r.shared ? "=" : ""}</td><td>${_escHtml(r.name)}</td><td>${Number(r.played)}</td><td>${Number(r.series_wins)}–${Number(r.draws)}–${Number(r.losses)}</td><td>${seriesPoints}</td><td>${_escHtml(r.note || "")}</td></tr>`;
  }).join("");
  const actions = b ? `<div class="admin-panel-row">
      <button type="button" class="secondary" onclick="toggleFinalsPause(this)">${b.paused ? "Resume predictions" : "Pause predictions"}</button>
      <button type="button" class="danger" onclick="closeFinalsNow(this)" ${b.locked_at ? "disabled" : ""}>Close now</button></div>` : "";
  el.innerHTML = `<ul class="finals-admin-facts">${facts.join("")}</ul>
    ${_adminFinalsTieHtml(d)}
    ${b ? _adminFinalsSeriesHtml(b) : ""}${actions}
    <details class="finals-admin-standings"><summary>Div 1 standings</summary>
      <div class="admin-table-wrap"><table><thead><tr><th>#</th><th>Team</th><th>P</th><th>W–D–L</th><th>Pts</th><th>Tiebreak</th></tr></thead><tbody>${table}</tbody></table></div>
    </details>`;
}

function moveFinalsTie(i, step) {
  const j = i + step;
  if (j < 0 || j >= _finalsTieOrder.length) return;
  [_finalsTieOrder[i], _finalsTieOrder[j]] = [_finalsTieOrder[j], _finalsTieOrder[i]];
  renderAdminFinals();
}

async function _adminFinalsSend(btn, url, method, body, done) {
  await withBusy(btn, async () => {
    try {
      const opts = { method };
      if (body) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
      const res = await adminFetch(url, opts);
      const data = await res.json();
      if (!res.ok) return setStatus("adminFinalsStatus", typeof data.detail === "string" ? data.detail : "Request failed", false);
      setStatus("adminFinalsStatus", done(data));
      await loadAdminFinals();
    } catch (e) {
      setStatus("adminFinalsStatus", e.message, false);
    }
  });
}

function saveFinalsTiebreak(btn) {
  return _adminFinalsSend(btn, `${API}/admin/finals/tiebreak`, "PUT", { order: _finalsTieOrder },
    () => "Tie resolved; the bracket is set and predictions are open");
}

function toggleFinalsPause(btn) {
  return _adminFinalsSend(btn, `${API}/admin/finals/pause`, "POST", null,
    data => (data.paused ? "Predictions paused" : "Predictions resumed"));
}

function closeFinalsNow(btn) {
  if (!confirm("Close predictions now? Saves after this are not counted.")) return;
  return _adminFinalsSend(btn, `${API}/admin/finals/close`, "POST", null, () => "Predictions closed");
}

function setFinalsResult(series, btn) {
  const sel = document.getElementById(`finalsResult_${series}`);
  const winner = sel ? parseInt(sel.value, 10) : NaN;
  if (!Number.isFinite(winner)) return;
  return _adminFinalsSend(btn, `${API}/admin/finals/result`, "PUT", { series, winner },
    () => "Result set");
}

// ---------------------------------------------------------------------------
// Issue #220: Team signup card. The period's state, Open signup (label and optional
// closing time) or Close now, every listing with Remove, Download CSV and Clear
// signups (re-auth through adminFetch). Every listing field is escaped.
// ---------------------------------------------------------------------------

let _adminTeamSignup = null;

async function loadAdminTeamSignup() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/team-signup`);
    const data = await res.json();
    if (!res.ok) return setStatus("adminTeamSignupStatus", data.detail, false);
    _adminTeamSignup = data;
    renderAdminTeamSignup();
  } catch (e) {
    setStatus("adminTeamSignupStatus", e.message, false);
  }
}

function _adminTsDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : "";
}

function renderAdminTeamSignup() {
  const d = _adminTeamSignup;
  const el = document.getElementById("adminTeamSignupBody");
  if (!d || !el) return;
  const p = d.current;
  let state = "No signup period yet.";
  if (p && p.open) state = `Open: <strong>${_escHtml(p.label)}</strong>, ${p.closes_at ? `closes ${_escHtml(_adminTsDate(p.closes_at))}` : "no closing time"}.`;
  else if (p) state = `Closed: <strong>${_escHtml(p.label)}</strong>, closed ${_escHtml(_adminTsDate(p.closed_at))}.`;
  const controls = d.open
    ? `<div class="admin-panel-row"><button type="button" class="danger" onclick="closeTeamSignupNow(this)">Close now</button></div>`
    : `<div class="admin-panel-row">
        <input type="text" id="teamSignupLabel" maxlength="40" placeholder="Label, e.g. Season 17" aria-label="Signup period label">
        <input type="datetime-local" id="teamSignupClosesAt" aria-label="Closing time (optional)">
        <button type="button" onclick="openTeamSignup(this)">Open signup</button></div>`;
  const rows = (d.listings || []).map(r => `<tr><td>${_escHtml(r.team_name)}</td><td>${_escHtml(r.captain)}</td>
      <td>${_escHtml(r.contact)}</td><td>${Number(r.player_count)}${r.duplicates ? ` <span class="status-badge" title="Players also listed by another team">${Number(r.duplicates)} shared</span>` : ""}</td>
      <td>${r.is_full ? "Full" : "Partial"}</td><td>${_escHtml(_adminTsDate(r.updated_at))}</td>
      <td><button type="button" class="secondary" onclick="removeTeamSignupListing(${Number(r.id)}, this)">Remove</button></td></tr>`).join("");
  const table = rows
    ? `<div class="admin-table-wrap"><table><thead><tr><th>Team</th><th>Captain</th><th>Contact</th><th>Players</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
    : (p ? `<p class="admin-panel-note">No listings in this period.</p>` : "");
  const exportRow = p
    ? `<div class="admin-panel-row">
        <button type="button" class="secondary" onclick="downloadTeamSignupCsv(${Number(p.id)}, this)">Download CSV</button>
        <button type="button" class="danger" onclick="clearTeamSignups(${Number(p.id)}, this)" ${(d.listings || []).length ? "" : "disabled"}>Clear signups</button></div>`
    : "";
  el.innerHTML = `<p class="admin-panel-note">${state}</p>${controls}${table}${exportRow}`;
}

async function _adminTeamSignupSend(btn, url, method, body, done) {
  await withBusy(btn, async () => {
    try {
      const opts = { method };
      if (body) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
      const res = await adminFetch(url, opts);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return setStatus("adminTeamSignupStatus", data.detail || "Request failed", false);
      setStatus("adminTeamSignupStatus", done(data));
      await loadAdminTeamSignup();
    } catch (e) {
      setStatus("adminTeamSignupStatus", e.message, false);
    }
  });
}

function openTeamSignup(btn) {
  const label = document.getElementById("teamSignupLabel").value.trim();
  if (!label) return setStatus("adminTeamSignupStatus", "Give the period a label", false);
  const when = document.getElementById("teamSignupClosesAt").value;
  const closesAt = when ? Math.floor(new Date(when).getTime() / 1000) : null;
  if (when && !Number.isFinite(closesAt)) return setStatus("adminTeamSignupStatus", "Invalid closing time", false);
  return _adminTeamSignupSend(btn, `${API}/admin/team-signup/period`, "POST", { label, closes_at: closesAt },
    () => "Signup opened; the Team Finder tab now shows for everyone");
}

function closeTeamSignupNow(btn) {
  if (!confirm("Close the signup now? The Team Finder tab hides and captains can't save.")) return;
  return _adminTeamSignupSend(btn, `${API}/admin/team-signup/period/close`, "POST", null, () => "Signup closed");
}

function removeTeamSignupListing(id, btn) {
  if (!confirm("Remove this listing with its players and contact?")) return;
  return _adminTeamSignupSend(btn, `${API}/admin/team-signup/${Number(id)}`, "DELETE", null, () => "Listing removed");
}

async function downloadTeamSignupCsv(periodId, btn) {
  await withBusy(btn, async () => {
    try {
      const res = await fetch(`${API}/admin/team-signup/export.csv?period_id=${Number(periodId)}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return setStatus("adminTeamSignupStatus", data.detail || "Download failed", false);
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `team-signups-${Number(periodId)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setStatus("adminTeamSignupStatus", e.message, false);
    }
  });
}

function clearTeamSignups(periodId, btn) {
  if (!confirm("Delete every listing of this period, with players and contacts? This can't be undone.")) return;
  return _adminTeamSignupSend(btn, `${API}/admin/team-signup/clear`, "POST", { period_id: Number(periodId) },
    data => `Deleted ${Number(data.deleted)} listing(s)`);
}
