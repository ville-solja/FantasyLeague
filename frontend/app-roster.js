let _rosterCards = [];
let _rosterWeekId = null; // null = current week (default)

async function showRosterCard(cardId) {
  let c = _rosterCards.find(x => x.id === cardId);
  if (!c) return;
  // Modifiers may not be cached on locked-week rows — fetch from API if missing
  if (!c.modifiers) {
    try {
      const res = await fetch(`${API}/cards/${cardId}`);
      if (res.ok) { const d = await res.json(); c = {...c, ...d}; }
    } catch (_) {}
  }
  const status = c.is_active !== undefined ? (c.is_active ? "active" : "bench") : "";
  const pts = c.total_points != null ? `${Number(c.total_points).toFixed(1)} wk pts · ` : "";
  showCard(c, `${pts}${status}`);
}

async function loadWeeks() {
  try {
    const res = await fetch(`${API}/weeks`);
    _weeks = await res.json();
    _renderWeekSelector();
  } catch (e) { /* weeks endpoint may not exist on older deploys */ }
}

function _renderWeekSelector() {
  const sel = document.getElementById("rosterWeekSelect");
  if (!sel || !_weeks.length) return;
  const now = Date.now() / 1000;
  const nextWeek = _weeks.find(w => w.start_time > now);
  sel.innerHTML = _weeks.map(w => {
    const isLive   = w.is_locked && w.start_time <= now && w.end_time >= now;
    const isNext   = nextWeek && w.id === nextWeek.id;
    const label = w.is_locked
      ? (isLive ? `${w.label} (live)` : `${w.label} ✓`)
      : (isNext ? `${w.label} (upcoming)` : w.label);
    const isSelected = _rosterWeekId === w.id || (_rosterWeekId === null && isNext);
    return `<option value="${w.id}"${isSelected ? " selected" : ""}>${label}</option>`;
  }).join("");
}

function onRosterWeekChange() {
  const sel = document.getElementById("rosterWeekSelect");
  _rosterWeekId = sel ? parseInt(sel.value) : null;
  loadRoster(_rosterWeekId);
}

async function loadRoster(weekId = null) {
  if (!activeUserId) return;
  try {
    const url = weekId != null
      ? `${API}/roster/${activeUserId}?week_id=${weekId}`
      : `${API}/roster/${activeUserId}`;
    const res = await fetch(url);
    const data = await res.json();
    const { active, bench, combined_value, tokens, season_points, week } = data;
    const isLocked = week?.is_locked ?? false;

    _rosterCards = [...active, ...bench];

    if (tokens !== undefined) updateTokenDisplay(tokens);

    const seasonEl = document.getElementById("rosterSeasonPoints");
    if (seasonEl) seasonEl.textContent = season_points !== undefined ? Number(season_points).toFixed(1) : "—";

    const counter = document.getElementById("drawCounter");
    if (counter) counter.textContent = tokens !== undefined ? `${tokens} ${_tokenName} remaining` : "";

    const weekStatusEl = document.getElementById("rosterWeekStatus");
    if (weekStatusEl && week) {
      if (isLocked) {
        const now = Date.now() / 1000;
        const isLive = week.start_time <= now && week.end_time >= now;
        weekStatusEl.textContent = isLive ? "In progress" : "Locked";
        weekStatusEl.style.color = "#888";
      } else {
        const lockDate = new Date((week.start_time - 1) * 1000);
        const formatted = lockDate.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
        weekStatusEl.textContent = `Locks ${formatted}`;
        weekStatusEl.style.color = "#f0b429";
      }
    }

    const banner = document.getElementById("rosterLockedBanner");
    if (banner) {
      if (isLocked && week) {
        banner.textContent = `Roster locked — ${week.label} snapshot`;
        banner.style.display = "";
      } else {
        banner.style.display = "none";
      }
    }

    const activeGrid = document.getElementById("rosterActiveGrid");
    const emptyCount = Math.max(0, 5 - active.length);
    let activeHTML = active.map(c => _cardSlotHTML(c, isLocked ? null : "bench")).join("");
    activeHTML += Array(emptyCount).fill(`<div class="card-slot-empty">empty slot</div>`).join("");
    activeGrid.innerHTML = activeHTML || `<span style="color:#444;font-size:0.85rem;">No active cards</span>`;

    document.getElementById("rosterCombined").textContent = Number(combined_value).toFixed(1);

    const benchSection = document.getElementById("benchSection");
    const benchGrid = document.getElementById("benchGrid");
    if (!isLocked) {
      benchSection.style.display = "";
      const rosterFull = active.length >= 5;
      if (bench.length) {
        benchGrid.innerHTML = bench.map(c => _cardSlotHTML(c, rosterFull ? null : "activate")).join("");
      } else {
        benchGrid.innerHTML = `<span style="color:#444;font-size:0.85rem;">No cards on bench — draw some!</span>`;
      }
    } else {
      benchSection.style.display = "none";
    }

    const statusEl = document.getElementById("rosterStatus");
    if (statusEl) statusEl.textContent = isLocked ? "" : `${active.length}/5 active`;

  } catch (e) {
    const statusEl = document.getElementById("rosterStatus");
    if (statusEl) { statusEl.textContent = e.message; statusEl.className = "status err"; }
  }
}

/**
 * Build the HTML for a single card slot (image + action button).
 * action: "bench" | "activate" | null (locked/no action)
 */
function _cardSlotHTML(c, action) {
  const imgSrc = cardImageUrl(c.id);
  const pts = Number(c.total_points || 0).toFixed(1);
  let actionBtn = "";
  if (action === "bench") {
    actionBtn = `<button class="secondary" style="font-size:0.7rem;padding:4px 8px;" onclick="deactivateCard(${c.id})">Bench</button>`;
  } else if (action === "activate") {
    actionBtn = `<button class="secondary" style="font-size:0.7rem;padding:4px 8px;" onclick="activateCard(${c.id})">Activate</button>`;
  }
  return `
    <div class="card-slot" data-rarity="${c.card_type}">
      <img class="card-img" src="${imgSrc}" alt="${c.player_name}"
           onclick="showRosterCard(${c.id})"
           onerror="this.outerHTML='<div class=\\'card-img-loading\\'>${c.card_type.toUpperCase()}<br><span style=\\'font-size:0.65rem;margin-top:4px;\\'>${c.player_name}</span></div>'" />
      <div class="card-slot-pts">${pts} pts</div>
      <div class="card-slot-actions">${actionBtn}</div>
    </div>`;
}

async function activateCard(cardId) {
  try {
    const res = await fetch(`${API}/roster/${cardId}/activate`, { method: "POST" });
    const data = await res.json();
    if (res.ok) loadRoster(_rosterWeekId);
    else { const s = document.getElementById("rosterStatus"); if(s){s.textContent=data.detail;s.className="status err";} }
  } catch (e) {
    const s = document.getElementById("rosterStatus"); if(s){s.textContent=e.message;s.className="status err";}
  }
}

async function deactivateCard(cardId) {
  try {
    const res = await fetch(`${API}/roster/${cardId}/deactivate`, { method: "POST" });
    const data = await res.json();
    if (res.ok) loadRoster(_rosterWeekId);
    else { const s = document.getElementById("rosterStatus"); if(s){s.textContent=data.detail;s.className="status err";} }
  } catch (e) {
    const s = document.getElementById("rosterStatus"); if(s){s.textContent=e.message;s.className="status err";}
  }
}

async function redeemCode() {
  const code = document.getElementById("redeemCodeInput").value.trim().toUpperCase();
  if (!code) return setStatus("redeemStatus", "Enter a code", false);
  try {
    const res = await fetch(`${API}/redeem`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code}) });
    const data = await res.json();
    if (!res.ok) return setStatus("redeemStatus", data.detail, false);
    document.getElementById("redeemCodeInput").value = "";
    updateTokenDisplay(data.tokens ?? null);
    setStatus("redeemStatus", `+${data.granted} ${_tokenName}!`);
  } catch (e) {
    setStatus("redeemStatus", e.message, false);
  }
}
