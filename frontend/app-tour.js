// Guided tour of My Team (issue #144). Plain JS, no library.
// Started from How to Play ("Show the tour"); the automatic first-visit start
// only runs when GET /config reports tour_autostart (GUIDED_TOUR_AUTOSTART).

const TOUR_STORAGE_KEY = "fantasy.tourSeen.v1";
const TOUR_MARGIN = 16;
const TOUR_GAP = 12;
const TOUR_PAD = 6;
const TOUR_MODAL_WAIT_MS = 10000;
const TOUR_ROSTER_WAIT_MS = 5000;
const TOUR_POLL_MS = 250;

let _tour = null;

function _tourSeen() {
  try {
    return localStorage.getItem(TOUR_STORAGE_KEY) === "1";
  } catch (_) {
    return false;
  }
}

function _markTourSeen() {
  try {
    localStorage.setItem(TOUR_STORAGE_KEY, "1");
  } catch (_) { /* blocked storage: the tour just shows again next time */ }
}

function _tourReducedMotion() {
  return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function _tourTargetVisible(el) {
  if (!el || el.getClientRects().length === 0) return false;
  return getComputedStyle(el).visibility !== "hidden";
}

function _tourModalOpen() {
  return [...document.querySelectorAll(".modal-overlay:not(.hidden)")]
    .some(el => el.getClientRects().length > 0);
}

function _tourWaitFor(conditionFn, timeoutMs) {
  return new Promise(resolve => {
    const deadline = Date.now() + timeoutMs;
    (function check() {
      if (conditionFn()) return resolve(true);
      if (Date.now() >= deadline) return resolve(false);
      setTimeout(check, TOUR_POLL_MS);
    })();
  });
}

function myTeamTourSteps() {
  const grid = document.getElementById("rosterActiveGrid");
  const rosterLimit = grid ? grid.children.length : 0;
  const rosterText = rosterLimit > 0
    ? `Put up to ${rosterLimit} cards on your active roster. Only active cards score.`
    : "Put cards on your active roster, up to the roster limit. Only active cards score.";
  return [
    {
      target: "#drawBtn",
      title: "Draw a card",
      body: `A draw costs 1 of your ${_tokenName}, or ${_teamBoosterCost} for a card from a team you pick. You get players you don't own yet first.`,
    },
    {
      target: ".rarity-grid",
      title: "Chances",
      body: "Your chance of each rarity per draw. Rarer cards score a higher bonus.",
    },
    {
      target: "#rosterActiveGrid",
      title: "Your roster",
      body: rosterText,
    },
    {
      target: "#rosterWeekSelect",
      title: "Weekly lock",
      body: "Your roster locks automatically when the week starts. Make your changes before then.",
    },
    {
      target: "#rosterTotals",
      title: "Points",
      body: "Your active cards score from every league match that week. Totals update as matches come in.",
    },
    {
      target: "#weeklyReportBtn",
      title: "Weekly Report",
      body: "After each week ends, your recap is here: what each card scored, game by game, and every match result. A popup tells you when a new one is ready.",
    },
    {
      target: "#tab-btn-leaderboard",
      title: "Leaderboards",
      body: "See how you rank each week and over the season. Full rules are in How to Play.",
    },
  ];
}

function _tourEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

/**
 * Start a spotlight tour. Steps whose target is missing or hidden are dropped,
 * and the step counter uses the filtered list. Returns true when it started.
 * Without {force: true} a browser that has already seen the tour is skipped.
 */
function startTour(steps, opts = {}) {
  if (_tour) return false;
  if (!opts.force && _tourSeen()) return false;
  const visibleSteps = (steps || []).filter(s => _tourTargetVisible(document.querySelector(s.target)));
  if (!visibleSteps.length) return false;

  const root = _tourEl("div", "tour-root");
  const backdrop = _tourEl("div", "tour-backdrop");
  const spot = _tourEl("div", "tour-spotlight");
  spot.setAttribute("aria-hidden", "true");

  const box = _tourEl("div", "tour-box");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-labelledby", "tourTitle");
  box.setAttribute("aria-describedby", "tourBody");
  box.tabIndex = -1;

  const title = _tourEl("h2", "tour-title");
  title.id = "tourTitle";
  const body = _tourEl("p", "tour-body");
  body.id = "tourBody";
  const footer = _tourEl("div", "tour-footer");
  const counter = _tourEl("span", "tour-counter");
  counter.setAttribute("aria-live", "polite");
  const skipBtn = _tourEl("button", "ghost tour-skip", "Skip");
  skipBtn.type = "button";
  const nextBtn = _tourEl("button", "tour-next", "Next");
  nextBtn.type = "button";
  footer.append(counter, skipBtn, nextBtn);
  box.append(title, body, footer);
  root.append(backdrop, spot, box);

  _tour = {
    steps: visibleSteps,
    index: 0,
    root, spot, box, title, body, counter, nextBtn,
    prevFocus: document.activeElement,
    raf: 0,
    onResize: () => _tourSchedulePosition(),
    onScroll: () => _tourSchedulePosition(),
    onKey: _tourOnKey,
  };

  backdrop.addEventListener("click", () => endTour());
  skipBtn.addEventListener("click", () => endTour());
  nextBtn.addEventListener("click", () => _tourNext());

  window.addEventListener("resize", _tour.onResize);
  window.addEventListener("scroll", _tour.onScroll, true);
  document.addEventListener("keydown", _tour.onKey, true);

  document.body.appendChild(root);
  _tourShow(0);
  return true;
}

function _tourShow(index) {
  if (!_tour) return;
  const step = _tour.steps[index];
  const target = step && document.querySelector(step.target);
  if (!_tourTargetVisible(target)) {
    // The element vanished mid-tour: drop the step and adjust the count.
    _tour.steps.splice(index, 1);
    if (!_tour.steps.length) return endTour();
    return _tourShow(Math.min(index, _tour.steps.length - 1));
  }
  _tour.index = index;
  const total = _tour.steps.length;
  const isLast = index === total - 1;

  target.scrollIntoView({ block: "center", behavior: _tourReducedMotion() ? "auto" : "smooth" });

  _tour.title.textContent = step.title;
  _tour.body.textContent = step.body;
  _tour.counter.textContent = `${index + 1} / ${total}`;
  _tour.nextBtn.textContent = isLast ? "Done" : "Next";

  _tourPosition();
  _tour.box.focus({ preventScroll: true });
}

function _tourNext() {
  if (!_tour) return;
  if (_tour.index >= _tour.steps.length - 1) return endTour();
  _tourShow(_tour.index + 1);
}

function _tourBack() {
  if (!_tour || _tour.index === 0) return;
  _tourShow(_tour.index - 1);
}

function _tourOnKey(e) {
  if (!_tour) return;
  if (e.key === "Escape") {
    e.preventDefault(); e.stopPropagation(); endTour();
  } else if (e.key === "Enter" || e.key === "ArrowRight") {
    e.preventDefault(); e.stopPropagation(); _tourNext();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault(); e.stopPropagation(); _tourBack();
  } else if (e.key === "Tab") {
    // Keep focus inside the tour box while it is open.
    const focusables = [..._tour.box.querySelectorAll("button")];
    if (!focusables.length) return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    const inside = _tour.box.contains(document.activeElement);
    if (e.shiftKey && (!inside || document.activeElement === first || document.activeElement === _tour.box)) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && (!inside || document.activeElement === last)) {
      e.preventDefault(); first.focus();
    }
  }
}

function _tourSchedulePosition() {
  if (!_tour || _tour.raf) return;
  _tour.raf = requestAnimationFrame(() => {
    if (!_tour) return;
    _tour.raf = 0;
    _tourPosition();
  });
}

function _tourPosition() {
  if (!_tour) return;
  const step = _tour.steps[_tour.index];
  const target = step && document.querySelector(step.target);
  if (!target) return;
  const rect = target.getBoundingClientRect();
  const spot = _tour.spot;
  spot.style.left = `${rect.left - TOUR_PAD}px`;
  spot.style.top = `${rect.top - TOUR_PAD}px`;
  spot.style.width = `${rect.width + TOUR_PAD * 2}px`;
  spot.style.height = `${rect.height + TOUR_PAD * 2}px`;

  const box = _tour.box;
  const vw = document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const bw = box.offsetWidth;
  const bh = box.offsetHeight;

  // Below the target when it fits, otherwise above; then clamp inside the viewport.
  const below = rect.bottom + TOUR_PAD + TOUR_GAP;
  const above = rect.top - TOUR_PAD - TOUR_GAP - bh;
  let top;
  if (below + bh <= vh - TOUR_MARGIN) top = below;
  else if (above >= TOUR_MARGIN) top = above;
  else top = vh - bh - TOUR_MARGIN;
  top = Math.max(TOUR_MARGIN, Math.min(top, vh - bh - TOUR_MARGIN));

  let left = rect.left + rect.width / 2 - bw / 2;
  left = Math.max(TOUR_MARGIN, Math.min(left, vw - bw - TOUR_MARGIN));

  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
}

/** Close the tour (Skip, Done, Esc or backdrop) and remember it was seen. */
function endTour() {
  if (!_tour) return;
  const t = _tour;
  _tour = null;
  window.removeEventListener("resize", t.onResize);
  window.removeEventListener("scroll", t.onScroll, true);
  document.removeEventListener("keydown", t.onKey, true);
  if (t.raf) cancelAnimationFrame(t.raf);
  t.root.remove();
  _markTourSeen();
  const prev = t.prevFocus;
  if (prev && prev !== document.body && document.contains(prev) && typeof prev.focus === "function") {
    prev.focus({ preventScroll: true });
  }
  if (activeUserId && typeof checkWeeklySummaryHighlight === "function") {
    checkWeeklySummaryHighlight();
  }
}

/**
 * Automatic first-visit start, called after the roster loads on My Team.
 * Off unless GET /config reported tour_autostart (GUIDED_TOUR_AUTOSTART=true).
 */
async function maybeStartMyTeamTour() {
  if (!_tourAutostart) return;
  if (!activeUserId) return;
  if (_tour || _tourSeen()) return;
  const noModal = await _tourWaitFor(() => !_tourModalOpen(), TOUR_MODAL_WAIT_MS);
  if (!noModal) return;
  const teamTab = document.getElementById("tab-team");
  if (!activeUserId || _tourSeen() || !teamTab || !teamTab.classList.contains("active")) return;
  startTour(myTeamTourSteps());
}

/** How to Play "Show the tour": always starts, seen or not; logged out opens login. */
async function startTourFromHowToPlay() {
  if (!activeUserId) {
    showLogin();
    return;
  }
  switchTab("team");
  const teamTab = document.getElementById("tab-team");
  if (!teamTab || !teamTab.classList.contains("active")) return;
  const grid = document.getElementById("rosterActiveGrid");
  await _tourWaitFor(() => !!grid && grid.children.length > 0, TOUR_ROSTER_WAIT_MS);
  startTour(myTeamTourSteps(), { force: true });
}
