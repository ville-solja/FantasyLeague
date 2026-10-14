let _rosterCards = [];
let _rosterWeekId = null; // null = current week (default)
let _rosterLocked = false; // true when week is locked — drag disabled
let _rosterWeek = null;    // the shown week, from GET /roster
const ROSTER_SLOTS = 5;

// Issue #186: the page owns the layout. active has one entry per roster slot (card id
// or null for an empty slot), bench the card ids in order, version the stored layout
// it is based on. A move edits _layout and renders it at once; the autosave below
// stores it with one PUT /roster.
let _layout = { active: Array(ROSTER_SLOTS).fill(null), bench: [], version: null };
const _rosterById = new Map();  // card id -> card data
const _rosterNodes = new Map(); // card id -> its .card-slot node, reused by every render
const _emptySlotNodes = [];     // slot index -> its .card-slot-empty node
let _benchEmptyNode = null;

const ROSTER_FULL_MSG = `Roster full (${ROSTER_SLOTS} cards max)`;
const ROSTER_DUPLICATE_MSG = "A card for this player is already active";
const ROSTER_REMOVED_MSG = "A removed player can't be on the roster";
const ROSTER_CONFLICT_MSG = "Your roster changed elsewhere. Showing the latest.";

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
    if (!res.ok) return;
    _weeks = await res.json();
    _renderWeekSelector();
  } catch (e) { /* weeks endpoint may not exist on older deploys */ }
}

function _renderWeekSelector() {
  const sel = document.getElementById("rosterWeekSelect");
  if (!sel || !_weeks.length) return;
  const now = Date.now() / 1000;
  const nextWeek = _weeks.find(w => w.start_time > now);
  // Keep the player's own pick; with none (_rosterWeekId null) the markup's
  // default (the upcoming week) wins.
  const prev = _rosterWeekId !== null ? sel.value : "";
  const html = _weeks.map(w => {
    const isLive   = w.is_locked && w.start_time <= now && w.end_time >= now;
    const isNext   = nextWeek && w.id === nextWeek.id;
    const label = w.is_locked
      ? (isLive ? `${w.label} (live)` : `${w.label} ✓`)
      : (isNext ? `${w.label} (upcoming)` : w.label);
    const isSelected = _rosterWeekId === w.id || (_rosterWeekId === null && isNext);
    return `<option value="${w.id}"${isSelected ? " selected" : ""}>${_escHtml(label)}</option>`;
  }).join("");
  if (renderIfChanged(sel, html) && prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}

/** A week change sends a waiting save first (loadRoster flushes it). */
function onRosterWeekChange() {
  const sel = document.getElementById("rosterWeekSelect");
  _rosterWeekId = sel ? parseInt(sel.value) : null;
  return loadRoster(_rosterWeekId);
}

/**
 * Fetch and show the roster of a week. opts.animate glides the cards from where they
 * are to the server's layout (after a save conflict); opts.skipFlush skips sending a
 * waiting save first (the save itself reloads with it).
 */
async function loadRoster(weekId = null, opts = {}) {
  if (!activeUserId) return;
  if (!opts.skipFlush) await _settleRosterSave();
  if (_drag) _cancelRosterDrag();
  try {
    const url = weekId != null
      ? `${API}/roster/${activeUserId}?week_id=${weekId}`
      : `${API}/roster/${activeUserId}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load roster");
    const { active, bench, combined_value, tokens, season_points, week,
            substitutions_done, substitution_delay_hours, version } = data;
    const isLocked = week?.is_locked ?? false;
    _rosterLocked = isLocked;
    _rosterWeek = week || null;
    _rememberRosterCards(active, bench);

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

    renderIfChanged(document.getElementById("rosterCombined"), _escHtml(Number(combined_value).toFixed(1)));

    // Issue #129 — bench substitutions run a set delay after a locked week ends.
    const subsNote = document.getElementById("rosterSubsNote");
    if (subsNote) {
      if (isLocked && !substitutions_done) {
        const hours = Number(substitution_delay_hours ?? 24);
        subsNote.textContent = `Substitutions are made ${hours} hours after the week ends`;
        subsNote.style.display = "";
      } else {
        subsNote.style.display = "none";
      }
    }

    // Locked week: the saved bench (and any subbed-out cards), read-only; hidden
    // when the week has no saved bench.
    const benchSection = document.getElementById("benchSection");
    if (benchSection) benchSection.style.display = isLocked && !bench.length ? "none" : "";

    _layout = _layoutFromRoster(active, bench, version);
    renderRosterLayout(_layout, { animate: !!opts.animate });
    _showRosterCount();
    _bindRosterGrid(document.getElementById("rosterActiveGrid"));
    _bindRosterGrid(document.getElementById("benchGrid"));
  } catch (e) {
    _setRosterStatus(e.message, true);
  }
}

function _rememberRosterCards(active, bench) {
  _rosterCards = [...active, ...bench];
  _rosterById.clear();
  _rosterCards.forEach(c => _rosterById.set(c.id, c));
}

/** The page layout of a roster response: cards sit in their slot_index, so gaps are
 * kept; an active card without a usable slot takes the first free one. */
function _layoutFromRoster(active, bench, version) {
  const slots = Array(ROSTER_SLOTS).fill(null);
  const unplaced = [];
  active.forEach(c => {
    const si = c.slot_index;
    if (si != null && si >= 0 && si < ROSTER_SLOTS && slots[si] == null) slots[si] = c.id;
    else unplaced.push(c.id);
  });
  unplaced.forEach(id => {
    const free = slots.indexOf(null);
    if (free === -1) slots.push(id); else slots[free] = id;
  });
  return { active: slots, bench: bench.map(c => c.id), version: version ?? null };
}

function _copyLayout(l) {
  return { active: l.active.slice(), bench: l.bench.slice(), version: l.version };
}

function _sameLayout(a, b) {
  return a.active.length === b.active.length && a.active.every((id, i) => id === b.active[i])
    && a.bench.length === b.bench.length && a.bench.every((id, i) => id === b.bench[i]);
}

// ---------------------------------------------------------------------------
// Moves and rules (all local; the server checks the same rules again on save)
// ---------------------------------------------------------------------------

/** The rule a layout breaks, as the status line names it, or null. */
function _rosterRuleError(layout) {
  const ids = layout.active.filter(id => id != null);
  if (ids.length > ROSTER_SLOTS) return ROSTER_FULL_MSG;
  const players = new Set();
  for (const id of ids) {
    const c = _rosterById.get(id);
    if (!c) continue;
    if (c.player_is_active === false) return ROSTER_REMOVED_MSG;
    if (players.has(c.player_id)) return ROSTER_DUPLICATE_MSG;
    players.add(c.player_id);
  }
  return null;
}

/**
 * The layout after moving cardId onto target: {zone, cardId} (a card), {zone,
 * slotIndex} (an empty roster slot) or {zone} (the zone's background). Returns
 * {layout}, {error} when the move can't be made, or null when nothing would change.
 *   roster card → roster card : moves to that position, the cards between slide aside
 *   roster card → empty slot  : moves there
 *   roster card → bench       : before that bench card, or last on the background
 *   bench card  → roster card : swap; the replaced card takes the bench card's place
 *   bench card  → empty slot  : activates there (the background: the first free slot)
 *   bench card  → bench       : reorders the bench
 */
function _rosterMove(layout, cardId, target) {
  if (!target || target.cardId === cardId) return null;
  const next = _copyLayout(layout);
  const ai = next.active.indexOf(cardId);
  const bi = next.bench.indexOf(cardId);
  if (ai === -1 && bi === -1) return null;
  if (ai !== -1) {
    if (target.zone === "active") {
      if (target.cardId != null) {
        const ti = next.active.indexOf(target.cardId);
        if (ti === -1) return null;
        next.active.splice(ai, 1);
        next.active.splice(ti, 0, cardId);
      } else if (target.slotIndex != null && next.active[target.slotIndex] == null) {
        next.active[ai] = null;
        next.active[target.slotIndex] = cardId;
      } else {
        return null;
      }
    } else {
      next.active[ai] = null;
      const ti = target.cardId != null ? next.bench.indexOf(target.cardId) : -1;
      next.bench.splice(ti === -1 ? next.bench.length : ti, 0, cardId);
    }
  } else if (target.zone === "bench") {
    next.bench.splice(bi, 1);
    const ti = target.cardId != null ? layout.bench.indexOf(target.cardId) : -1;
    next.bench.splice(ti === -1 ? next.bench.length : ti, 0, cardId);
  } else if (target.cardId != null) {
    const ti = next.active.indexOf(target.cardId);
    if (ti === -1) return null;
    next.active[ti] = cardId;
    next.bench[bi] = target.cardId;
  } else {
    const si = target.slotIndex != null ? target.slotIndex : next.active.indexOf(null);
    if (si === -1 || next.active[si] != null) return { error: ROSTER_FULL_MSG };
    next.active[si] = cardId;
    next.bench.splice(bi, 1);
  }
  return _sameLayout(next, layout) ? null : { layout: next };
}

/**
 * Make next the page's layout: render it at once with a glide and schedule the save.
 * A layout that breaks a rule (or doesn't change anything) is refused: the cards glide
 * back and the status line names the rule. opts.from starts the dropped card where it
 * was released. Returns whether the layout changed.
 */
function _commitRosterLayout(next, opts = {}) {
  const err = next ? _rosterRuleError(next) : null;
  if (!next || err || _sameLayout(next, _layout)) {
    renderRosterLayout(_layout, { animate: true, from: opts.from });
    if (err) _setRosterStatus(err, true);
    return false;
  }
  _layout = { active: next.active.slice(), bench: next.bench.slice(), version: _layout.version };
  renderRosterLayout(_layout, { animate: true, from: opts.from });
  if (_saveState !== "saving" && _saveState !== "error" && !(_saveHoldUntil > Date.now())) _showRosterCount();
  _scheduleRosterSave();
  return true;
}

/** Enter/Space on a focused card: a roster card goes to the front of the bench, a
 * bench card to the first free roster slot. Same local path as a drop. */
function toggleCardZone(cardId) {
  if (_rosterLocked || _drag) return;
  const target = _layout.active.includes(cardId)
    ? { zone: "bench", cardId: _layout.bench.length ? _layout.bench[0] : null }
    : { zone: "active" };
  const res = _rosterMove(_layout, cardId, target);
  if (res && res.error) { _setRosterStatus(res.error, true); return; }
  _commitRosterLayout(res && res.layout);
}

// ---------------------------------------------------------------------------
// Keyed render: nodes are kept per card id and moved, never rebuilt
// ---------------------------------------------------------------------------

/** The inner markup of a card slot: image and weekly points (and a substitution label). */
function _cardSlotHTML(c) {
  const imgSrc = cardImageUrl(c.id);
  const pts = Number(c.total_points || 0).toFixed(1);
  return `
      <img class="card-img" src="${imgSrc}" alt="${_escHtml(c.player_name)}"
           data-player-name="${_escHtml(c.player_name)}"
           draggable="false" tabindex="0" role="button"
           onerror="_cardImgFallback(this)" />
      <div class="card-slot-pts">${pts} pts</div>${_subLabelHTML(c)}`;
}

function _rosterSlotNode(c, zone, editable) {
  let node = _rosterNodes.get(c.id);
  if (!node) {
    node = document.createElement("div");
    node.className = "card-slot";
    node.dataset.cardId = String(c.id);
    _rosterNodes.set(c.id, node);
  }
  node.dataset.rarity = String(c.card_type || "");
  node.dataset.zone = zone;
  node.classList.toggle("card-slot--editable", editable);
  const html = _cardSlotHTML(c);
  if (node._slotHtml !== html) {
    node.innerHTML = html;
    node._slotHtml = html;
  }
  return node;
}

function _emptySlotNode(i) {
  if (!_emptySlotNodes[i]) {
    const n = document.createElement("div");
    n.className = "card-slot-empty";
    n.dataset.zone = "active";
    n.dataset.slotIndex = String(i);
    n.textContent = "empty slot";
    _emptySlotNodes[i] = n;
  }
  return _emptySlotNodes[i];
}

function _benchEmptyMessage() {
  if (!_benchEmptyNode) {
    _benchEmptyNode = document.createElement("span");
    _benchEmptyNode.className = "bench-empty-note";
    _benchEmptyNode.textContent = "No cards on bench — draw some!";
  }
  return _benchEmptyNode;
}

function _rosterRects() {
  const rects = new Map();
  ["rosterActiveGrid", "benchGrid"].forEach(id => {
    const grid = document.getElementById(id);
    if (grid) Array.from(grid.children).forEach(el => rects.set(el, el.getBoundingClientRect()));
  });
  return rects;
}

function _placeChildren(grid, nodes) {
  const kids = Array.from(grid.children);
  if (kids.length === nodes.length && kids.every((k, i) => k === nodes[i])) return;
  grid.replaceChildren(...nodes);
}

/**
 * Render a layout into the roster and bench grids, reusing each card's node, so a
 * move only reorders nodes. Empty roster slots stay as placeholders. opts.animate
 * glides every node that moved (flipMove); opts.from = {el, rect} starts one node
 * elsewhere (where a dragged card was released).
 */
function renderRosterLayout(layout = _layout, opts = {}) {
  const activeGrid = document.getElementById("rosterActiveGrid");
  const benchGrid = document.getElementById("benchGrid");
  if (!activeGrid || !benchGrid) return;
  const editable = !_rosterLocked;
  const first = opts.animate ? _rosterRects() : null;
  const focused = document.activeElement;
  const activeNodes = layout.active.map((id, i) => {
    const c = id != null ? _rosterById.get(id) : null;
    return c ? _rosterSlotNode(c, "active", editable) : _emptySlotNode(i);
  });
  const benchNodes = layout.bench.map(id => _rosterById.get(id)).filter(Boolean)
    .map(c => _rosterSlotNode(c, "bench", editable));
  _placeChildren(activeGrid, activeNodes);
  _placeChildren(benchGrid, benchNodes.length || _rosterLocked ? benchNodes : [_benchEmptyMessage()]);
  forgetRendered(activeGrid);
  forgetRendered(benchGrid);
  // Moving a node drops its focus; keep the keyboard on the card it was on.
  if (focused && focused !== document.activeElement && focused.isConnected && typeof focused.focus === "function") {
    focused.focus({ preventScroll: true });
  }
  if (first) flipMove([...activeNodes, ...benchNodes], first, { from: opts.from });
}

/** Substitution label for a locked-week card (issue #129). */
function _subLabelHTML(c) {
  if (c.subbed_in) {
    const who = c.subbed_in_for ? ` ${_escHtml(c.subbed_in_for)}` : "";
    return `<div class="card-slot-note">Subbed in for${who}</div>`;
  }
  if (c.subbed_out) return `<div class="card-slot-note">Did not play</div>`;
  return "";
}

/** Image-load fallback: swap the <img> for a text placeholder built with
 * textContent, so the player name is never parsed as HTML. */
function _cardImgFallback(img) {
  const div = document.createElement("div");
  div.className = "card-img-loading";
  const slot = img.closest(".card-slot");
  const rarity = (slot && slot.dataset.rarity) || "";
  div.append(rarity.toUpperCase(), document.createElement("br"));
  const span = document.createElement("span");
  span.style.fontSize = "0.65rem";
  span.style.marginTop = "4px";
  span.textContent = img.dataset.playerName || "";
  div.appendChild(span);
  img.replaceWith(div);
}

// ---------------------------------------------------------------------------
// Pointer drag (mouse, pen and touch): the card follows the pointer, the roster
// makes room live, and the drop applies locally
// ---------------------------------------------------------------------------

const DRAG_START_PX = 6;     // mouse/pen: movement that starts a drag
const TOUCH_HOLD_MS = 250;   // touch: a hold that picks a card up
const EDGE_SCROLL_PX = 48;   // near the viewport's top/bottom edge, the page scrolls

let _drag = null;            // the pressed card while a pointer is down on it
let _rosterSuppressClick = false;

function _bindRosterGrid(grid) {
  if (!grid || grid._rosterBound) return;
  grid._rosterBound = true;
  grid.addEventListener("pointerdown", _onRosterPointerDown);
  grid.addEventListener("click", _onRosterClick);
  grid.addEventListener("keydown", _onRosterKeyDown);
  grid.addEventListener("contextmenu", e => { if (_drag) e.preventDefault(); });
}

function _onRosterPointerDown(e) {
  if (_rosterLocked || _drag) return;
  if (e.pointerType === "mouse" && e.button !== 0) return;
  const node = e.target && e.target.closest ? e.target.closest(".card-slot[data-card-id]") : null;
  if (!node) return;
  const cardId = parseInt(node.dataset.cardId, 10);
  if (!Number.isFinite(cardId)) return;
  _drag = {
    cardId, node, pointerId: e.pointerId, type: e.pointerType || "mouse",
    startX: e.clientX, startY: e.clientY, x: e.clientX, y: e.clientY,
    active: false, timer: null, frame: null, scrollFrame: null, scrollV: 0,
    clone: null, preview: null, target: null, targetKey: null, previewKey: null, hoverEls: [],
  };
  if (_drag.type === "touch") {
    _drag.timer = setTimeout(() => { if (_drag && !_drag.active) _startRosterDrag(); }, TOUCH_HOLD_MS);
  }
  window.addEventListener("pointermove", _onRosterPointerMove);
  window.addEventListener("pointerup", _onRosterPointerUp);
  window.addEventListener("pointercancel", _onRosterPointerCancel);
  document.addEventListener("touchmove", _blockTouchScroll, { passive: false });
}

function _onRosterPointerMove(e) {
  const d = _drag;
  if (!d || e.pointerId !== d.pointerId) return;
  d.x = e.clientX;
  d.y = e.clientY;
  if (!d.active) {
    if (Math.hypot(d.x - d.startX, d.y - d.startY) <= DRAG_START_PX) return;
    // Touch: moving before the hold is a scroll, not a drag.
    if (d.type === "touch") { _endRosterPointer(); return; }
    _startRosterDrag();
  }
  if (e.cancelable) e.preventDefault();
  _moveRosterClone();
  _updateRosterAutoScroll();
  _scheduleRosterPreview();
}

/** While a card is held, touch moves drag it instead of scrolling the page. */
function _blockTouchScroll(e) {
  if (_drag && _drag.active && e.cancelable) e.preventDefault();
}

function _startRosterDrag() {
  const d = _drag;
  clearTimeout(d.timer);
  d.active = true;
  d.preview = _copyLayout(_layout);
  const rect = d.node.getBoundingClientRect();
  d.offX = d.startX - rect.left;
  d.offY = d.startY - rect.top;
  const clone = document.createElement("div");
  clone.className = "card-slot roster-drag-clone";
  clone.dataset.rarity = d.node.dataset.rarity || "";
  clone.setAttribute("aria-hidden", "true");
  clone.innerHTML = d.node.innerHTML;
  clone.style.width = `${rect.width}px`;
  clone.style.height = `${rect.height}px`;
  document.body.appendChild(clone);
  d.clone = clone;
  _moveRosterClone();
  d.node.classList.add("drag-placeholder");
  if (d.type === "touch") d.node.style.touchAction = "none";
  document.body.classList.add("roster-dragging");
  // #93: light up every drop zone for the whole drag.
  document.getElementById("rosterActiveGrid")?.classList.add("drop-targets-active");
  document.getElementById("benchGrid")?.classList.add("drop-targets-active");
  document.addEventListener("keydown", _onRosterDragKey);
}

function _moveRosterClone() {
  const d = _drag;
  if (!d || !d.clone) return;
  d.clone.style.left = `${d.x - d.offX}px`;
  d.clone.style.top = `${d.y - d.offY}px`;
}

function _updateRosterAutoScroll() {
  const d = _drag;
  const h = window.innerHeight;
  let v = 0;
  if (d.y < EDGE_SCROLL_PX) v = -Math.ceil((EDGE_SCROLL_PX - d.y) / 4);
  else if (d.y > h - EDGE_SCROLL_PX) v = Math.ceil((d.y - (h - EDGE_SCROLL_PX)) / 4);
  d.scrollV = v;
  if (v && !d.scrollFrame) d.scrollFrame = requestAnimationFrame(_rosterAutoScrollStep);
}

function _rosterAutoScrollStep() {
  const d = _drag;
  if (!d) return;
  d.scrollFrame = null;
  if (!d.active || !d.scrollV) return;
  window.scrollBy(0, d.scrollV);
  _scheduleRosterPreview();
  d.scrollFrame = requestAnimationFrame(_rosterAutoScrollStep);
}

function _scheduleRosterPreview() {
  const d = _drag;
  if (!d || d.frame) return;
  d.frame = requestAnimationFrame(() => {
    if (_drag !== d) return;
    d.frame = null;
    _updateRosterPreview();
  });
}

/** The drop target under a point: a card, an empty roster slot or a zone's background;
 * null outside both zones. For a bench card, the roster's background (the gaps between
 * slots) picks its nearest empty slot; a roster card stays where it is. */
function _rosterTargetAt(x, y) {
  const el = document.elementFromPoint(x, y);
  if (!el || !el.closest) return null;
  const grid = el.closest("#rosterActiveGrid, #benchGrid");
  if (!grid) return null;
  const zone = grid.id === "benchGrid" ? "bench" : "active";
  const slot = el.closest(".card-slot[data-card-id], .card-slot-empty");
  if (slot && slot.classList.contains("card-slot-empty")) {
    return { zone, slotIndex: parseInt(slot.dataset.slotIndex, 10), el: slot };
  }
  if (slot) return { zone, cardId: parseInt(slot.dataset.cardId, 10), el: slot };
  const fromBench = _drag && (_drag.preview || _layout).bench.includes(_drag.cardId);
  if (zone === "active" && fromBench) {
    let best = null, bestDist = Infinity;
    grid.querySelectorAll(".card-slot-empty").forEach(s => {
      const r = s.getBoundingClientRect();
      const dist = Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2));
      if (dist < bestDist) { bestDist = dist; best = s; }
    });
    if (best) return { zone, slotIndex: parseInt(best.dataset.slotIndex, 10), el: best };
  }
  return { zone, el: grid };
}

function _clearRosterHover() {
  const d = _drag;
  if (!d) return;
  d.hoverEls.forEach(el => el.classList.remove("drag-over", "swap-preview"));
  d.hoverEls = [];
}

/**
 * Live preview: the result of dropping here, rendered from a copy of the layout
 * (d.preview), so the other cards slide aside; _layout changes only on the drop. A
 * bench card over a roster card marks the swap instead (the replaced card dims, with
 * an arrow to the bench). A move that breaks a rule is not previewed.
 */
function _updateRosterPreview() {
  const d = _drag;
  if (!d || !d.active) return;
  const target = _rosterTargetAt(d.x, d.y);
  // A card still gliding sits under the pointer only for the moment; wait for it.
  if (target && target.el && target.el._flipUntil > Date.now()) return;
  const key = _rosterTargetKey(target);
  if (key === d.targetKey) return;
  d.targetKey = key;
  d.target = target;
  _clearRosterHover();
  if (!target || target.cardId === d.cardId) return;
  const hover = target.el;
  if (hover) { hover.classList.add("drag-over"); d.hoverEls.push(hover); }
  if (target.zone === "active" && target.cardId != null && d.preview.bench.includes(d.cardId)) {
    hover.classList.add("swap-preview");
    return;
  }
  const res = _rosterMove(d.preview, d.cardId, target);
  if (!res || res.error || _rosterRuleError(res.layout)) return;
  d.preview = res.layout;
  d.previewKey = key;
  renderRosterLayout(d.preview, { animate: true });
}

function _rosterTargetKey(target) {
  return target ? `${target.zone}:${target.cardId ?? ""}:${target.slotIndex ?? ""}` : "";
}

function _onRosterPointerUp(e) {
  const d = _drag;
  if (!d || e.pointerId !== d.pointerId) return;
  if (!d.active) { _endRosterPointer(); return; } // a click: _onRosterClick opens the card
  d.x = e.clientX;
  d.y = e.clientY;
  const target = _rosterTargetAt(d.x, d.y);
  const from = { el: d.node, rect: d.clone.getBoundingClientRect() };
  const { preview, previewKey, cardId } = d;
  _endRosterPointer();
  if (!target) { renderRosterLayout(_layout, { animate: true, from }); return; }
  // The preview already shows the move onto the target it was made for.
  let next = preview;
  if (target.cardId !== cardId && _rosterTargetKey(target) !== previewKey) {
    const res = _rosterMove(preview, cardId, target);
    if (res && res.error) {
      renderRosterLayout(_layout, { animate: true, from });
      _setRosterStatus(res.error, true);
      return;
    }
    if (res) next = res.layout;
  }
  _commitRosterLayout(next, { from });
}

function _onRosterPointerCancel(e) {
  if (_drag && e.pointerId === _drag.pointerId) _cancelRosterDrag();
}

function _onRosterDragKey(e) {
  if (e.key === "Escape") { e.preventDefault(); _cancelRosterDrag(); }
}

/** Escape, pointercancel or a release outside the zones: the card glides back. */
function _cancelRosterDrag() {
  const d = _drag;
  if (!d) return;
  const from = d.active && d.clone ? { el: d.node, rect: d.clone.getBoundingClientRect() } : null;
  _endRosterPointer();
  if (from) renderRosterLayout(_layout, { animate: true, from });
}

function _endRosterPointer() {
  const d = _drag;
  if (!d) return;
  clearTimeout(d.timer);
  if (d.frame) cancelAnimationFrame(d.frame);
  if (d.scrollFrame) cancelAnimationFrame(d.scrollFrame);
  window.removeEventListener("pointermove", _onRosterPointerMove);
  window.removeEventListener("pointerup", _onRosterPointerUp);
  window.removeEventListener("pointercancel", _onRosterPointerCancel);
  document.removeEventListener("touchmove", _blockTouchScroll, { passive: false });
  document.removeEventListener("keydown", _onRosterDragKey);
  _clearRosterHover();
  if (d.active) {
    d.node.classList.remove("drag-placeholder");
    d.node.style.touchAction = "";
    if (d.clone) d.clone.remove();
    document.body.classList.remove("roster-dragging");
    document.getElementById("rosterActiveGrid")?.classList.remove("drop-targets-active");
    document.getElementById("benchGrid")?.classList.remove("drop-targets-active");
    // The click that follows a drag's pointerup doesn't open the card.
    _rosterSuppressClick = true;
    setTimeout(() => { _rosterSuppressClick = false; }, 50);
  }
  _drag = null;
}

/** A click (no drag) on a card opens the card view, also on locked weeks. */
function _onRosterClick(e) {
  if (_rosterSuppressClick) return;
  const node = e.target && e.target.closest ? e.target.closest(".card-slot[data-card-id]") : null;
  if (node) showRosterCard(parseInt(node.dataset.cardId, 10));
}

function _onRosterKeyDown(e) {
  if (e.key !== "Enter" && e.key !== " ") return;
  if (!e.target || !e.target.classList || !e.target.classList.contains("card-img")) return;
  const node = e.target.closest(".card-slot[data-card-id]");
  if (!node) return;
  e.preventDefault();
  toggleCardZone(parseInt(node.dataset.cardId, 10));
}

// ---------------------------------------------------------------------------
// Autosave: idle → waiting (debounce) → saving → idle, plus error. One save at a
// time; moves are never blocked, and a move during a save is sent by the next one.
// ---------------------------------------------------------------------------

const ROSTER_SAVE_DEBOUNCE_MS = 600;
const ROSTER_SAVED_SHOW_MS = 2000;
const ROSTER_LOCK_FLUSH_S = 120;  // the week locks this soon: save at once

let _saveState = "idle";
let _saveTimer = null;
let _saveDirty = false;   // the layout changed since the last save was sent
let _saveFlight = null;   // the running PUT
let _savedTimer = null;
let _saveRetried = false;   // the save already waited out one 429
let _saveHoldUntil = 0;     // after a 429: no save before this time (ms)
const ROSTER_RETRY_DEFAULT_MS = 10000;

function _rosterLockSoon() {
  const w = _rosterWeek;
  return !!(w && !w.is_locked && w.start_time && w.start_time - Date.now() / 1000 < ROSTER_LOCK_FLUSH_S);
}

function _scheduleRosterSave() {
  _saveDirty = true;
  // After a 429 the retry timer already waits out the limit; it sends the newest layout.
  if (_saveTimer && _saveHoldUntil > Date.now()) return;
  clearTimeout(_saveTimer);
  _saveTimer = null;
  if (_rosterLockSoon()) { _runRosterSave(); return; }
  if (_saveState === "idle") _saveState = "waiting";
  _saveTimer = setTimeout(() => { _saveTimer = null; _runRosterSave(); }, ROSTER_SAVE_DEBOUNCE_MS);
}

/** Send the layout now (a waiting save, or the next one after a running save). */
function flushRosterSave(opts = {}) {
  if (_saveHoldUntil > Date.now() && !opts.keepalive) return _saveFlight || Promise.resolve();
  if (_saveTimer || (_saveDirty && _saveState !== "saving")) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
    _runRosterSave(opts);
  }
  return _saveFlight || Promise.resolve();
}

/** Wait until no save waits or runs (a failed one stays failed). */
async function _settleRosterSave() {
  for (let i = 0; i < 4 && (_saveFlight || _saveTimer || (_saveDirty && _saveState !== "error")); i++) {
    await flushRosterSave();
  }
}

function retryRosterSave() {
  _saveDirty = true;
  _saveHoldUntil = 0;
  if (_saveState === "error") _saveState = "idle";
  return flushRosterSave();
}

function _runRosterSave(opts = {}) {
  if (_saveState === "saving" || !_saveDirty) return _saveFlight;
  clearTimeout(_saveTimer);
  _saveTimer = null;
  _saveDirty = false;
  _saveState = "saving";
  _setRosterStatus("Saving…");
  const sent = _copyLayout(_layout);
  const body = JSON.stringify({ active: sent.active, bench: sent.bench, base_version: sent.version });
  _saveFlight = (async () => {
    let res, data;
    try {
      res = await fetch(`${API}/roster`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: !!opts.keepalive,
      });
      data = await res.json().catch(() => ({}));
    } catch (_) {
      _saveRetried = false;
      _rosterSaveFailed();
      return;
    }
    _saveState = "idle";
    if (res.status === 429 && !_saveRetried) {
      _waitOutRateLimit(res);
      return;
    }
    _saveRetried = false;
    _saveHoldUntil = 0;
    if (res.ok) {
      _onRosterSaved(data);
    } else if (res.status === 409 && res.headers && res.headers.get("X-Roster-Conflict") === "version") {
      await _reloadRosterAfterRefusal(ROSTER_CONFLICT_MSG);
    } else if (res.status === 409 || res.status === 422 || res.status === 404) {
      await _reloadRosterAfterRefusal(_detailText(data.detail) || "Couldn't save.");
    } else {
      _rosterSaveFailed(_detailText(data.detail));
    }
  })().finally(() => {
    _saveFlight = null;
    if (_saveState !== "error" && _saveDirty && !_saveTimer) _runRosterSave();
  });
  return _saveFlight;
}

/** A 429 (a long drag session can pass RATE_LIMIT_ROSTER_MUTATION): wait for
 * Retry-After (or 10 s) and send the newest layout once more, still "Saving…". Only
 * when that save fails too does the status line say "Couldn't save." */
function _waitOutRateLimit(res) {
  _saveRetried = true;
  _saveDirty = true;
  _saveState = "waiting";
  const after = parseInt(res.headers && res.headers.get("Retry-After"), 10);
  const wait = Number.isFinite(after) && after > 0 ? after * 1000 : ROSTER_RETRY_DEFAULT_MS;
  _saveHoldUntil = Date.now() + wait;
  _setRosterStatus("Saving…");
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => { _saveTimer = null; _saveHoldUntil = 0; _runRosterSave(); }, wait);
}

function _detailText(detail) {
  if (Array.isArray(detail)) return detail.map(e => e.msg ?? JSON.stringify(e)).join("; ");
  return detail ? String(detail) : "";
}

/** A network error or an unexpected answer (a 429 names its limit): the layout stays
 * as arranged, and Retry sends it. */
function _rosterSaveFailed(detail = "") {
  _saveDirty = true;
  _saveState = "error";
  _setRosterStatus(detail ? `Couldn't save. ${detail}` : "Couldn't save.", true);
  const btn = document.getElementById("rosterRetryBtn");
  if (btn) btn.style.display = "";
}

function _onRosterSaved(data) {
  if (data.version) _layout.version = data.version;
  if (Array.isArray(data.active) && Array.isArray(data.bench)) {
    _rememberRosterCards(data.active, data.bench);
    if (data.combined_value !== undefined) {
      renderIfChanged(document.getElementById("rosterCombined"), _escHtml(Number(data.combined_value).toFixed(1)));
    }
    if (!_saveDirty && !_drag) {
      const stored = _layoutFromRoster(data.active, data.bench, _layout.version);
      if (!_sameLayout(stored, _layout)) {
        _layout = stored;
        renderRosterLayout(_layout, { animate: true });
      } else {
        renderRosterLayout(_layout); // new points or labels on the kept nodes
      }
    }
  }
  const shown = _rosterWeek;
  if (data.week && shown && data.week.id !== shown.id && data.week.start_time > shown.start_time) {
    _setRosterStatus(`${shown.label} locked; this change counts from ${data.week.label}`, true);
    return;
  }
  if (_saveDirty) return;
  _setRosterStatus("Saved");
  clearTimeout(_savedTimer);
  _savedTimer = setTimeout(() => {
    _savedTimer = null;
    if (_saveState === "idle" && !_saveDirty) _showRosterCount();
  }, ROSTER_SAVED_SHOW_MS);
}

/** A refused save: show the stored layout (gliding there) and say why. Moves made
 * since the refused save are dropped. */
async function _reloadRosterAfterRefusal(msg) {
  _saveDirty = false;
  clearTimeout(_saveTimer);
  _saveTimer = null;
  await loadRoster(_rosterWeekId, { animate: true, skipFlush: true });
  _setRosterStatus(msg, true);
}

function _setRosterStatus(msg, isErr = false) {
  clearTimeout(_savedTimer);
  _savedTimer = null;
  const el = document.getElementById("rosterStatus");
  if (el) { el.textContent = msg; el.className = isErr ? "status err" : ""; }
  const btn = document.getElementById("rosterRetryBtn");
  if (btn && _saveState !== "error") btn.style.display = "none";
}

function _showRosterCount() {
  const n = _layout.active.filter(id => id != null).length;
  _setRosterStatus(_rosterLocked ? "" : `${n}/${ROSTER_SLOTS} active`);
}

// Leaving the page sends a waiting save at once; keepalive lets it finish after unload.
if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushRosterSave({ keepalive: true });
  });
}
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("pagehide", () => flushRosterSave({ keepalive: true }));
}

async function redeemCode() {
  const code = document.getElementById("redeemCodeInput").value.trim().toUpperCase();
  if (!code) return setStatus("redeemStatus", "Enter a code", false);
  await withBusy(document.getElementById("redeemBtn"), async () => {
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
  });
}
