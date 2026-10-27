// Issue #237: the Finals tab. One Div 1 match tree (semi-final 1 and 2 lead into the
// grand final) from GET /finals, pick buttons while predictions are open, and the
// projected, waiting, open, locked and decided states. Team names are always escaped.
// Other users' picks never reach the page: after the lock only the share per team.

let _finalsData = null;
const _finalsPicks = { sf1: null, sf2: null, final: null };
const _FINALS_KEYS = ["sf1", "sf2", "final"];

/** GET /config finals_available shows or hides the tab button. */
function applyFinalsAvailability(available) {
  const btn = document.getElementById("tab-btn-finals");
  if (btn) btn.hidden = !available;
}

async function loadFinals() {
  try {
    const res = await fetch(`${API}/finals`);
    const data = await res.json();
    if (!res.ok) return setStatus("finalsStatus", data.detail || "Could not load the finals", false);
    _finalsData = data;
    const own = data.prediction;
    _FINALS_KEYS.forEach(k => { _finalsPicks[k] = own ? own[`${k}_pick`] : null; });
    renderFinals();
  } catch (e) {
    setStatus("finalsStatus", e.message, false);
  }
}

/** A team of the tree by id (the semis hold all four), or null. */
function _finalsTeam(id) {
  for (const s of (_finalsData && _finalsData.tree) || []) {
    for (const t of s.teams || []) if (t.team_id && t.team_id === id) return t;
  }
  return null;
}

function _finalsNotice(d) {
  if (d.state === "projected") return `${Number(d.played) || 0}/${Number(d.total) || 0} group series played`;
  if (d.state === "waiting_for_tiebreak") return "Seeding waits for a tiebreak decision";
  if (d.state === "set") return d.paused ? "Predictions are paused" : "Predictions close when the first semi-final game starts";
  if (d.state === "locked") return "Predictions closed";
  return "The finals are decided";
}

/** Logo (or monogram) and name; before the bracket is set, the slot and who holds it now. */
function _finalsSlotHtml(t) {
  if (!t) return "";
  if (t.team_id) {
    return `${_teamLogoHtml(t.name, t.logo_url, "team-logo--sm")}<span class="finals-team-name">${_escHtml(t.name)}</span>`;
  }
  let now = "";
  if (t.tie) now = `<span class="finals-team-now">tie: ${(t.tied || []).map(n => _escHtml(n)).join(", ")}</span>`;
  else if (t.now) now = `<span class="finals-team-now">now ${_escHtml(t.now)}</span>`;
  return `<span class="team-logo team-logo--sm team-logo--mono finals-slot-mark" aria-hidden="true">?</span><span class="finals-team-name">${_escHtml(t.slot || "")}</span>${now}`;
}

function _finalsPickButton(key, t) {
  const id = Number(t.team_id);
  const on = _finalsPicks[key] === id;
  return `<button type="button" class="finals-pick" aria-pressed="${on}" onclick="pickFinals('${key}', ${id})">${_finalsSlotHtml(t)}</button>`;
}

/** The grand final offers only the user's two semi-final picks. */
function _finalsPickOptions() {
  const ids = [_finalsPicks.sf1, _finalsPicks.sf2].filter(Boolean);
  if (ids.length < 2) return `<p class="finals-hint">Pick both semi-final winners first</p>`;
  return ids.map(id => _finalsPickButton("final", _finalsTeam(id) || { team_id: id, name: "" })).join("");
}

function _finalsTeamRow(s, t, res) {
  const share = res && t.team_id ? (res.shares.find(x => x.team_id === t.team_id) || { pct: 0 }).pct : null;
  const shareHtml = share === null ? "" : `<span class="finals-share">${Number(share)}%</span>`;
  return `<div class="finals-team">${_finalsSlotHtml(t)}${shareHtml}</div>`;
}

function _finalsWinnerHtml(s) {
  if (!s.winner) return "";
  const t = _finalsTeam(s.winner);
  return `<p class="finals-winner"><span class="finals-winner-label">Winner</span> <span class="mark-winner">${_escHtml(t ? t.name : "")}</span></p>`;
}

function _finalsOwnHtml(key, d) {
  const own = d.prediction;
  const id = d.can_predict ? _finalsPicks[key] : own && own[`${key}_pick`];
  if (!id) return "";
  const t = _finalsTeam(id);
  const mark = !d.can_predict && own && own.marks ? own.marks[key] : null;
  const markHtml = mark === true ? ` <span class="finals-mark finals-mark--right">Correct</span>`
    : mark === false ? ` <span class="finals-mark finals-mark--wrong">Wrong</span>` : "";
  return `<p class="finals-your-pick">Your pick: ${_escHtml(t ? t.name : "")}${markHtml}</p>`;
}

function _finalsMatchHtml(s, d) {
  const key = _FINALS_KEYS.includes(s.key) ? s.key : "";
  const res = d.results && d.results[key];
  let rows;
  if (d.can_predict && key === "final") rows = _finalsPickOptions();
  else if (d.can_predict) rows = (s.teams || []).map(t => (t.team_id ? _finalsPickButton(key, t) : _finalsTeamRow(s, t, null))).join("");
  else rows = (s.teams || []).map(t => _finalsTeamRow(s, t, res)).join("");
  const live = s.live ? `<span class="live-tag">Live</span>` : "";
  const score = Array.isArray(s.score) ? `<span class="finals-score">${Number(s.score[0])}–${Number(s.score[1])}</span>` : "";
  const count = res ? `<p class="finals-count">${Number(res.count)} ${res.count === 1 ? "prediction" : "predictions"}</p>` : "";
  return `<article class="panel finals-match" aria-label="${_escHtml(s.label || "")}">
    <header class="finals-match-head"><span class="finals-match-label">${_escHtml(s.label || "")}</span>${live}${score}</header>
    <div class="finals-teams">${rows}</div>
    ${_finalsWinnerHtml(s)}${_finalsOwnHtml(key, d)}${count}
  </article>`;
}

function _finalsActionsHtml(d) {
  if (d.can_predict) {
    return `<button type="button" id="finalsSaveBtn" onclick="saveFinalsPrediction(this)">Save predictions</button>`;
  }
  if (d.open && !d.logged_in) {
    return `<button type="button" class="secondary" onclick="showLogin()">Log in to predict</button>`;
  }
  if (d.summary) {
    const mine = d.summary.correct === null || d.summary.correct === undefined ? ""
      : `<p class="finals-summary-own">You got ${Number(d.summary.correct)} of 3</p>`;
    const n = Number(d.summary.perfect_count) || 0;
    return `${mine}<p class="finals-summary-all">${n} ${n === 1 ? "user" : "users"} got all three</p>`;
  }
  return "";
}

function renderFinals() {
  const d = _finalsData;
  if (!d || !Array.isArray(d.tree) || d.tree.length < 3) return;
  document.getElementById("finalsNotice").textContent = _finalsNotice(d);
  const [sf1, sf2, fin] = d.tree;
  document.getElementById("finalsTree").innerHTML = `
    <div class="finals-tree">
      <div class="finals-col finals-col--semis">${_finalsMatchHtml(sf1, d)}${_finalsMatchHtml(sf2, d)}</div>
      <svg class="finals-connector" viewBox="0 0 40 100" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="M0 25 H20 V75 H0 M20 50 H40" /></svg>
      <div class="finals-col finals-col--final">${_finalsMatchHtml(fin, d)}</div>
    </div>`;
  document.getElementById("finalsActions").innerHTML = _finalsActionsHtml(d);
}

function pickFinals(key, teamId) {
  if (!_finalsData || !_finalsData.can_predict || !_FINALS_KEYS.includes(key)) return;
  _finalsPicks[key] = teamId;
  if (key !== "final" && ![_finalsPicks.sf1, _finalsPicks.sf2].includes(_finalsPicks.final)) {
    _finalsPicks.final = null;
  }
  setStatus("finalsStatus", "");
  renderFinals();
}

async function saveFinalsPrediction(btn) {
  if (_FINALS_KEYS.some(k => !_finalsPicks[k])) {
    return setStatus("finalsStatus", "Pick a winner for both semi-finals and the grand final", false);
  }
  await withBusy(btn, async () => {
    try {
      const res = await fetch(`${API}/finals/prediction`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sf1_pick: _finalsPicks.sf1, sf2_pick: _finalsPicks.sf2, final_pick: _finalsPicks.final }),
      });
      const data = await res.json();
      if (!res.ok) {
        setStatus("finalsStatus", typeof data.detail === "string" ? data.detail : "Could not save the predictions", false);
        if (res.status === 409) loadFinals();
        return;
      }
      setStatus("finalsStatus", "Predictions saved");
      await loadFinals();
    } catch (e) {
      setStatus("finalsStatus", e.message, false);
    }
  });
}
