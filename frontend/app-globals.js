const API = "";

let activeUserId   = null;
let activeUsername = localStorage.getItem("username");
let activeIsAdmin  = false;
let activeMustChangePassword = false;
// Issue #150: from GET /me (booleans only; the Steam id never reaches the page).
let activeSteamLinked  = false;
let activeHasPassword  = true;
let activeIsDemo       = false;
// Issue #169: Unix time the next rename is possible (null = now), from GET /me.
let activeUsernameChangeAvailableAt = null;
// Issue #150: password | both | steam_signup, from GET /config.
let _loginMethod = "password";
let _tokenName        = "Tokens";
let _tokenBalance     = null;
let _teamBoosterCost  = 3;
let _tourAutostart    = false;
let _weeks         = [];
/** Increments on modifier reroll so every PNG URL is unique (Date.now() can collide in the same ms). */
let _cardImageBustSeq = 0;

function bumpCardImageCacheBust() {
  _cardImageBustSeq += 1;
  return _cardImageBustSeq;
}

function cardImageUrl(cardId) {
  return `${API}/cards/${cardId}/image?b=${_cardImageBustSeq}`;
}

async function loadConfig() {
  try {
    const res = await fetch(`${API}/config`);
    if (res.ok) {
      const cfg = await res.json();
      _tokenName = cfg.token_name || "Tokens";
      if (cfg.team_booster_cost != null) _teamBoosterCost = cfg.team_booster_cost;
      _tourAutostart = cfg.tour_autostart === true;
      _loginMethod = cfg.login_method || "password";
      if (typeof applyLoginMode === "function") applyLoginMode();
      const htpCostEl = document.getElementById("htpTeamDrawCost");
      if (htpCostEl) htpCostEl.textContent = _teamBoosterCost;
      const hintCostEl = document.getElementById("boosterHintCost");
      if (hintCostEl) hintCostEl.textContent = _teamBoosterCost;
      const parts = [];
      if (cfg.app_release) parts.push(cfg.app_release);
      if (cfg.app_version) parts.push(cfg.app_version);
      const versionEl = document.getElementById("version-badge");
      if (versionEl) {
        if (parts.length) {
          versionEl.textContent = parts.join(" · ");
          versionEl.style.display = "";
        } else {
          versionEl.style.display = "none";
        }
      }

      window.demoMode = cfg.demo_mode === true;
      const demoBadge = document.getElementById("demo-mode-badge");
      if (demoBadge) demoBadge.style.display = window.demoMode ? "" : "none";
      if (typeof renderDemoModePanel === "function") renderDemoModePanel();
    }
  } catch (_) { /* non-fatal */ }
}

function updateTokenDisplay(balance) {
  _tokenBalance = balance;
  if (typeof _updateBoosterBtn === "function") _updateBoosterBtn();
  const el = document.getElementById("tokenBalance");
  const counter = document.getElementById("drawCounter");
  if (counter && balance !== null && activeUserId) {
    counter.textContent = `${balance} ${_tokenName} remaining`;
  }
  if (!el) return;
  if (balance !== null && activeUserId) {
    const numEl = document.getElementById("headerTokenNum");
    if (numEl) numEl.textContent = balance;
    el.style.display = "flex";
    if (typeof lucide !== "undefined") lucide.createIcons();
  } else {
    el.style.display = "none";
  }
}

// Last markup renderIfChanged wrote into each element (issue #159).
const _lastHtml = new WeakMap();

/**
 * Set el.innerHTML only when html differs from what this function last set there,
 * so a refresh with unchanged data leaves the DOM (images, focus, scroll) alone.
 * Writes on first sight of an element and when it was emptied elsewhere. Returns
 * whether it wrote. Rule: code that changes a managed element's children directly
 * (other than cosmetic classes that may persist) calls forgetRendered(el) so the
 * next render writes again.
 */
function renderIfChanged(el, html) {
  if (!el) return false;
  if (_lastHtml.get(el) === html && el.innerHTML !== "") return false;
  el.innerHTML = html;
  _lastHtml.set(el, html);
  return true;
}

/** The next renderIfChanged(el, ...) writes, whatever it was given before. */
function forgetRendered(el) {
  if (el) _lastHtml.delete(el);
}

/** renderIfChanged for a <select>: keeps the selected value when that option still exists. */
function renderSelectIfChanged(sel, html) {
  if (!sel) return false;
  const prev = sel.value;
  const wrote = renderIfChanged(sel, html);
  if (wrote && prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
  return wrote;
}

// Window scroll position per main tab during this page visit (issue #159).
const _tabScroll = {};

function switchTab(name) {
  if (activeMustChangePassword && name !== "profile") {
    name = "profile";
  }
  const current = document.querySelector(".tab-content.active");
  const sameTab = !!current && current.id === `tab-${name}`;
  if (!sameTab) {
    if (current) _tabScroll[current.id.replace(/^tab-/, "")] = window.scrollY;
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
    document.getElementById(`tab-${name}`).classList.add("active");
    const btn = document.getElementById(`tab-btn-${name}`);
    if (btn) btn.classList.add("active");
    const y = _tabScroll[name] || 0;
    requestAnimationFrame(() => window.scrollTo(0, y));
  }

  if (name === "profile")  { if (!activeUserId) return; loadProfile(); }
  if (name === "team")     {
    if (!activeUserId) return;
    loadDeck();
    loadWeeks()
      .then(() => loadRoster(_rosterWeekId))
      .then(() => { if (typeof maybeStartMyTeamTour === "function") maybeStartMyTeamTour(); });
  }
  if (name === "leaderboard") {
    loadSeasonLeaderboard();
    loadWeeks().then(() => {
      _populateLbWeekSelect();
      const sel = document.getElementById("lbWeekSelect");
      const weekId = sel ? parseInt(sel.value) : null;
      if (weekId) loadWeeklyLeaderboard(weekId);
    });
    loadPastSeasons();
  }
  if (name === "players")       { loadPlayers(); loadLeaderboard(); loadTop(); }
  if (name === "teams")         loadTeams();
  if (name === "schedule")      loadSchedule();
  if (name === "howtoplay")     loadHowToPlay();
  if (name === "admin")  { if (!activeUserId || !activeIsAdmin) return; initAdminTabs(); loadAdminWeeks(); loadWeights(); loadUsers(); loadTags(); loadCodes(); loadNotifications(); loadTokenGrantEvents(); loadPlayerPool(); loadLeagues(); loadAuditLog(); loadSeasonArchives(); }
}

function setStatus(id, msg, ok = true) {
  const el = document.getElementById(id);
  el.textContent = Array.isArray(msg) ? msg.map(e => e.msg ?? JSON.stringify(e)).join("; ") : (msg ?? "Unknown error");
  el.className = "status " + (ok ? "ok" : "err");
}

// Issue #169: the ADMIN badge comes only from the server's is_admin flag. A fixed
// string, styled apart from the filled tag chips (style.css .admin-badge).
function adminBadgeHtml(isAdmin) {
  return isAdmin === true ? `<span class="admin-badge" title="Kana Cards admin">ADMIN</span>` : "";
}

function _escHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// URLs from external data (avatars, stream links, hero icons) go into src/href
// only when they are plain http(s) links; anything else (javascript:, data:) is dropped.
function _safeUrl(u) {
  const s = String(u ?? "").trim();
  return /^https?:\/\//i.test(s) ? s : "";
}

function playerLink(id, name) {
  return `<span class="entity-link" tabindex="0" role="button" onclick="openPlayerModal(${id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPlayerModal(${id})}">${_escHtml(name)}</span>`;
}

function teamLink(id, name) {
  if (!id) return _escHtml(name) || "—";
  return `<span class="entity-link" tabindex="0" role="button" onclick="openTeamModal(${id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openTeamModal(${id})}">${_escHtml(name)}</span>`;
}
