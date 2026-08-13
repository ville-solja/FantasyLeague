let _rosterCards = [];
let _rosterWeekId = null; // null = current week (default)
let _rosterLocked = false; // true when week is locked — drag disabled
let _dragState = null;    // { cardId, zone } while a drag is in flight

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
    _rosterLocked = isLocked;

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
    // Render 5 fixed positions by slot_index so gaps are preserved (e.g. card at slot 4 with slot 3 empty)
    const ROSTER_SLOTS = 5;
    const slotMap = new Map();
    const unplacedCards = [];
    active.forEach(card => {
      const si = card.slot_index;
      if (si != null && si >= 0 && si < ROSTER_SLOTS && !slotMap.has(si)) {
        slotMap.set(si, card);
      } else {
        unplacedCards.push(card);
      }
    });
    let upIdx = 0;
    const slots = Array.from({length: ROSTER_SLOTS}, (_, i) => {
      if (slotMap.has(i)) return slotMap.get(i);
      if (upIdx < unplacedCards.length) return unplacedCards[upIdx++];
      return null;
    });
    let activeHTML = slots.map((card, i) =>
      card
        ? _cardSlotHTML(card, isLocked ? null : "bench")
        : `<div class="card-slot-empty" data-zone="active" data-slot-index="${i}">empty slot</div>`
    ).join("");
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

    // Item 5 — settle animation on every render
    requestAnimationFrame(() => {
      document.querySelectorAll(".card-slot, .card-slot-empty").forEach(el => {
        el.classList.remove("reorder-animate");
        void el.offsetWidth; // force reflow so re-adding the class restarts the animation
        el.classList.add("reorder-animate");
      });
    });

    if (!isLocked) _initDragAndDrop(active, bench);

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
  const zone = action === "bench" ? "active" : "bench";
  const isActiveCard = action === "bench";
  return `
    <div class="card-slot" data-rarity="${c.card_type}" data-card-id="${c.id}" data-zone="${zone}">
      <img class="card-img" src="${imgSrc}" alt="${c.player_name}"
           draggable="false" tabindex="0" role="button"
           onclick="if(!window._rosterDragging)showRosterCard(${c.id})"
           onkeydown="if((event.key==='Enter'||event.key===' ')&&!window._rosterDragging&&!_rosterLocked){event.preventDefault();toggleCardZone(${c.id},${isActiveCard})}"
           onerror="this.outerHTML='<div class=\\'card-img-loading\\'>${c.card_type.toUpperCase()}<br><span style=\\'font-size:0.65rem;margin-top:4px;\\'>${c.player_name}</span></div>'" />
      <div class="card-slot-pts">${pts} pts</div>
    </div>`;
}

/** Keyboard fallback for the removed Bench/Activate buttons: Enter/Space on a
 * focused card image toggles it between active and bench, reusing the
 * existing activate/deactivate machinery (and its error handling). */
async function toggleCardZone(cardId, isActiveCard) {
  if (isActiveCard) {
    await deactivateCard(cardId);
  } else {
    await activateCard(cardId);
  }
}


// ---------------------------------------------------------------------------
// Drag-and-drop implementation
// ---------------------------------------------------------------------------

/**
 * Wire up HTML5 drag-and-drop on all rendered card slots.
 * Must be called after loadRoster() has populated the DOM.
 *
 * Four drop scenarios handled:
 *   active → active   : in-zone reorder  → POST /roster/reorder
 *   bench  → bench    : in-zone reorder  → POST /roster/reorder
 *   bench  → active   : swap             → POST /roster/swap
 *   active → bench    : deactivate + reorder
 */
function _initDragAndDrop(activeCards, benchCards) {
  const activeGrid = document.getElementById("rosterActiveGrid");
  const benchGrid  = document.getElementById("benchGrid");
  if (!activeGrid || !benchGrid) return;

  const cardSlots = document.querySelectorAll(".card-slot[data-card-id]");

  cardSlots.forEach(slot => {
    slot.setAttribute("draggable", "true");

    slot.addEventListener("dragstart", e => {
      const cardId = parseInt(slot.dataset.cardId);
      const zone   = slot.dataset.zone;
      _dragState = { cardId, zone };
      e.dataTransfer.setData("application/json", JSON.stringify({ cardId, zone }));
      e.dataTransfer.effectAllowed = "move";
      // Item 6 — grabbing cursor on body
      document.body.classList.add("roster-dragging");
      // Item 3 — highlight all valid drop targets immediately
      document.getElementById("rosterActiveGrid").classList.add("drop-targets-active");
      document.getElementById("benchGrid").classList.add("drop-targets-active");
      // Item 2 — dim source slot after browser takes drag-image snapshot
      requestAnimationFrame(() => slot.classList.add("drag-placeholder"));
      window._rosterDragging = true;
    });

    slot.addEventListener("dragend", () => {
      _dragState = null;
      slot.classList.remove("drag-placeholder");
      document.body.classList.remove("roster-dragging");
      document.getElementById("rosterActiveGrid").classList.remove("drop-targets-active");
      document.getElementById("benchGrid").classList.remove("drop-targets-active");
      // Brief timeout so the onclick suppression outlasts the synthetic click
      setTimeout(() => { window._rosterDragging = false; }, 50);
    });

    slot.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      // Item 4 — swap indicator when bench card hovers a populated active slot
      if (_dragState?.zone === "bench" && slot.dataset.zone === "active") {
        slot.classList.remove("drag-over");
        slot.classList.add("drag-swap-target");
      } else {
        slot.classList.remove("drag-swap-target");
        slot.classList.add("drag-over");
      }
    });

    slot.addEventListener("dragleave", () => {
      slot.classList.remove("drag-over", "drag-swap-target");
    });

    slot.addEventListener("drop", async e => {
      e.preventDefault();
      slot.classList.remove("drag-over", "drag-swap-target");

      let payload;
      try { payload = JSON.parse(e.dataTransfer.getData("application/json")); }
      catch (_) { return; }

      const { cardId: draggedId, zone: draggedZone } = payload;
      const safeId     = parseInt(draggedId, 10);
      if (!Number.isFinite(safeId)) return;
      const targetId   = parseInt(slot.dataset.cardId);
      const targetZone = slot.dataset.zone;

      if (safeId === targetId) return;

      // Case 1 — active → active : in-zone reorder
      if (draggedZone === "active" && targetZone === "active") {
        const ids = activeCards.map(c => c.id);
        const fromIdx = ids.indexOf(safeId);
        const toIdx   = ids.indexOf(targetId);
        if (fromIdx === -1 || toIdx === -1) return;
        ids.splice(fromIdx, 1);
        ids.splice(toIdx, 0, safeId);
        await _apiReorder(ids);
      }

      // Case 2 — bench → bench : in-zone reorder
      else if (draggedZone === "bench" && targetZone === "bench") {
        const ids = benchCards.map(c => c.id);
        const fromIdx = ids.indexOf(safeId);
        const toIdx   = ids.indexOf(targetId);
        if (fromIdx === -1 || toIdx === -1) return;
        ids.splice(fromIdx, 1);
        ids.splice(toIdx, 0, safeId);
        await _apiReorder(ids);
      }

      // Case 3 — bench → active : swap
      else if (draggedZone === "bench" && targetZone === "active") {
        const targetCard = activeCards.find(c => c.id === targetId);
        const slotIdx = targetCard?.slot_index ?? activeCards.indexOf(targetCard);
        const res = await fetch(`${API}/roster/swap`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            bench_card_id: safeId,
            active_card_id: targetId,
            slot_index: slotIdx,
          }),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          const s = document.getElementById("rosterStatus");
          if (s) { s.textContent = d.detail || "Swap failed"; s.className = "status err"; }
          return;
        }
      }

      // Case 4 — active → bench : deactivate then reorder
      else if (draggedZone === "active" && targetZone === "bench") {
        const res = await fetch(`${API}/roster/${safeId}/deactivate`, { method: "POST" });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          const s = document.getElementById("rosterStatus");
          if (s) { s.textContent = d.detail || "Deactivate failed"; s.className = "status err"; }
          return;
        }
        // Place at front of bench
        const benchIds = [safeId, ...benchCards.map(c => c.id)];
        await _apiReorder(benchIds);
      }

      loadRoster(_rosterWeekId);
    });
  });

  // Shared handler for drops onto empty active slots (used by both per-slot and container fallback)
  async function _dropOnEmptySlot(draggedId, draggedZone, targetSlotIndex) {
    const safeId = parseInt(draggedId, 10);
    if (!Number.isFinite(safeId)) return;
    if (draggedZone === "bench") {
      const res = await fetch(`${API}/roster/${safeId}/activate`, { method: "POST" });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const s = document.getElementById("rosterStatus");
        if (s) { s.textContent = d.detail || "Activate failed"; s.className = "status err"; }
        return;
      }
      // Assign this card directly to the target slot; other cards keep their slot_indexes
      await _apiReorder([safeId], [targetSlotIndex]);
    } else if (draggedZone === "active") {
      // Move the active card to the specific empty slot; leave other cards in place
      await _apiReorder([safeId], [targetSlotIndex]);
    }
    loadRoster(_rosterWeekId);
  }

  // Per-slot handlers (normal case: mouse directly over an empty slot element)
  document.querySelectorAll(".card-slot-empty[data-zone='active']").forEach(slot => {
    slot.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      slot.classList.add("drag-over");
    });
    slot.addEventListener("dragleave", () => slot.classList.remove("drag-over"));
    slot.addEventListener("drop", async e => {
      e.preventDefault();
      slot.classList.remove("drag-over");
      let payload;
      try { payload = JSON.parse(e.dataTransfer.getData("application/json")); }
      catch (_) { return; }
      const { cardId: draggedId, zone: draggedZone } = payload;
      await _dropOnEmptySlot(draggedId, draggedZone, parseInt(slot.dataset.slotIndex));
    });
  });

  // Container-level fallback: catches drops that land on the activeGrid background
  // (flex gaps between slots, padding, wrapped rows) — routes to the spatially closest empty slot.
  activeGrid.addEventListener("dragover", e => {
    if (activeGrid.querySelectorAll(".card-slot-empty").length) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    }
  });
  activeGrid.addEventListener("drop", async e => {
    if (e.target !== activeGrid) return; // per-slot handlers cover direct hits
    e.preventDefault();
    const emptySlots = Array.from(activeGrid.querySelectorAll(".card-slot-empty"));
    if (!emptySlots.length) return;
    let payload;
    try { payload = JSON.parse(e.dataTransfer.getData("application/json")); }
    catch (_) { return; }
    const { cardId: draggedId, zone: draggedZone } = payload;
    // Route to the empty slot closest to where the mouse released
    let target = emptySlots[emptySlots.length - 1];
    let minDist = Infinity;
    emptySlots.forEach(slot => {
      const r = slot.getBoundingClientRect();
      const dist = Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2));
      if (dist < minDist) { minDist = dist; target = slot; }
    });
    await _dropOnEmptySlot(draggedId, draggedZone, parseInt(target.dataset.slotIndex));
  });

  // Also allow dropping active cards onto the bench container (not just a specific bench card)
  benchGrid.addEventListener("dragover", e => {
    e.preventDefault();
    benchGrid.classList.add("drag-over");
  });
  benchGrid.addEventListener("dragleave", () => benchGrid.classList.remove("drag-over"));
  benchGrid.addEventListener("drop", async e => {
    e.preventDefault();
    benchGrid.classList.remove("drag-over");

    // Only handle if the drop landed on the container, not on a card-slot child
    if (e.target !== benchGrid) return;

    let payload;
    try { payload = JSON.parse(e.dataTransfer.getData("application/json")); }
    catch (_) { return; }

    const { cardId: draggedId, zone: draggedZone } = payload;
    if (draggedZone !== "active") return;
    const safeId = parseInt(draggedId, 10);
    if (!Number.isFinite(safeId)) return;

    const res = await fetch(`${API}/roster/${safeId}/deactivate`, { method: "POST" });
    if (!res.ok) return;
    const benchIds = [draggedId, ...benchCards.map(c => c.id)];
    await _apiReorder(benchIds);
    loadRoster(_rosterWeekId);
  });
}


async function _apiReorder(cardIds, slotIndexes = null) {
  try {
    const body = { card_ids: cardIds };
    if (slotIndexes) body.slot_indexes = slotIndexes;
    await fetch(`${API}/roster/reorder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (_) {}
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
