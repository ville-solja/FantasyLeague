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
// Issue #188: the own player card popup still to show ({player_name, card_id, outcome}), from GET /me.
let activeOwnCardGrant = null;
// Issue #150: password | both | steam_signup, from GET /config.
let _loginMethod = "password";
// Issue 213: whether the Steam re-auth popup can work here (Steam on, APP_BASE_URL set), from GET /config.
let _steamReauthAvailable = false;
let _tokenName        = "Tokens";
let _tokenBalance     = null;
let _teamBoosterCost  = 3;
let _tourAutostart    = false;
// Issue #187: the one-time Twitch starter bonus of Connect Twitch, from GET /config.
let _twitchConnectBonusTokens = 0;
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
      if (Number.isInteger(cfg.twitch_connect_bonus_tokens)) _twitchConnectBonusTokens = cfg.twitch_connect_bonus_tokens;
      _loginMethod = cfg.login_method || "password";
      _steamReauthAvailable = cfg.steam_reauth_available === true;
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
    if (numEl) _showTokenBalance(el, numEl, balance);
    el.style.display = "flex";
    if (typeof lucide !== "undefined") lucide.createIcons();
  } else {
    if (_tokenMotion.finish) _tokenMotion.finish();
    _tokenMotion.shown = null;
    el.style.display = "none";
  }
}

// Issue #155: the balance the header chip shows now (null before the first display
// after page load or a logout) and the finish function of a running count-up.
const _tokenMotion = { shown: null, finish: null };
const TOKEN_COUNT_UP_MS = 600;

/**
 * Write the balance into the header chip. A rise counts the number up, pulses the
 * chip once and floats "+N"; spending, the same balance and reduced motion show the
 * number at once. The first display after page load compares with the balance last
 * shown to this user in this browser (tokensSeen:<user id>).
 */
function _showTokenBalance(chip, numEl, balance) {
  const store = seenStore(`tokensSeen:${activeUserId}`);
  const prev = _tokenMotion.shown !== null ? _tokenMotion.shown : store.get(null);
  _tokenMotion.shown = balance;
  store.set(balance);
  if (_tokenMotion.finish) _tokenMotion.finish();
  if (typeof prev !== "number" || !(balance > prev) || prefersReducedMotion()) {
    numEl.textContent = balance;
    return;
  }
  chip.classList.remove("token-chip-pulse");
  void chip.offsetWidth; // restart the pulse
  chip.classList.add("token-chip-pulse");
  const float = document.createElement("span");
  float.className = "token-float";
  float.setAttribute("aria-hidden", "true");
  float.textContent = `+${balance - prev}`;
  chip.appendChild(float);
  const timer = setTimeout(() => finish(), TOKEN_COUNT_UP_MS + 300);
  const stopTween = tweenNumber(numEl, prev, balance, TOKEN_COUNT_UP_MS);
  function finish() {
    if (_tokenMotion.finish !== finish) return;
    _tokenMotion.finish = null;
    clearTimeout(timer);
    stopTween();
    chip.classList.remove("token-chip-pulse");
    float.remove();
  }
  _tokenMotion.finish = finish;
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
  // Issue #186: leaving My Team sends a waiting roster save at once.
  if (!sameTab && current && current.id === "tab-team" && typeof flushRosterSave === "function") flushRosterSave();
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
  if (name === "history")       loadHistory();
  if (name === "players")       { loadPlayers(); loadLeaderboard(); loadTop(); }
  if (name === "teams")         loadTeams();
  if (name === "schedule")      loadSchedule();
  if (name === "howtoplay")     loadHowToPlay();
  if (name === "admin")  { if (!activeUserId || !activeIsAdmin) return; initAdminTabs(); loadAdminWeeks(); loadWeights(); loadUsers(); loadTags(); loadCodes(); loadNotifications(); loadTokenGrantEvents(); loadPlayerPool(); loadLeagues(); loadAuditLog(); loadSeasonArchives(); }
}

/**
 * Issue #185: run an action's request with its button disabled until the answer is
 * handled, so a double click sends one request. A click on a disabled button does
 * nothing. Re-enables in finally (also on errors); a render that should leave the
 * button disabled (no tokens) runs after this returns. Usability only: the server
 * enforces every limit on its own. With no button, fn just runs.
 */
async function withBusy(btn, fn) {
  if (btn && btn.disabled) return undefined;
  if (btn) btn.disabled = true;
  try {
    return await fn();
  } finally {
    if (btn) btn.disabled = false;
  }
}

function setStatus(id, msg, ok = true) {
  const el = document.getElementById(id);
  el.textContent = Array.isArray(msg) ? msg.map(e => e.msg ?? JSON.stringify(e)).join("; ") : (msg ?? "Unknown error");
  el.className = "status " + (ok ? "ok" : "err");
}

// Issue #169: the ADMIN badge comes only from the server's is_admin flag, as a fixed
// string. Issue #202: it is a role badge in the admin colour; no tag can take that colour.
function adminBadgeHtml(isAdmin) {
  return isAdmin === true ? `<span class="role-badge role-badge-admin" title="Kana Cards admin">ADMIN</span>` : "";
}

// Issue #202: role badge variant and hover reason per tag key; any other tag uses the
// neutral tag variant with its label as the reason.
const _TAG_BADGE_VARIANTS = { caster: "caster", season_winner: "winner" };
const _TAG_BADGE_REASONS = {
  caster: "Verified caster: an approved tournament streamer",
  season_winner: "Won a previous season",
};

function _ownValue(map, key) {
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined;
}

// A user tag as a role badge. opts.title replaces the reason, opts.suffix is added to the
// label (Admin › User Management marks synced tags "(auto)").
function tagBadgeHtml(tag, opts = {}) {
  const key = String((tag && tag.key) ?? "");
  const label = String((tag && tag.label) ?? key);
  const variant = _ownValue(_TAG_BADGE_VARIANTS, key) || "tag";
  const title = opts.title || _ownValue(_TAG_BADGE_REASONS, key) || label;
  const text = opts.suffix ? `${label} ${opts.suffix}` : label;
  return `<span class="role-badge role-badge-${variant}" title="${_escHtml(title)}">${_escHtml(text)}</span>`;
}

// Issue #202: a neutral status badge (TESTER, ID SHARED, Steam/Twitch links, "(You)").
function statusBadgeHtml(label, title) {
  const tip = title ? ` title="${_escHtml(title)}"` : "";
  return `<span class="status-badge"${tip}>${_escHtml(label)}</span>`;
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

// An escaped <img src> value: an http(s) URL or a same-origin path ("/..." but not
// "//host"), else empty. For URLs that come from ingested or admin data.
function _imgSrc(u) {
  const s = String(u ?? "").trim();
  return _escHtml(/^\/(?!\/)/.test(s) ? s : _safeUrl(s));
}

function playerLink(id, name) {
  return `<span class="entity-link" tabindex="0" role="button" onclick="openPlayerModal(${id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPlayerModal(${id})}">${_escHtml(name)}</span>`;
}

function teamLink(id, name) {
  if (!id) return _escHtml(name) || "—";
  return `<span class="entity-link" tabindex="0" role="button" onclick="openTeamModal(${id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openTeamModal(${id})}">${_escHtml(name)}</span>`;
}

/** True when the player asked the system for less motion. */
function prefersReducedMotion() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const FLIP_DURATION_MS = 220;

/**
 * FLIP glide (issues #186, #155): after the DOM has moved, play each element from its
 * old place to its new one. first maps element -> its getBoundingClientRect() taken
 * before the change; opts.from = {el, rect} starts one element somewhere else (a
 * dropped card starts where it was released). Rects include running transforms, so
 * an interrupted glide continues from where the card is on screen. No motion under
 * prefers-reduced-motion: the elements are already in place.
 */
function flipMove(els, first, opts = {}) {
  if (prefersReducedMotion()) return;
  const duration = opts.duration || FLIP_DURATION_MS;
  const moves = [];
  for (const el of els) {
    const a = opts.from && opts.from.el === el ? opts.from.rect : first && first.get(el);
    if (!a) continue;
    const b = el.getBoundingClientRect();
    const dx = a.left - b.left, dy = a.top - b.top;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
    moves.push([el, dx, dy]);
  }
  for (const [el, dx, dy] of moves) {
    el.style.transition = "none";
    el.style.transform = `translate(${dx}px, ${dy}px)`;
  }
  if (!moves.length) return;
  void document.body.offsetWidth; // apply the inverted positions before gliding back
  for (const [el] of moves) {
    const seq = (el._flipSeq || 0) + 1;
    el._flipSeq = seq;
    el._flipUntil = Date.now() + duration;
    el.style.transition = `transform ${duration}ms var(--ease-out)`;
    el.style.transform = "";
    setTimeout(() => { if (el._flipSeq === seq) el.style.transition = ""; }, duration + 50);
  }
}

/**
 * Issue #155: one localStorage entry as JSON, for "what this browser last showed".
 * Every access is in try/catch: storage that is missing, blocked (private mode) or
 * full, and bad JSON, read as the fallback and drop writes. add(item, cap) keeps a
 * list with item last and only the newest cap entries.
 */
function seenStore(key) {
  return {
    get(fallback = null) {
      try {
        const raw = localStorage.getItem(key);
        return raw == null ? fallback : JSON.parse(raw);
      } catch (_) {
        return fallback;
      }
    },
    set(value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* not remembered */ }
    },
    has(item) {
      const list = this.get([]);
      return Array.isArray(list) && list.includes(item);
    },
    add(item, cap = 50) {
      const list = this.get([]);
      const next = (Array.isArray(list) ? list : []).filter(x => x !== item);
      next.push(item);
      this.set(next.slice(-cap));
    },
  };
}

/**
 * Issue #155: count el's text from `from` to `to` over ms on animation frames
 * (ease-out by default), ending exactly at `to`. Returns finish(), which jumps to
 * `to` and stops the frames. opts.format(value) builds the text (default: a whole
 * number); opts.onDone runs once when it ends either way. Under reduced motion (or
 * with nothing to count) it writes `to` at once.
 */
function tweenNumber(el, from, to, ms, opts = {}) {
  const format = opts.format || (v => String(Math.round(v)));
  const ease = opts.ease || (t => 1 - Math.pow(1 - t, 3));
  let frame = 0, start = null, done = false;
  const finish = () => {
    if (done) return;
    done = true;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (el) el.textContent = format(to);
    if (opts.onDone) opts.onDone();
  };
  if (!el || !(ms > 0) || from === to || prefersReducedMotion()) {
    finish();
    return finish;
  }
  el.textContent = format(from);
  const tick = now => {
    frame = 0;
    if (done) return;
    if (start === null) start = now;
    const t = Math.min(1, (now - start) / ms);
    if (t >= 1) { finish(); return; }
    el.textContent = format(from + (to - from) * ease(t));
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return finish;
}

// ACCOLADES (issue 50)
// Season accolades as symbols. Pips for a glance (cards, the Players list, the popup
// header), chips where the names fit (Player management, the popup timeline, History).
// Same order, names, icons and tokens as ACCOLADE_KINDS in backend/accolades.py.
const ACCOLADE_KINDS = [
  { key: "div1", kind: "champion", division: "div1", name: "Div 1 Champion", icon: "crown", plate: "filled", token: "--accolade-div1" },
  { key: "div2", kind: "champion", division: "div2", name: "Div 2 Champion", icon: "trophy", plate: "filled", token: "--accolade-div2" },
  { key: "most_points", kind: "most_points", division: null, name: "Most Points", icon: "flame", plate: "outlined", token: "--accolade-points" },
  { key: "best_average", kind: "best_average", division: null, name: "Best Average", icon: "gauge", plate: "outlined", token: "--accolade-average" },
  { key: "best_match", kind: "best_match", division: null, name: "Best Single Match", icon: "zap", plate: "outlined", token: "--accolade-match" },
  { key: "fantasy_winner", kind: "fantasy_winner", division: null, name: "Fantasy Winner", icon: "medal", plate: "outlined", token: "--accolade-fantasy" },
  { key: "played", kind: "played", division: null, name: "Played", icon: "calendar-check", plate: "muted", token: "--accolade-played" },
];

function _accoladeKindKey(a) {
  return a && a.kind === "champion" ? String(a.division || "") : String((a && a.kind) || "");
}

function _accoladeKind(a) {
  const key = _accoladeKindKey(a);
  return ACCOLADE_KINDS.find(k => k.key === key) || null;
}

function _seasonNumber(label) {
  const m = /^\s*(?:season|s)\s*(\d+)\s*$/i.exec(String(label ?? ""));
  return m ? parseInt(m[1], 10) : null;
}

function _seasonShort(a) {
  if (a && a.season_short) return String(a.season_short);
  const n = _seasonNumber(a && a.season);
  return n === null ? String((a && a.season) || "") : `S${n}`;
}

/** Newest season first; within a season, champions first (ACCOLADE_KINDS order). */
function _accoladeNewestFirst(a, b) {
  const na = _seasonNumber(a.season), nb = _seasonNumber(b.season);
  const sa = na === null ? -1 : na, sb = nb === null ? -1 : nb;
  if (sa !== sb) return sb - sa;
  const ka = ACCOLADE_KINDS.indexOf(_accoladeKind(a)), kb = ACCOLADE_KINDS.indexOf(_accoladeKind(b));
  return ka - kb;
}

/** "S1–S10, S14, S16": played seasons, oldest first, consecutive numbers as runs. */
function _compressSeasonRuns(list) {
  const nums = [], other = [];
  for (const a of list) {
    const n = _seasonNumber(a.season);
    if (n === null) other.push(_seasonShort(a));
    else if (!nums.includes(n)) nums.push(n);
  }
  nums.sort((x, y) => x - y);
  const parts = [];
  for (let i = 0; i < nums.length;) {
    let j = i;
    while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++;
    parts.push(j > i ? `S${nums[i]}–S${nums[j]}` : `S${nums[i]}`);
    i = j + 1;
  }
  return parts.concat(other).join(", ");
}

/** {tip, aria, count} for one kind's accolades (already newest first). */
function _accoladePipText(kind, list) {
  if (kind.key === "played") {
    const n = new Set(list.map(a => a.season)).size;
    const seasons = `${n} season${n === 1 ? "" : "s"}: ${_compressSeasonRuns(list)}`;
    return { tip: `Played · ${seasons}`, aria: `Played, ${seasons}`, count: String(n) };
  }
  const seasons = list.map(a => (kind.kind === "champion" && a.team_name)
    ? `${_seasonShort(a)} with ${a.team_name}` : _seasonShort(a)).join(", ");
  const times = list.length > 1 ? `, ${list.length} times` : "";
  return { tip: `${kind.name} · ${seasons}`, aria: `${kind.name}${times}: ${seasons}`,
           count: list.length > 1 ? String(list.length) : "" };
}

/**
 * Compact form: one pip per earned kind in ACCOLADE_KINDS order, a count from two
 * (Played always shows its seasons count and comes last, muted). Each pip is
 * focusable, carries its text as aria-label and shows it as a tooltip on hover,
 * focus or tap. opts.omitPlayed leaves Played out (small cards, the Titles column).
 * Empty input gives "".
 */
function accoladePipsHtml(accolades, opts = {}) {
  const list = Array.isArray(accolades) ? accolades.slice().sort(_accoladeNewestFirst) : [];
  const pips = [];
  for (const kind of ACCOLADE_KINDS) {
    if (kind.key === "played" && opts.omitPlayed) continue;
    const mine = list.filter(a => _accoladeKind(a) === kind);
    if (!mine.length) continue;
    const t = _accoladePipText(kind, mine);
    const count = t.count ? `<span class="accolade-pip-count">${_escHtml(t.count)}</span>` : "";
    pips.push(`<span class="accolade-pip accolade-pip--${kind.plate} accolade-pip--${kind.key}" role="listitem" tabindex="0" aria-label="${_escHtml(t.aria)}" data-tip="${_escHtml(t.tip)}"><i data-lucide="${kind.icon}" aria-hidden="true"></i>${count}</span>`);
  }
  if (!pips.length) return "";
  _initAccoladeTips();
  return `<span class="accolade-pips" role="list" aria-label="Accolades">${pips.join("")}</span>`;
}

/** The full name on a chip: "S16 Div 1 Champion", "S16 Played · 7 matches". */
function _accoladeChipLabel(a, kind) {
  const matches = kind.key === "played" && Number.isFinite(a.matches)
    ? ` · ${a.matches} match${a.matches === 1 ? "" : "es"}` : "";
  return `${_seasonShort(a)} ${kind.name}${matches}`;
}

/** Expanded form: one chip per accolade with its symbol and full name, newest
 * season first, champions first within a season. */
function accoladeChipsHtml(accolades) {
  const list = Array.isArray(accolades) ? accolades.filter(a => _accoladeKind(a)).sort(_accoladeNewestFirst) : [];
  if (!list.length) return "";
  return `<span class="accolade-chips">${list.map(a => {
    const kind = _accoladeKind(a);
    const detail = kind.kind === "champion" && a.team_name ? `with ${a.team_name}`
      : (a.value != null && Number.isFinite(Number(a.value)) ? `${Number(a.value).toFixed(1)} pts` : "");
    const tip = detail ? ` title="${_escHtml(detail)}"` : "";
    return `<span class="accolade-chip accolade-chip--${kind.plate} accolade-chip--${kind.key}"${tip}><i data-lucide="${kind.icon}" aria-hidden="true"></i>${_escHtml(_accoladeChipLabel(a, kind))}</span>`;
  }).join("")}</span>`;
}

// The shared tooltip (issue 50, generalised in issue 208): one element for any
// [data-tip] (accolade pips, the player popup's form chart bars), opened on hover,
// focus or tap and closed on Escape, blur, mouse leave or a tap elsewhere.
let _accoladeTipEl = null;
let _accoladeTipFor = null;
let _accoladeTipsBound = false;

function _accoladeTipTarget(e) {
  const t = e && e.target;
  return t && typeof t.closest === "function" ? t.closest("[data-tip]") : null;
}

function showAccoladeTip(pip) {
  if (typeof document === "undefined" || !pip) return;
  if (!_accoladeTipEl) {
    _accoladeTipEl = document.createElement("div");
    _accoladeTipEl.id = "accoladeTip";
    _accoladeTipEl.className = "accolade-tip";
    _accoladeTipEl.setAttribute("role", "tooltip");
    document.body.appendChild(_accoladeTipEl);
  }
  _accoladeTipEl.textContent = pip.getAttribute("data-tip") || "";
  const r = pip.getBoundingClientRect();
  _accoladeTipEl.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 260))}px`;
  _accoladeTipEl.style.top = `${r.bottom + 6}px`;
  _accoladeTipEl.classList.add("accolade-tip--open");
  pip.setAttribute("aria-describedby", "accoladeTip");
  _accoladeTipFor = pip;
}

function hideAccoladeTip() {
  if (_accoladeTipEl) _accoladeTipEl.classList.remove("accolade-tip--open");
  if (_accoladeTipFor) _accoladeTipFor.removeAttribute("aria-describedby");
  _accoladeTipFor = null;
}

function _initAccoladeTips() {
  if (_accoladeTipsBound || typeof document === "undefined" || !document.addEventListener) return;
  _accoladeTipsBound = true;
  document.addEventListener("mouseover", e => { const pip = _accoladeTipTarget(e); if (pip) showAccoladeTip(pip); });
  document.addEventListener("mouseout", e => {
    const pip = _accoladeTipTarget(e);
    if (pip && pip === _accoladeTipFor && !pip.contains(e.relatedTarget)) hideAccoladeTip();
  });
  document.addEventListener("focusin", e => { const pip = _accoladeTipTarget(e); if (pip) showAccoladeTip(pip); });
  document.addEventListener("focusout", e => { if (_accoladeTipTarget(e) === _accoladeTipFor) hideAccoladeTip(); });
  document.addEventListener("click", e => {
    const pip = _accoladeTipTarget(e);
    if (!pip) { hideAccoladeTip(); return; }  // a tap elsewhere
    if (pip === _accoladeTipFor) hideAccoladeTip();
    else showAccoladeTip(pip);
  });
  // Escape closes an open tooltip first, before any dialog it sits in.
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !_accoladeTipFor) return;
    hideAccoladeTip();
    e.stopPropagation();
  }, true);
}

/** Renders Lucide icons placed by the helpers above (data-lucide). */
function refreshAccoladeIcons() {
  if (typeof lucide !== "undefined" && lucide.createIcons) lucide.createIcons();
}

// GET /accolades, loaded once per page and used for every card.
let _accoladesByPlayer = {};
let _accoladesCurrentSeason = "";
let _accoladesLoading = null;
// Issue 217: GET /accolades `tags`, {player id: [{key, label}]}.
let _tagsByPlayer = {};

function loadAccolades(force = false) {
  if (_accoladesLoading && !force) return _accoladesLoading;
  _accoladesLoading = fetch(`${API}/accolades`)
    .then(res => (res.ok ? res.json() : null))
    .then(data => {
      if (!data) return;
      _accoladesByPlayer = data.players || {};
      _tagsByPlayer = data.tags || {};
      _accoladesCurrentSeason = data.current_season || "";
      if (typeof _rerenderRosterPips === "function") _rerenderRosterPips();
    })
    .catch(() => { /* cards render without pips */ });
  return _accoladesLoading;
}

/** One player's accolades from GET /accolades ([] when none or not loaded). */
function playerAccolades(playerId) {
  const list = _accoladesByPlayer[String(playerId)];
  return Array.isArray(list) ? list : [];
}

/** The pip overlay stacked down a card's right edge. */
function cardPipsHtml(playerId) {
  const pips = accoladePipsHtml(playerAccolades(playerId));
  return pips ? `<div class="card-pips">${pips}</div>` : "";
}

// TAG SYMBOLS (issue 217)
// A linked user's tags as pips down a card's left edge, mirroring the accolade pips on
// the right. Admin first, then caster, then any other tag (its label as the tooltip).
// season_winner is never a tag pip: the Fantasy Winner accolade already shows it.
const TAG_SYMBOLS = {
  admin:  { icon: "shield", tip: "Kana Cards admin", token: "--tag-admin", order: 0 },
  caster: { icon: "mic", tip: "Caster", token: "--tag-caster", order: 1 },
};
const TAG_SYMBOL_GENERIC = { icon: "tag", tip: null, token: "--tag-generic", order: 2 };
const TAG_SYMBOLS_HIDDEN = ["season_winner"];

/** One player's tags from GET /accolades ([] when none or not loaded). */
function playerTags(playerId) {
  const list = _ownValue(_tagsByPlayer, String(playerId));
  return Array.isArray(list) ? list : [];
}

/**
 * One focusable pip per tag (data-tip tooltip, same text as aria-label), ordered admin,
 * caster, then other tags in their given order. Empty input gives "".
 */
function tagPipsHtml(tags) {
  const list = (Array.isArray(tags) ? tags : [])
    .map((t, i) => {
      const key = String((t && t.key) ?? "");
      const known = _ownValue(TAG_SYMBOLS, key);
      const sym = known || TAG_SYMBOL_GENERIC;
      const tip = known ? known.tip : String((t && t.label) ?? key);
      return { key, sym, tip, known: Boolean(known), i };
    })
    .filter(t => t.key && !TAG_SYMBOLS_HIDDEN.includes(t.key))
    .sort((a, b) => (a.sym.order - b.sym.order) || (a.i - b.i));
  if (!list.length) return "";
  _initAccoladeTips();
  const pips = list.map(t => {
    const variant = t.known ? t.key : "generic";
    return `<span class="card-tag-pip card-tag-pip--${variant}" role="listitem" tabindex="0" aria-label="${_escHtml(t.tip)}" data-tip="${_escHtml(t.tip)}"><i data-lucide="${t.sym.icon}" aria-hidden="true"></i></span>`;
  });
  return `<span class="tag-pips" role="list" aria-label="Tags">${pips.join("")}</span>`;
}
// END TAG SYMBOLS (issue 217)
// END ACCOLADES (issue 50)
