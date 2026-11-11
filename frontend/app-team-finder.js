// Issue #220: the Team Finder tab. Partial teams as a card grid in the server's daily
// shuffle order (GET /team-signup), filters that narrow it in the browser, a collapsed
// Full teams section, and the captain's listing form (PUT / DELETE /team-signup/mine)
// with a batched id lookup. Every user-written string goes through _escHtml.

let _tfData = null;
let _tfSignupOpen = false;
const _tfFilter = { roles: new Set() };
const _tfForm = { rows: [], roles: new Set(), full: false, closed: false };
let _tfLookupTimer = null;

const _TF_ROLES = [[1, "Carry"], [2, "Mid"], [3, "Offlane"], [4, "Soft support"], [5, "Hard support"]];
const _TF_MAX_PLAYERS = 7;
const _TF_TEAM_SIZE = 5;
const _TF_STEAM64_OFFSET = 76561197960265728n;
const _TF_MAX_ACCOUNT_ID = 4294967295n;

/** GET /config team_signup_open shows the tab button; admins see it at any time. Called
 *  without an argument (after login or logout) it keeps the last /config answer. */
function applyTeamFinderAvailability(open) {
  if (typeof open === "boolean") _tfSignupOpen = open;
  const btn = document.getElementById("tab-btn-teamfinder");
  if (btn) btn.hidden = !(_tfSignupOpen || activeIsAdmin);
}

async function loadTeamFinder() {
  _tfInitControls();
  try {
    const res = await fetch(`${API}/team-signup`);
    const data = await res.json();
    if (!res.ok) return setStatus("tfStatus", data.detail || "Could not load the Team Finder", false);
    _tfData = data;
    _tfFillForm(data);
    renderTeamFinder();
  } catch (e) {
    setStatus("tfStatus", e.message, false);
  }
}

/** The role and medal filter controls and the form's role chips: built once from constants. */
function _tfInitControls() {
  const roleFilter = document.getElementById("tfRoleFilter");
  if (!roleFilter || roleFilter.dataset.ready) return;
  roleFilter.dataset.ready = "1";
  roleFilter.innerHTML = _TF_ROLES.map(([n, name]) =>
    `<button type="button" class="tf-chip" data-role="${n}" aria-pressed="false" title="${name}">Pos ${n}</button>`).join("");
  roleFilter.addEventListener("click", e => {
    const b = e.target.closest("[data-role]");
    if (!b) return;
    const r = Number(b.dataset.role);
    if (_tfFilter.roles.has(r)) _tfFilter.roles.delete(r); else _tfFilter.roles.add(r);
    b.setAttribute("aria-pressed", String(_tfFilter.roles.has(r)));
    renderTeamFinder();
  });
  const medals = Object.values(_RANK_MEDALS);
  ["tfMedalMin", "tfMedalMax"].forEach((id, i) => {
    document.getElementById(id).innerHTML = medals.map((m, j) =>
      `<option value="${j + 1}"${(i ? j + 1 === medals.length : j === 0) ? " selected" : ""}>${m}</option>`).join("");
  });
  const formRoles = document.getElementById("tfFormRoles");
  formRoles.innerHTML = _TF_ROLES.map(([n, name]) =>
    `<button type="button" class="tf-chip" data-role="${n}" aria-pressed="false">Pos ${n} · ${name}</button>`).join("");
  formRoles.addEventListener("click", e => {
    const b = e.target.closest("[data-role]");
    if (!b || _tfForm.closed) return;
    const r = Number(b.dataset.role);
    if (_tfForm.roles.has(r)) _tfForm.roles.delete(r); else _tfForm.roles.add(r);
    b.setAttribute("aria-pressed", String(_tfForm.roles.has(r)));
  });
  document.getElementById("tfIdInput").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); teamFinderAddIds(); }
  });
}

// ---------------------------------------------------------------------------
// Browsing
// ---------------------------------------------------------------------------

function _tfDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString() : "";
}

function _tfMedalHtml(p) {
  return rankMedalHtml(p.rank_tier, p.leaderboard_rank) || `<span class="tf-unranked">Unranked</span>`;
}

function _tfRoleTags(roles) {
  if (!(roles || []).length) return `<span class="tf-muted">No open roles listed</span>`;
  return roles.map(r => {
    const role = _TF_ROLES[Number(r) - 1];
    return role ? `<span class="tf-role-tag" title="Position ${role[0]}: ${role[1]}">Pos ${role[0]} · ${role[1]}</span>` : "";
  }).join("");
}

function _tfContactHtml(t) {
  if (!_tfData || !_tfData.logged_in) return `<span class="tf-contact tf-muted">Log in to see contact details</span>`;
  return `<span class="tf-contact">${_escHtml(t.contact)}</span>`;
}

/** One row per player and one per open slot up to five: name, medal, badges. Every cell is
 *  emitted so the columns line up across cards. */
function _tfPlayerRowsHtml(t, withActions = true) {
  const players = t.players || [];
  const rows = [];
  for (const p of players) {
    const name = p.name
      ? `${_escHtml(p.name)}`
      : `<span class="tf-id">${Number(p.account_id)}</span>${statusBadgeHtml("Unknown player", "Not found in the player pool or on OpenDota")}`;
    const you = p.is_you ? statusBadgeHtml("(You)") : "";
    const flags = [p.verified
      ? statusBadgeHtml("Verified", "The captain's own Steam-verified player")
      : statusBadgeHtml("Listed by captain", "Typed in by the captain; not confirmed by the player")];
    if (p.also_listed) flags.push(`<span class="status-badge tf-badge-warn" title="This player is on more than one listing">Also listed by another team</span>`);
    if (withActions && p.is_you && !t.is_mine) {
      flags.push(`<button type="button" class="ghost tf-small" title="Remove yourself from this listing" onclick="teamFinderNotOnTeam(${Number(t.id)}, this)">Not on this team</button>`);
    }
    rows.push(`<div class="tf-p-name">${name}${you}</div>`, `<div class="tf-p-medal">${_tfMedalHtml(p)}</div>`,
              `<div class="tf-p-flags">${flags.join("")}</div>`);
  }
  for (let i = players.length; i < _TF_TEAM_SIZE; i++) {
    rows.push(`<div class="tf-p-name tf-p-open">Open slot</div>`, `<div class="tf-p-medal"></div>`, `<div class="tf-p-flags"></div>`);
  }
  return `<div class="tf-players">${rows.join("")}</div>`;
}

function _tfCardHtml(t) {
  const n = Number(t.players_needed) || 0;
  const mine = t.is_mine ? statusBadgeHtml("Your team") : "";
  const note = t.note ? `<p class="tf-note">${_escHtml(t.note)}</p>` : "";
  return `<article class="panel tf-card${t.is_mine ? " row-self" : ""}">
    <div class="tf-card-head">
      <div><h3 class="tf-team-name">${_escHtml(t.team_name)}${mine}</h3>
        <div class="tf-muted">${Number(t.player_count)} listed · updated ${_tfDate(t.updated_at)}</div></div>
      <div class="tf-need"><div class="tf-needed${n ? "" : " tf-needed--zero"}">${n}</div><div class="tf-label">needed</div></div>
    </div>
    <div class="tf-chips">${_tfRoleTags(t.open_roles)}</div>
    ${_tfPlayerRowsHtml(t)}
    ${note}
    <div class="tf-card-foot"><span class="tf-label">Contact</span>${_tfContactHtml(t)}</div>
  </article>`;
}

function _tfFullCardHtml(t) {
  return `<article class="panel tf-card tf-card--full${t.is_mine ? " row-self" : ""}">
    <h3 class="tf-team-name tf-team-name--sm">${_escHtml(t.team_name)}</h3>
    <div class="tf-muted">${Number(t.player_count)} players · full since ${_tfDate(t.updated_at)}</div>
    ${_tfPlayerRowsHtml(t)}
    <div class="tf-card-foot"><span class="tf-label">Contact</span>${_tfContactHtml(t)}</div>
  </article>`;
}

/** A team's average medal (1-8), or null when no player has a medal. */
function _tfAvgMedal(t) {
  const tiers = (t.players || []).map(p => Number(p.rank_tier)).filter(x => Number.isInteger(x) && x >= 10);
  if (!tiers.length) return null;
  return Math.min(8, Math.max(1, Math.round(tiers.reduce((a, b) => a + b, 0) / tiers.length / 10)));
}

function _tfFiltered(teams) {
  const needed = Number(document.getElementById("tfNeeded").value) || 0;
  const lo = Number(document.getElementById("tfMedalMin").value) || 1;
  const hi = Number(document.getElementById("tfMedalMax").value) || 8;
  return teams.filter(t => {
    if ((Number(t.players_needed) || 0) < needed) return false;
    if (_tfFilter.roles.size && !(t.open_roles || []).some(r => _tfFilter.roles.has(r))) return false;
    const m = _tfAvgMedal(t);
    return m === null || (m >= lo && m <= hi);
  });
}

function renderTeamFinder() {
  const d = _tfData;
  if (!d) return;
  const p = d.period;
  document.getElementById("tfPeriodLabel").textContent = p ? p.label + " signup" : "Team signup";
  const meta = document.getElementById("tfPeriodMeta");
  meta.textContent = d.open ? (p.closes_at ? `Closes ${_tfDate(p.closes_at)}` : "Open") : "";
  const cta = document.getElementById("tfCta");
  if (!d.open) cta.innerHTML = "";
  else if (!d.logged_in) cta.innerHTML = `<button type="button" class="ghost" onclick="showLogin()">Log in to list your team</button>`;
  else cta.innerHTML = `<button type="button" class="ghost" onclick="teamFinderFocusForm()">${d.mine ? "Edit your listing" : "List your team"}</button>`;

  const notice = document.getElementById("tfNotice");
  notice.hidden = d.open;
  notice.textContent = d.open ? "" : (activeIsAdmin
    ? "Signup is closed. Open a period in Admin › Settings › Season › Team signup."
    : "Signup is closed.");
  document.getElementById("tfFilters").hidden = !d.open;

  const list = _tfFiltered(d.teams || []);
  document.getElementById("tfResultCount").textContent = `${list.length} partial team${list.length === 1 ? "" : "s"}`;
  const listEl = document.getElementById("tfList");
  if (!d.open) listEl.innerHTML = "";
  else if (!(d.teams || []).length) listEl.innerHTML = `<div class="tf-empty">No partial teams listed yet.</div>`;
  else if (!list.length) listEl.innerHTML = `<div class="tf-empty">No partial teams match these filters.</div>`;
  else listEl.innerHTML = `<div class="tf-grid">${list.map(_tfCardHtml).join("")}</div>`;

  const full = d.full_teams || [];
  document.getElementById("tfFullSection").hidden = !full.length;
  document.getElementById("tfFullLabel").textContent = `Full teams (${full.length})`;
  document.getElementById("tfFullList").innerHTML = full.map(_tfFullCardHtml).join("");

  document.getElementById("tfForm").hidden = !d.can_list;
  _tfRenderForm();
}

async function teamFinderNotOnTeam(signupId, btn) {
  if (!confirm("Remove yourself from this team's listing? The captain can list you again.")) return;
  await withBusy(btn, async () => {
    try {
      const res = await fetch(`${API}/team-signup/${Number(signupId)}/not-on-team`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return setStatus("tfStatus", typeof data.detail === "string" ? data.detail : "Could not remove you", false);
      setStatus("tfStatus", "You were removed from that listing");
      await loadTeamFinder();
    } catch (e) {
      setStatus("tfStatus", e.message, false);
    }
  });
}

// ---------------------------------------------------------------------------
// Captain form: create, update, delete
// ---------------------------------------------------------------------------

function teamFinderFocusForm() {
  const form = document.getElementById("tfForm");
  if (!form || form.hidden) return;
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  document.getElementById("tfName").focus({ preventScroll: true });
}

function _tfCount(inputId, countId) {
  document.getElementById(countId).textContent = document.getElementById(inputId).value.length;
}

/** The form from the server: the own listing, else an empty form with the captain's
 *  Steam-verified player first. */
function _tfFillForm(d) {
  const mine = d.mine;
  _tfForm.closed = false;
  _tfForm.rows = [];
  const own = d.own_player;
  if (mine) {
    _tfForm.rows = (mine.players || []).map(p => ({ ...p, state: p.name ? "found" : "unknown" }));
  } else if (own) {
    _tfForm.rows = [{ ...own, verified: true, state: own.name ? "found" : "looking" }];
  }
  _tfForm.roles = new Set(mine ? mine.open_roles : []);
  _tfForm.full = !!(mine && mine.is_full);
  document.getElementById("tfName").value = mine ? mine.team_name : "";
  document.getElementById("tfNote").value = mine ? mine.note : "";
  document.getElementById("tfContact").value = mine ? (mine.contact || "") : "";
  document.getElementById("tfIdInput").value = "";
  document.getElementById("tfIdErr").textContent = "";
  document.getElementById("tfFormTitle").textContent = mine ? "Edit your listing" : "List your team";
  document.getElementById("tfDelete").hidden = !mine;
  _tfCount("tfName", "tfNameCount");
  _tfCount("tfNote", "tfNoteCount");
  if (_tfForm.rows.some(r => r.state === "looking")) _tfLookupSoon();
}

function _tfRenderForm() {
  const rows = [];
  _tfForm.rows.forEach((r, i) => {
    const id = `<span class="tf-id">${Number(r.account_id)}</span>`;
    const from = r.converted ? ` <span class="tf-muted">from Steam64</span>` : "";
    let name, medal;
    if (r.state === "looking") {
      name = `<span class="tf-spinner" aria-hidden="true"></span>${id}`;
      medal = `<span class="tf-muted">Looking up</span>`;
    } else if (r.state === "unknown" || !r.name) {
      name = `${id}${from}`;
      medal = statusBadgeHtml("Unknown player", "Not found in the player pool or on OpenDota; it is still saved");
    } else {
      name = `${_escHtml(r.name)} ${id}${from}`;
      medal = _tfMedalHtml(r);
    }
    const flag = r.verified ? statusBadgeHtml("Verified") : statusBadgeHtml("Listed by captain");
    const action = r.verified
      ? `<span class="tf-muted" title="Your own player stays on your listing">You</span>`
      : `<button type="button" class="ghost tf-small" aria-label="Remove ${Number(r.account_id)}" onclick="teamFinderRemoveRow(${i})"${_tfForm.closed ? " disabled" : ""}>Remove</button>`;
    rows.push(`<div>${name}</div>`, `<div>${medal}</div>`, `<div>${flag}</div>`, `<div>${action}</div>`);
  });
  document.getElementById("tfIdRows").innerHTML = rows.join("");
  document.getElementById("tfIdCount").textContent = _tfForm.rows.length;
  document.querySelectorAll("#tfFormRoles [data-role]").forEach(b =>
    b.setAttribute("aria-pressed", String(_tfForm.roles.has(Number(b.dataset.role)))));
  const fullBtn = document.getElementById("tfFull");
  fullBtn.setAttribute("aria-pressed", String(_tfForm.full));
  document.getElementById("tfFullHelp").textContent = _tfForm.full
    ? "Shown under Full teams; still in the organiser's export."
    : "Partial teams are listed; full teams move to Full teams.";
  document.querySelectorAll("#tfForm input, #tfForm button").forEach(el => { el.disabled = _tfForm.closed; });
}

/** A typed id as a 32-bit Dota id (a Steam64 id is converted), or an error message. */
function _tfParseId(raw) {
  if (!/^\d{1,19}$/.test(raw)) return { error: "Dota ids are digits only" };
  let id = BigInt(raw);
  let converted = false;
  if (id > _TF_STEAM64_OFFSET && id <= _TF_STEAM64_OFFSET + _TF_MAX_ACCOUNT_ID) {
    id -= _TF_STEAM64_OFFSET;
    converted = true;
  }
  if (id < 1n || id > _TF_MAX_ACCOUNT_ID) return { error: "Not a Dota id or a Steam64 id" };
  return { id: Number(id), converted };
}

function teamFinderAddIds() {
  const input = document.getElementById("tfIdInput");
  const err = document.getElementById("tfIdErr");
  err.textContent = "";
  const parts = input.value.split(/[\s,]+/).filter(Boolean);
  if (!parts.length) return;
  for (const raw of parts) {
    const parsed = _tfParseId(raw);
    if (parsed.error) { err.textContent = parsed.error; break; }
    if (_tfForm.rows.some(r => r.account_id === parsed.id)) { err.textContent = "Already on your team"; break; }
    if (_tfForm.rows.length >= _TF_MAX_PLAYERS) { err.textContent = "Seven players at most"; break; }
    _tfForm.rows.push({ account_id: parsed.id, converted: parsed.converted, verified: false, state: "looking" });
  }
  input.value = err.textContent ? input.value : "";
  _tfRenderForm();
  _tfLookupSoon();
}

function teamFinderRemoveRow(i) {
  if (_tfForm.closed || !_tfForm.rows[i] || _tfForm.rows[i].verified) return;
  _tfForm.rows.splice(i, 1);
  _tfRenderForm();
}

/** Debounced and batched: one GET /team-signup/lookup for every row still looking up. */
function _tfLookupSoon() {
  clearTimeout(_tfLookupTimer);
  _tfLookupTimer = setTimeout(_tfLookupNow, 400);
}

async function _tfLookupNow() {
  const pending = _tfForm.rows.filter(r => r.state === "looking");
  if (!pending.length) return;
  const ids = pending.map(r => r.account_id).join(",");
  let found = [];
  try {
    const res = await fetch(`${API}/team-signup/lookup?ids=${encodeURIComponent(ids)}`);
    if (res.ok) found = await res.json();
  } catch (_) { /* shown as Unknown player; the save still works */ }
  const byId = new Map(found.map(f => [Number(f.account_id), f]));
  for (const r of pending) {
    const f = byId.get(r.account_id);
    if (f && f.name) Object.assign(r, { name: f.name, rank_tier: f.rank_tier, leaderboard_rank: f.leaderboard_rank, state: "found" });
    else r.state = "unknown";
  }
  _tfRenderForm();
}

function toggleTeamFinderFull() {
  if (_tfForm.closed) return;
  _tfForm.full = !_tfForm.full;
  _tfRenderForm();
}

/** 409 mid-edit: the period closed meanwhile, so the form turns read-only. */
function _tfSetClosed() {
  _tfForm.closed = true;
  _tfRenderForm();
  setStatus("tfFormStatus", "Signup closed", false);
}

async function saveTeamFinderListing(btn) {
  if (_tfForm.closed) return;
  const body = {
    team_name: document.getElementById("tfName").value.trim(),
    players: _tfForm.rows.filter(r => !r.verified).map(r => r.account_id),
    open_roles: [..._tfForm.roles].sort(),
    note: document.getElementById("tfNote").value.trim(),
    contact: document.getElementById("tfContact").value.trim(),
    is_full: _tfForm.full,
  };
  if (body.team_name.length < 2) return setStatus("tfFormStatus", "Team name needs at least 2 characters", false);
  if (!body.contact) return setStatus("tfFormStatus", "Add a way to contact you", false);
  if (!_tfForm.rows.length) return setStatus("tfFormStatus", "Add at least one player", false);
  await withBusy(btn, async () => {
    try {
      const res = await fetch(`${API}/team-signup/mine`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) return _tfSetClosed();
      if (res.status === 429) return setStatus("tfFormStatus", "Too many saves. Wait a minute and save again.", false);
      if (!res.ok) return setStatus("tfFormStatus", data.detail || "Could not save", false);
      await loadTeamFinder();
      setStatus("tfFormStatus", body.is_full ? "Saved. Your team is under Full teams." : "Saved");
    } catch (e) {
      setStatus("tfFormStatus", e.message, false);
    }
  });
}

async function deleteTeamFinderListing(btn) {
  if (_tfForm.closed || !confirm("Delete your listing? Its players and contact are removed at once.")) return;
  await withBusy(btn, async () => {
    try {
      const res = await fetch(`${API}/team-signup/mine`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) return _tfSetClosed();
      if (!res.ok) return setStatus("tfFormStatus", data.detail || "Could not delete", false);
      await loadTeamFinder();
      setStatus("tfFormStatus", "Listing deleted. You can list again while signup is open.");
    } catch (e) {
      setStatus("tfFormStatus", e.message, false);
    }
  });
}
