const API = "";

let activeUserId   = null;
let activeUsername = localStorage.getItem("username");
let activeIsAdmin  = false;  // always set from server via loadMe(), never trusted from localStorage
let activeMustChangePassword = false;
let _tokenName     = "Tokens";
let _tokenBalance  = null;
/** Increments on modifier reroll so every PNG URL is unique (Date.now() can collide in the same ms). */
let _cardImageBustSeq = 0;
function bumpCardImageCacheBust() {
  _cardImageBustSeq += 1;
  return _cardImageBustSeq;
}
function cardImageUrl(cardId) {
  return `${API}/cards/${cardId}/image?b=${_cardImageBustSeq}`;
}

// -------------------------------------------------------
// CONFIG
// -------------------------------------------------------

async function loadConfig() {
  try {
    const res = await fetch(`${API}/config`);
    if (res.ok) {
      const cfg = await res.json();
      _tokenName = cfg.token_name || "Tokens";
    }
  } catch (_) { /* non-fatal */ }
}

function updateTokenDisplay(balance) {
  _tokenBalance = balance;
  const el = document.getElementById("tokenBalance");
  const counter = document.getElementById("drawCounter");
  if (counter && balance !== null && activeUserId) {
    counter.textContent = `${balance} ${_tokenName} remaining`;
  }
  if (!el) return;
  if (balance !== null && activeUserId) {
    el.textContent = `${balance} ${_tokenName}`;
    el.style.display = "";
  } else {
    el.style.display = "none";
  }
}

// -------------------------------------------------------
// AUTH
// -------------------------------------------------------

function applyAuthState() {
  const loggedIn = !!activeUserId;

  document.getElementById("headerUserLabel").textContent = loggedIn ? activeUsername : "";
  document.getElementById("headerLoginBtn").style.display  = loggedIn ? "none" : "";
  document.getElementById("headerLogoutBtn").style.display = loggedIn ? "" : "none";

  document.getElementById("tab-btn-team").style.display    = loggedIn ? "" : "none";
  document.getElementById("tab-btn-profile").style.display = loggedIn ? "" : "none";
  document.getElementById("tab-btn-admin").style.display   = (loggedIn && activeIsAdmin) ? "" : "none";

  const tokenEl = document.getElementById("tokenBalance");
  if (tokenEl) tokenEl.style.display = loggedIn ? "" : "none";

  if (!loggedIn) switchTab("leaderboard");
}

function showLogin() {
  document.getElementById("registerModal").classList.add("hidden");
  document.getElementById("forgotModal").classList.add("hidden");
  document.getElementById("loginModal").classList.remove("hidden");
  document.getElementById("loginStatus").textContent = "";
}

function showForgotPassword() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("forgotModal").classList.remove("hidden");
  document.getElementById("forgotStatus").textContent = "";
  document.getElementById("forgotUsername").value = "";
}

async function submitForgotPassword() {
  const username = document.getElementById("forgotUsername").value.trim();
  if (!username) return setStatus("forgotStatus", "Enter your username", false);
  try {
    const res = await fetch(`${API}/forgot-password`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username})
    });
    if (res.ok) {
      setStatus("forgotStatus", "If an account with that username exists, a temporary password has been sent to its registered email.");
      document.getElementById("forgotUsername").value = "";
    } else {
      const data = await res.json();
      setStatus("forgotStatus", data.detail, false);
    }
  } catch (e) {
    setStatus("forgotStatus", e.message, false);
  }
}

function closeLoginModal() {
  document.getElementById("loginModal").classList.add("hidden");
}

function showRegister() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("registerModal").classList.remove("hidden");
  document.getElementById("registerStatus").textContent = "";
}

async function login() {
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  if (!username || !password) return setStatus("loginStatus", "Enter username and password", false);

  try {
    const res = await fetch(`${API}/login`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, password}) });
    const data = await res.json();
    if (!res.ok) return setStatus("loginStatus", data.detail, false);

    await loadMe();
    document.getElementById("loginModal").classList.add("hidden");
    document.getElementById("loginPassword").value = "";
    applyAuthState();
    if (activeMustChangePassword) {
      switchTab("profile");
    } else {
      switchTab("team");
      loadDeck();
    }
  } catch (e) {
    setStatus("loginStatus", e.message, false);
  }
}

async function register() {
  const username = document.getElementById("regUsername").value.trim();
  const email    = document.getElementById("regEmail").value.trim();
  const password = document.getElementById("regPassword").value;
  if (!username || !email || !password) return setStatus("registerStatus", "All fields required", false);

  try {
    const res = await fetch(`${API}/register`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, email, password}) });
    const data = await res.json();
    if (!res.ok) return setStatus("registerStatus", data.detail, false);

    await loadMe();
    document.getElementById("registerModal").classList.add("hidden");
    document.getElementById("regUsername").value = "";
    document.getElementById("regEmail").value    = "";
    document.getElementById("regPassword").value = "";
    applyAuthState();
    switchTab("team");
    loadDeck();
  } catch (e) {
    setStatus("registerStatus", e.message, false);
  }
}

async function logout() {
  await fetch(`${API}/logout`, { method: "POST" });
  activeUserId = activeUsername = null;
  activeIsAdmin = false;
  activeMustChangePassword = false;
  localStorage.removeItem("username");
  localStorage.removeItem("is_admin");
  updateTokenDisplay(null);
  applyAuthState();
}

async function loadMe() {
  try {
    const res = await fetch(`${API}/me`);
    if (!res.ok) return;
    const data = await res.json();
    activeUserId             = data.user_id;
    activeUsername           = data.username;
    activeIsAdmin            = data.is_admin;
    activeMustChangePassword = data.must_change_password ?? false;
    localStorage.setItem("username", activeUsername);
    localStorage.setItem("is_admin", String(activeIsAdmin));
    updateTokenDisplay(data.tokens ?? null);
    _applyTempPasswordBanner();
  } catch (_) {}
}

function _applyTempPasswordBanner() {
  const banner = document.getElementById("tempPasswordBanner");
  if (banner) banner.style.display = activeMustChangePassword ? "" : "none";
}

// -------------------------------------------------------
// PROFILE
// -------------------------------------------------------

async function loadProfile() {
  document.getElementById("profileUsername").value = activeUsername || "";
  document.getElementById("profilePlayerPreview").style.display = "none";
  document.getElementById("playerIdStatus").textContent = "";
  document.getElementById("usernameStatus").textContent = "";
  try {
    const res = await fetch(`${API}/profile/${activeUserId}`);
    const data = await res.json();
    if (data.player_id) {
      document.getElementById("profilePlayerId").value = data.player_id;
      if (data.player_name) showPlayerPreview(data.player_name, data.player_avatar_url);
    } else {
      document.getElementById("profilePlayerId").value = "";
    }
    _renderTwitchLinkStatus(data.twitch_linked);
  } catch (e) {
    setStatus("playerIdStatus", e.message, false);
  }
}

function _renderTwitchLinkStatus(linked) {
  document.getElementById("twitchLinked").style.display = linked ? "block" : "none";
  document.getElementById("twitchUnlinked").style.display = linked ? "none" : "block";
  document.getElementById("twitchCodeSection").style.display = "none";
  document.getElementById("twitchStatus").textContent = "";
}

var _twitchCodeTimer = null;

async function generateTwitchCode() {
  document.getElementById("twitchStatus").textContent = "";
  try {
    const res = await fetch(`${API}/twitch/link-code`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("twitchStatus", data.detail, false);
    document.getElementById("twitchCode").textContent = data.code;
    document.getElementById("twitchCodeSection").style.display = "block";
    if (_twitchCodeTimer) clearInterval(_twitchCodeTimer);
    let remaining = data.expires_in;
    const expiry = document.getElementById("twitchCodeExpiry");
    expiry.style.color = "";
    expiry.textContent = `Expires in ${remaining}s`;
    _twitchCodeTimer = setInterval(() => {
      remaining--;
      if (remaining <= 0) {
        clearInterval(_twitchCodeTimer);
        _twitchCodeTimer = null;
        expiry.textContent = "Code expired. Generate a new one.";
        expiry.style.color = "#c0392b";
        document.getElementById("twitchCode").textContent = "------";
      } else {
        expiry.textContent = `Expires in ${remaining}s`;
      }
    }, 1000);
  } catch (e) {
    setStatus("twitchStatus", e.message, false);
  }
}

function showPlayerPreview(name, avatarUrl) {
  const preview = document.getElementById("profilePlayerPreview");
  document.getElementById("profilePlayerName").textContent = name || "";
  const avatar = document.getElementById("profilePlayerAvatar");
  if (avatarUrl) { avatar.src = avatarUrl; avatar.style.display = ""; }
  else { avatar.style.display = "none"; }
  preview.style.display = name ? "flex" : "none";
}

async function saveUsername() {
  const username = document.getElementById("profileUsername").value.trim();
  if (!username) return setStatus("usernameStatus", "Username cannot be empty", false);
  try {
    const res = await fetch(`${API}/profile/username`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username})
    });
    const data = await res.json();
    if (!res.ok) return setStatus("usernameStatus", data.detail, false);
    activeUsername = data.username;
    localStorage.setItem("username", activeUsername);
    document.getElementById("headerUserLabel").textContent = activeUsername;
    setStatus("usernameStatus", "Username updated");
  } catch (e) {
    setStatus("usernameStatus", e.message, false);
  }
}

async function changePassword() {
  const current = document.getElementById("pwCurrent").value;
  const newPw   = document.getElementById("pwNew").value;
  if (!current || !newPw) return setStatus("passwordStatus", "Fill in both fields", false);
  try {
    const res = await fetch(`${API}/profile/password`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({current_password: current, new_password: newPw})
    });
    const data = await res.json();
    if (!res.ok) return setStatus("passwordStatus", data.detail, false);
    document.getElementById("pwCurrent").value = "";
    document.getElementById("pwNew").value = "";
    setStatus("passwordStatus", "Password updated");
    activeMustChangePassword = false;
    _applyTempPasswordBanner();
  } catch (e) {
    setStatus("passwordStatus", e.message, false);
  }
}

async function savePlayerId() {
  const raw = document.getElementById("profilePlayerId").value.trim();
  const player_id = raw ? parseInt(raw) : null;
  try {
    const res = await fetch(`${API}/profile/player-id`, {
      method: "PUT", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_id})
    });
    const data = await res.json();
    if (!res.ok) return setStatus("playerIdStatus", data.detail, false);
    if (data.player_name) {
      showPlayerPreview(data.player_name, data.player_avatar_url);
      setStatus("playerIdStatus", "Player linked");
    } else if (player_id) {
      document.getElementById("profilePlayerPreview").style.display = "none";
      setStatus("playerIdStatus", "ID saved — player not found in current league data yet");
    } else {
      document.getElementById("profilePlayerPreview").style.display = "none";
      setStatus("playerIdStatus", "Player unlinked");
    }
  } catch (e) {
    setStatus("playerIdStatus", e.message, false);
  }
}

// -------------------------------------------------------
// TABS
// -------------------------------------------------------

function switchTab(name) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  const btn = document.getElementById(`tab-btn-${name}`);
  if (btn) btn.classList.add("active");

  if (name === "profile")  { if (!activeUserId) return; loadProfile(); }
  if (name === "team")     { if (!activeUserId) return; loadDeck(); loadWeeks().then(() => loadRoster(_rosterWeekId)); }
  if (name === "leaderboard") {
    loadWeeks().then(() => { _populateLbWeekSelect(); switchLeaderboard(_lbMode); });
    loadLeaderboard(); loadTop();
  }
  if (name === "players")       loadPlayers();
  if (name === "teams")         loadTeams();
  if (name === "schedule")      loadSchedule();
  if (name === "admin")  { if (!activeUserId || !activeIsAdmin) return; loadWeights(); loadUsers(); loadCodes(); loadAuditLog(); }
}

// -------------------------------------------------------
// HELPERS
// -------------------------------------------------------

function setStatus(id, msg, ok = true) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = "status " + (ok ? "ok" : "err");
}

// -------------------------------------------------------
// DECK
// -------------------------------------------------------

async function loadDeck() {
  try {
    const res = await fetch(`${API}/deck`);
    const counts = await res.json();
    const rarities = ["common", "rare", "epic", "legendary"];
    let total = 0;
    for (const r of rarities) {
      const n = counts[r] ?? 0;
      document.getElementById(`deck-${r}`).textContent = n;
      total += n;
    }
    setStatus("deckStatus", total > 0 ? `${total} cards available` : "Deck is empty");
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}

async function drawCard() {
  try {
    const res = await fetch(`${API}/draw`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("deckStatus", data.detail, false);
    updateTokenDisplay(data.tokens ?? null);
    if (data.id) {
      const warm = new window.Image();
      warm.src = cardImageUrl(data.id);
    }
    showReveal(data);
    loadDeck();
    loadRoster(_rosterWeekId);
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}

function toggleScoringInfo() {
  const el = document.getElementById("scoringInfo");
  if (el) el.style.display = el.style.display === "none" ? "" : "none";
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

let _openCardId = null;

/** Min ms before revealing art after PNG is ready (flash overlay is ~0.5s CSS) */
const DRAW_REVEAL_MIN_MS = 220;
/** Strip burst classes shortly after drawRevealFlash ends */
const DRAW_REVEAL_FLASH_MS = 1520;
let _drawBurstHideTimer = null;
const REROLL_IMAGE_MIN_MS = 280;

const DRAW_RARITY_KEYS = ["common", "rare", "epic", "legendary"];

function _normalizeDrawRarity(cardType) {
  const t = String(cardType || "common").toLowerCase();
  return DRAW_RARITY_KEYS.includes(t) ? t : "common";
}

function _stripDrawBurstClasses(burst) {
  if (_drawBurstHideTimer) {
    clearTimeout(_drawBurstHideTimer);
    _drawBurstHideTimer = null;
  }
  if (!burst) return;
  burst.classList.remove("reveal-draw-burst--active");
  for (const r of DRAW_RARITY_KEYS) {
    burst.classList.remove(`reveal-draw-burst--rarity-${r}`);
  }
}

function _stripRevealImgWrapRarity(imgWrap) {
  if (!imgWrap) return;
  for (const r of DRAW_RARITY_KEYS) {
    imgWrap.classList.remove(`reveal-img-wrap--rarity-${r}`);
  }
}

function _prefersReducedMotion() {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function _stripRevealDrawFx(modal, imgWrap, placeholder, img) {
  modal.classList.remove("reveal-overlay--draw");
  _stripDrawBurstClasses(document.getElementById("revealDrawBurst"));
  _stripRevealImgWrapRarity(imgWrap);
  if (imgWrap) {
    imgWrap.classList.remove("reveal-img-wrap--draw", "reveal-img-wrap--draw-soft");
  }
  if (placeholder) {
    placeholder.classList.remove(
      "reveal-img-placeholder--drawing",
      "reveal-img-placeholder--static",
    );
  }
  if (img) {
    img.classList.remove("reveal-card-img--reroll-flash");
    img.style.visibility = "";
  }
}

/** @param {object} card @param {string} [footer] @param {{ drawAnimation?: boolean }} [opts] */
function showCard(card, footer, opts = {}) {
  const drawFx = Boolean(opts.drawAnimation);
  const reduceMotion = _prefersReducedMotion();

  const modal = document.getElementById("revealModal");
  const cardEl = document.getElementById("revealCard");
  const imgWrap = document.getElementById("revealImgWrap") || modal.querySelector(".reveal-img-wrap");
  const img = document.getElementById("revealCardImg");
  const placeholder = document.getElementById("revealImgPlaceholder");

  _stripRevealDrawFx(modal, imgWrap, placeholder, img);

  _openCardId = card.id || null;
  cardEl.className = `reveal-card ${card.card_type}`;
  document.getElementById("revealRarity").textContent = card.card_type;
  // Draw reveal: names are painted on the PNG; duplicate HTML lines made _PLAYER_NAME_Y / _TEAM_NAME_Y tuning misleading.
  document.getElementById("revealPlayer").textContent = drawFx ? "" : (card.player_name || "");
  document.getElementById("revealTeam").textContent = drawFx ? "" : (card.team_name || "");
  document.getElementById("revealDestination").textContent = footer || "";
  closeRerollConfirm();

  img.style.display = "none";
  img.style.visibility = "";
  placeholder.style.display = "flex";
  placeholder.textContent = "";
  if (drawFx) {
    placeholder.classList.add("reveal-img-placeholder--drawing");
    if (reduceMotion) placeholder.classList.add("reveal-img-placeholder--static");
    placeholder.setAttribute("aria-label", "Drawing card, image loading");
  } else {
    placeholder.classList.remove("reveal-img-placeholder--drawing", "reveal-img-placeholder--static");
    placeholder.textContent = "generating card…";
    placeholder.removeAttribute("aria-label");
  }

  const t0 = performance.now();
  const minWait = drawFx ? (reduceMotion ? 320 : DRAW_REVEAL_MIN_MS) : 0;

  if (card.id) {
    placeholder.setAttribute("aria-busy", "true");
    const src = cardImageUrl(card.id);
    const tmp = new window.Image();
    tmp.onload = () => {
      const reveal = () => {
        img.src = src;
        img.alt = drawFx
          ? [card.player_name, card.team_name].filter(Boolean).join(" — ") || "Fantasy card"
          : "";
        img.style.display = "";
        img.style.opacity = "1";
        img.style.visibility = "hidden";
        const afterBitmapReady = () => {
          img.style.visibility = "visible";
          placeholder.style.display = "none";
          placeholder.classList.remove(
            "reveal-img-placeholder--drawing",
            "reveal-img-placeholder--static",
          );
          placeholder.removeAttribute("aria-label");
          placeholder.setAttribute("aria-busy", "false");
        };
        if (typeof img.decode === "function") {
          img.decode().then(afterBitmapReady).catch(afterBitmapReady);
        } else {
          requestAnimationFrame(afterBitmapReady);
        }
      };
      const elapsed = performance.now() - t0;
      const delay = Math.max(0, minWait - elapsed);
      if (delay > 0) setTimeout(reveal, delay);
      else reveal();
    };
    tmp.onerror = () => {
      placeholder.classList.remove("reveal-img-placeholder--drawing", "reveal-img-placeholder--static");
      placeholder.removeAttribute("aria-label");
      placeholder.setAttribute("aria-busy", "false");
      placeholder.textContent = (card.card_type || "").toUpperCase() || "Card";
      _stripDrawBurstClasses(document.getElementById("revealDrawBurst"));
      if (imgWrap) {
        imgWrap.classList.remove("reveal-img-wrap--draw", "reveal-img-wrap--draw-soft");
        _stripRevealImgWrapRarity(imgWrap);
      }
    };
    tmp.src = src;
  } else {
    placeholder.classList.remove("reveal-img-placeholder--drawing", "reveal-img-placeholder--static");
  }

  const rerollBtn = document.getElementById("rerollBtn");
  if (rerollBtn) {
    const hasTokens = _tokenBalance !== null && _tokenBalance >= 1;
    rerollBtn.disabled = !hasTokens;
    rerollBtn.style.opacity = hasTokens ? "1" : "0.4";
    rerollBtn.style.cursor = hasTokens ? "pointer" : "not-allowed";
  }

  modal.classList.remove("hidden");

  if (drawFx && imgWrap) {
    const rarityKey = _normalizeDrawRarity(card.card_type);
    const burst = document.getElementById("revealDrawBurst");
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!reduceMotion && burst) {
          _stripDrawBurstClasses(burst);
          burst.classList.add("reveal-draw-burst--active", `reveal-draw-burst--rarity-${rarityKey}`);
          _drawBurstHideTimer = setTimeout(() => {
            _drawBurstHideTimer = null;
            _stripDrawBurstClasses(burst);
          }, DRAW_REVEAL_FLASH_MS);
        }
        if (reduceMotion) imgWrap.classList.add("reveal-img-wrap--draw-soft");
      });
    });
  }
}

function showReveal(card) {
  showCard(card, card.is_active ? "Added to active roster" : "Added to bench (roster full)", {
    drawAnimation: true,
  });
}

function closeReveal() {
  const modal = document.getElementById("revealModal");
  const imgWrap = document.getElementById("revealImgWrap") || modal.querySelector(".reveal-img-wrap");
  const placeholder = document.getElementById("revealImgPlaceholder");
  const img = document.getElementById("revealCardImg");
  _stripRevealDrawFx(modal, imgWrap, placeholder, img);
  modal.classList.add("hidden");
  closeRerollConfirm();
}

function openRerollConfirm() {
  document.getElementById("rerollConfirm").style.display = "";
  document.getElementById("rerollStatus").textContent = "";
}

function closeRerollConfirm() {
  const el = document.getElementById("rerollConfirm");
  if (el) el.style.display = "none";
}

async function confirmReroll() {
  if (!_openCardId) return;
  const statusEl = document.getElementById("rerollStatus");
  statusEl.textContent = "";
  try {
    const res = await fetch(`${API}/roster/${_openCardId}/reroll`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = data.detail || "Reroll failed.";
      return;
    }
    updateTokenDisplay(data.tokens);
    closeRerollConfirm();
    bumpCardImageCacheBust();
    // Update cached roster card if present
    const cached = _rosterCards.find(x => x.id === _openCardId);
    if (cached) cached.modifiers = data.modifiers;
    // Refresh card art (modifiers are painted on PNG) + roster thumbnails
    const img = document.getElementById("revealCardImg");
    const placeholder = document.getElementById("revealImgPlaceholder");
    if (img && placeholder && _openCardId) {
      const modal = document.getElementById("revealModal");
      const imgWrap = document.getElementById("revealImgWrap") || (modal && modal.querySelector(".reveal-img-wrap"));
      const reduceMotion = _prefersReducedMotion();
      const t0 = performance.now();
      const minWait = reduceMotion ? 0 : REROLL_IMAGE_MIN_MS;
      const src = cardImageUrl(_openCardId);
      img.style.display = "none";
      placeholder.style.display = "flex";
      placeholder.textContent = "";
      placeholder.setAttribute("aria-busy", "true");
      placeholder.setAttribute("aria-label", "Updating card image");
      placeholder.classList.add("reveal-img-placeholder--drawing");
      placeholder.classList.toggle("reveal-img-placeholder--static", reduceMotion);
      const tmp = new window.Image();
      tmp.onload = () => {
        const reveal = () => {
          img.src = src;
          img.style.display = "";
          img.style.opacity = "1";
          img.style.visibility = "hidden";
          const afterBitmapReady = () => {
            img.style.visibility = "visible";
            placeholder.style.display = "none";
            placeholder.classList.remove("reveal-img-placeholder--drawing", "reveal-img-placeholder--static");
            placeholder.removeAttribute("aria-label");
            placeholder.setAttribute("aria-busy", "false");
            if (!reduceMotion) {
              img.classList.add("reveal-card-img--reroll-flash");
              setTimeout(() => img.classList.remove("reveal-card-img--reroll-flash"), 400);
            }
          };
          if (typeof img.decode === "function") {
            img.decode().then(afterBitmapReady).catch(afterBitmapReady);
          } else {
            requestAnimationFrame(afterBitmapReady);
          }
        };
        const elapsed = performance.now() - t0;
        const delay = Math.max(0, minWait - elapsed);
        if (delay > 0) setTimeout(reveal, delay);
        else reveal();
      };
      tmp.onerror = () => {
        placeholder.classList.remove("reveal-img-placeholder--drawing", "reveal-img-placeholder--static");
        placeholder.removeAttribute("aria-label");
        placeholder.setAttribute("aria-busy", "false");
        placeholder.textContent = "Could not load card";
      };
      tmp.src = src;
    }
    loadRoster(_rosterWeekId);
    // Gray out button if out of tokens
    const rerollBtn = document.getElementById("rerollBtn");
    if (rerollBtn && data.tokens < 1) {
      rerollBtn.disabled = true;
      rerollBtn.style.opacity = "0.4";
      rerollBtn.style.cursor = "not-allowed";
    }
  } catch (e) {
    statusEl.textContent = "Network error.";
  }
}

// -------------------------------------------------------
// ROSTER
// -------------------------------------------------------

let _rosterCards = [];
let _weeks = [];
let _rosterWeekId = null; // null = current week (default)

async function showRosterCard(cardId) {
  // Use cached data if available, otherwise fetch
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
  // Next editable week = first week that hasn't started yet
  const nextWeek = _weeks.find(w => w.start_time > now);
  sel.innerHTML = _weeks.map(w => {
    const isLive   = w.is_locked && w.start_time <= now && w.end_time >= now;
    const isNext   = nextWeek && w.id === nextWeek.id;
    const label = w.is_locked
      ? (isLive ? `${w.label} (live)` : `${w.label} \u2713`)
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

    // Week status label
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

    // Locked banner
    const banner = document.getElementById("rosterLockedBanner");
    if (banner) {
      if (isLocked && week) {
        banner.textContent = `Roster locked — ${week.label} snapshot`;
        banner.style.display = "";
      } else {
        banner.style.display = "none";
      }
    }

    // ── Active roster card grid ──────────────────────────────────────────
    const activeGrid = document.getElementById("rosterActiveGrid");
    const emptyCount = Math.max(0, 5 - active.length);
    let activeHTML = active.map(c => _cardSlotHTML(c, isLocked ? null : "bench")).join("");
    activeHTML += Array(emptyCount).fill(`<div class="card-slot-empty">empty slot</div>`).join("");
    activeGrid.innerHTML = activeHTML || `<span style="color:#444;font-size:0.85rem;">No active cards</span>`;

    document.getElementById("rosterCombined").textContent = Number(combined_value).toFixed(1);

    // ── Bench card grid ──────────────────────────────────────────────────
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

// -------------------------------------------------------
// LEADERBOARDS
// -------------------------------------------------------

let _lbMode = "season";

function switchLeaderboard(mode) {
  _lbMode = mode;
  const seasonBtn = document.getElementById("lbSeasonBtn");
  const weeklyBtn = document.getElementById("lbWeeklyBtn");
  const weekSel   = document.getElementById("lbWeekSelect");
  const header    = document.getElementById("lbPtsHeader");
  if (seasonBtn) seasonBtn.className = mode === "season" ? "secondary" : "ghost";
  if (weeklyBtn) weeklyBtn.className = mode === "weekly"  ? "secondary" : "ghost";
  if (weekSel)   weekSel.style.display = mode === "weekly" ? "" : "none";
  if (header)    header.textContent = mode === "season" ? "Season pts" : "Week pts";
  if (mode === "season") {
    loadSeasonLeaderboard();
  } else {
    const sel = document.getElementById("lbWeekSelect");
    const weekId = sel ? parseInt(sel.value) : null;
    if (weekId) loadWeeklyLeaderboard(weekId);
  }
}

async function onLbWeekChange() {
  const sel = document.getElementById("lbWeekSelect");
  if (sel) loadWeeklyLeaderboard(parseInt(sel.value));
}

function toggleLbDetail(userId) {
  const el = document.getElementById(`lb-detail-${userId}`);
  if (el) el.classList.toggle("hidden");
}

function _lbStandingsRow(r, i, ptsKey) {
  const isMe = activeUserId && String(r.id) === String(activeUserId);
  const baseStyle = isMe ? "color:#f0b429;font-weight:bold;" : "";
  const cards = r.cards || [];
  const hasCards = cards.length > 0;
  const cursorStyle = hasCards ? "cursor:pointer;" : "";
  const chevron = hasCards ? `<span class="lb-chevron" id="lb-chevron-${r.id}">›</span>` : "";
  const pts = Number(r[ptsKey] || 0).toFixed(1);
  const mainRow = `<tr style="${baseStyle}${cursorStyle}" ${hasCards ? `onclick="toggleLbDetail(${r.id})"` : ""}>
    <td>${i + 1}</td>
    <td>${r.username}${chevron}</td>
    <td>${pts}</td>
  </tr>`;
  if (!hasCards) return mainRow;
  const breakdown = cards.map(c =>
    `<span class="lb-card-chip ${c.card_type}">${c.player_name} <span class="lb-chip-pts">${Number(c.points).toFixed(1)}</span></span>`
  ).join("");
  const detailRow = `<tr class="lb-card-detail hidden" id="lb-detail-${r.id}">
    <td colspan="3"><div class="lb-card-breakdown">${breakdown}</div></td>
  </tr>`;
  return mainRow + detailRow;
}

async function loadSeasonLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard/season`);
    const rows = await res.json();
    const tbody = document.getElementById("standingsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => _lbStandingsRow(r, i, "season_points")).join("");
    setStatus("standingsStatus", "");
  } catch (e) {
    setStatus("standingsStatus", e.message, false);
  }
}

async function loadWeeklyLeaderboard(weekId) {
  try {
    const res = await fetch(`${API}/leaderboard/weekly?week_id=${weekId}`);
    const rows = await res.json();
    const tbody = document.getElementById("standingsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No data yet</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map((r, i) => _lbStandingsRow(r, i, "week_points")).join("");
    setStatus("standingsStatus", "");
  } catch (e) {
    setStatus("standingsStatus", e.message, false);
  }
}

function _populateLbWeekSelect() {
  const sel = document.getElementById("lbWeekSelect");
  if (!sel || !_weeks.length) return;
  sel.innerHTML = _weeks.filter(w => w.is_locked).map(w =>
    `<option value="${w.id}">${w.label}</option>`
  ).join("");
  if (!sel.innerHTML) sel.innerHTML = "<option disabled>No locked weeks yet</option>";
}

async function loadLeaderboard() {
  try {
    const res = await fetch(`${API}/leaderboard`);
    const rows = await res.json();
    const tbody = document.getElementById("leaderboardBody");
    if (!rows.length) { tbody.innerHTML = "<tr><td colspan='4' style='color:#444'>No data yet</td></tr>"; return; }
    tbody.innerHTML = rows.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td><img src="${r.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(r.id, r.name)}</td>
        <td>${r.matches}</td>
        <td>${Number(r.avg_points).toFixed(1)}</td>
      </tr>`).join("");
    setStatus("leaderboardStatus", "");
  } catch (e) {
    setStatus("leaderboardStatus", e.message, false);
  }
}

async function loadTop() {
  try {
    const res = await fetch(`${API}/top`);
    const rows = await res.json();
    document.getElementById("topBody").innerHTML = rows.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td><img src="${r.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(r.id, r.name)}</td>
        <td>${Number(r.fantasy_points).toFixed(1)}</td>
      </tr>`).join("");
    setStatus("topStatus", "");
  } catch (e) {
    setStatus("topStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — WEIGHTS
// -------------------------------------------------------

async function loadWeights() {
  try {
    const res = await fetch(`${API}/weights`);
    const weights = await res.json();
    document.getElementById("weightsBody").innerHTML = weights.map(w => `
      <tr>
        <td>${w.label}</td>
        <td>${w.value}</td>
      </tr>`).join("");
    setStatus("weightsStatus", "");
  } catch (e) {
    setStatus("weightsStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — USERS / TOKEN BALANCES
// -------------------------------------------------------

async function loadUsers() {
  try {
    const res = await fetch(`${API}/users`);
    const rows = await res.json();
    if (!res.ok) return setStatus("usersStatus", rows.detail, false);
    document.getElementById("usersBody").innerHTML = rows.map(u => `
      <tr>
        <td>${u.username}</td>
        <td>${u.tokens}</td>
        <td style="display:flex;gap:6px;align-items:center;">
          <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
          <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
        </td>
      </tr>`).join("");
    setStatus("usersStatus", "");
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function grantTokens(targetId) {
  const amount = parseInt(document.getElementById(`grant_${targetId}`).value);
  if (!amount || amount < 1) return setStatus("usersStatus", "Enter a valid amount", false);
  try {
    const res = await fetch(`${API}/grant-tokens`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({target_user_id: targetId, amount}) });
    const data = await res.json();
    setStatus("usersStatus", res.ok ? `${data.username} now has ${data.tokens} ${_tokenName}` : data.detail, res.ok);
    if (res.ok) loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — PROMO CODES
// -------------------------------------------------------

async function loadCodes() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/codes`);
    const rows = await res.json();
    if (!res.ok) return setStatus("codesStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("codesBody").innerHTML = "<tr><td colspan='4' style='color:#444'>No codes yet</td></tr>";
      return;
    }
    document.getElementById("codesBody").innerHTML = rows.map(c => `
      <tr>
        <td><code>${c.code}</code></td>
        <td>${c.token_amount}</td>
        <td>${c.redemptions}</td>
        <td><button class="ghost" style="font-size:0.8rem;" onclick="deleteCode(${c.id})">Delete</button></td>
      </tr>`).join("");
    setStatus("codesStatus", "");
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

async function createCode() {
  const code   = document.getElementById("newCodeInput").value.trim().toUpperCase();
  const amount = parseInt(document.getElementById("newCodeAmount").value);
  if (!code)        return setStatus("codesStatus", "Enter a code name", false);
  if (!amount || amount < 1) return setStatus("codesStatus", "Enter a token amount ≥ 1", false);
  try {
    const res = await fetch(`${API}/codes`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code, token_amount: amount}) });
    const data = await res.json();
    if (!res.ok) return setStatus("codesStatus", data.detail, false);
    document.getElementById("newCodeInput").value  = "";
    document.getElementById("newCodeAmount").value = "";
    setStatus("codesStatus", `Code ${data.code} created`);
    loadCodes();
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

async function deleteCode(codeId) {
  try {
    const res = await fetch(`${API}/codes/${codeId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("codesStatus", d.detail, false); }
    setStatus("codesStatus", "Code deleted");
    loadCodes();
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ADMIN — INGEST / RECALCULATE / SCHEDULE REFRESH
// -------------------------------------------------------

async function refreshSchedule() {
  setStatus("scheduleRefreshStatus", "Refreshing...");
  try {
    const res = await fetch(`${API}/schedule/refresh`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("scheduleRefreshStatus", data.detail, false);
    const count = data.weeks?.length ?? 0;
    setStatus("scheduleRefreshStatus", count > 0 ? `Done. ${count} weeks loaded.` : (data.error || "No data returned"), count > 0);
  } catch (e) {
    setStatus("scheduleRefreshStatus", e.message, false);
  }
}

async function ingestLeague() {
  const id = document.getElementById("leagueId").value;
  if (!id) return setStatus("ingestStatus", "Enter a league ID", false);
  setStatus("ingestStatus", "Ingesting... this may take a while");
  try {
    const res = await fetch(`${API}/ingest/league/${id}`, { method: "POST" });
    const data = await res.json();
    setStatus("ingestStatus", res.ok ? `Done. League ${data.league_id} ingested.` : data.detail, res.ok);
  } catch (e) {
    setStatus("ingestStatus", e.message, false);
  }
}

async function loadAuditLog() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/audit-logs`);
    const rows = await res.json();
    if (!res.ok) return setStatus("auditStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("auditBody").innerHTML = "<tr><td colspan='4' style='color:#444'>No entries yet</td></tr>";
      return;
    }
    document.getElementById("auditBody").innerHTML = rows.map(r => {
      const dt = new Date(r.timestamp * 1000).toLocaleString();
      return `<tr>
        <td style="white-space:nowrap;font-size:0.8rem;color:#888;">${dt}</td>
        <td>${r.actor_username || "<em style='color:#555'>system</em>"}</td>
        <td><code style="font-size:0.8rem;">${r.action}</code></td>
        <td style="font-size:0.8rem;color:#888;">${r.detail || ""}</td>
      </tr>`;
    }).join("");
    setStatus("auditStatus", "");
  } catch (e) {
    setStatus("auditStatus", e.message, false);
  }
}

async function recalculate() {
  setStatus("recalcStatus", "Recalculating...");
  try {
    const res = await fetch(`${API}/recalculate`, { method: "POST" });
    const data = await res.json();
    setStatus("recalcStatus", res.ok ? `Done. ${data.recalculated} records updated.` : data.detail, res.ok);
  } catch (e) {
    setStatus("recalcStatus", e.message, false);
  }
}

// -------------------------------------------------------
// ENTITY LINKS
// -------------------------------------------------------

function playerLink(id, name) {
  return `<span class="entity-link" onclick="openPlayerModal(${id})">${name}</span>`;
}

function teamLink(id, name) {
  if (!id) return name || "—";
  return `<span class="entity-link" onclick="openTeamModal(${id})">${name}</span>`;
}

// -------------------------------------------------------
// PLAYERS TAB
// -------------------------------------------------------

let _playersData = [];

async function loadPlayers() {
  try {
    const res = await fetch(`${API}/players`);
    const rows = await res.json();
    _playersData = rows;
    renderPlayers(rows);
    setStatus("playersStatus", `${rows.length} players`);
  } catch (e) {
    setStatus("playersStatus", e.message, false);
  }
}

function filterPlayers() {
  const q = document.getElementById("playersSearch").value.toLowerCase();
  const filtered = _playersData.filter(p =>
    p.name.toLowerCase().includes(q) || (p.team_name || "").toLowerCase().includes(q)
  );
  renderPlayers(filtered);
}

function renderPlayers(rows) {
  const tbody = document.getElementById("playersBody");
  if (!rows.length) {
    tbody.innerHTML = "<tr><td colspan='5' style='color:#444'>No players found</td></tr>";
    return;
  }
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td><img src="${p.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(p.id, p.name)}</td>
      <td>${p.team_id ? teamLink(p.team_id, p.team_name) : (p.team_name || "—")}</td>
      <td>${p.matches}</td>
      <td>${Number(p.avg_points).toFixed(1)}</td>
      <td>${Number(p.total_points).toFixed(1)}</td>
    </tr>`).join("");
}

// -------------------------------------------------------
// TEAMS TAB
// -------------------------------------------------------

async function loadTeams() {
  try {
    const res = await fetch(`${API}/teams`);
    const rows = await res.json();
    const tbody = document.getElementById("teamsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No teams found</td></tr>";
      setStatus("teamsStatus", "");
      return;
    }
    tbody.innerHTML = rows.map(t => `
      <tr>
        <td>${teamLink(t.id, t.name)}</td>
        <td>${t.matches}</td>
        <td>${t.player_count}</td>
      </tr>`).join("");
    setStatus("teamsStatus", `${rows.length} teams`);
  } catch (e) {
    setStatus("teamsStatus", e.message, false);
  }
}

// -------------------------------------------------------
// PLAYER MODAL
// -------------------------------------------------------

async function openPlayerModal(playerId) {
  const modal = document.getElementById("playerModal");
  modal.classList.remove("hidden");
  document.getElementById("playerModalName").textContent = "Loading...";
  document.getElementById("playerModalTeam").innerHTML = "";
  document.getElementById("playerModalAvatar").style.display = "none";
  document.getElementById("playerModalStats").innerHTML = "";
  document.getElementById("playerModalHistory").innerHTML = "";
  document.getElementById("playerModalStatus").textContent = "";

  try {
    const res = await fetch(`${API}/players/${playerId}`);
    const p = await res.json();
    if (!res.ok) {
      document.getElementById("playerModalName").textContent = "";
      setStatus("playerModalStatus", p.detail || "Failed to load", false);
      return;
    }

    const avatar = document.getElementById("playerModalAvatar");
    if (p.avatar_url) { avatar.src = p.avatar_url; avatar.style.display = ""; }

    document.getElementById("playerModalName").textContent = p.name;
    document.getElementById("playerModalTeam").innerHTML = p.team_id
      ? `<span class="entity-link" onclick="closePlayerModal();openTeamModal(${p.team_id})">${p.team_name}</span>`
      : (p.team_name || "");

    document.getElementById("playerModalStats").innerHTML = `
      <div class="player-modal-stat-grid">
        <div class="player-modal-stat"><div class="val">${p.matches}</div><div class="lbl">Matches</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.avg_points).toFixed(1)}</div><div class="lbl">Avg pts</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.total_points).toFixed(1)}</div><div class="lbl">Total pts</div></div>
        ${p.best_match ? `<div class="player-modal-stat"><div class="val">${Number(p.best_match.fantasy_points).toFixed(1)}</div><div class="lbl">Best match</div></div>` : ""}
      </div>`;

    if (!p.match_history.length) {
      document.getElementById("playerModalHistory").innerHTML =
        "<tr><td colspan='6' style='color:#444'>No matches yet</td></tr>";
    } else {
      document.getElementById("playerModalHistory").innerHTML = p.match_history.map(m => {
        const date = m.start_time
          ? new Date(m.start_time * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "2-digit"})
          : "—";
        return `<tr>
          <td>${date}</td>
          <td>${Number(m.fantasy_points).toFixed(1)}</td>
          <td>${m.kills}/${m.assists}/${m.deaths}</td>
          <td>${Math.round(m.gold_per_min)}</td>
          <td>${m.obs_placed + m.sen_placed}</td>
          <td>${Math.round(m.tower_damage)}</td>
        </tr>`;
      }).join("");
    }
  } catch (e) {
    setStatus("playerModalStatus", e.message, false);
  }
}

function closePlayerModal() {
  document.getElementById("playerModal").classList.add("hidden");
}

// -------------------------------------------------------
// TEAM MODAL
// -------------------------------------------------------

async function openTeamModal(teamId) {
  const modal = document.getElementById("teamModal");
  modal.classList.remove("hidden");
  document.getElementById("teamModalName").textContent = "Loading...";
  document.getElementById("teamModalMeta").textContent = "";
  document.getElementById("teamModalPlayers").innerHTML = "";
  document.getElementById("teamModalStatus").textContent = "";

  try {
    const res = await fetch(`${API}/teams/${teamId}`);
    const t = await res.json();
    if (!res.ok) {
      document.getElementById("teamModalName").textContent = "";
      setStatus("teamModalStatus", t.detail || "Failed to load", false);
      return;
    }

    document.getElementById("teamModalName").textContent = t.name;
    document.getElementById("teamModalMeta").textContent = `${t.matches} matches`;

    if (!t.players.length) {
      document.getElementById("teamModalPlayers").innerHTML =
        "<tr><td colspan='4' style='color:#444'>No players found</td></tr>";
    } else {
      document.getElementById("teamModalPlayers").innerHTML = t.players.map(p => `
        <tr>
          <td><img src="${p.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" /><span class="entity-link" onclick="closeTeamModal();openPlayerModal(${p.id})">${p.name}</span></td>
          <td>${p.matches}</td>
          <td>${Number(p.avg_points).toFixed(1)}</td>
          <td>${Number(p.total_points).toFixed(1)}</td>
        </tr>`).join("");
    }
  } catch (e) {
    setStatus("teamModalStatus", e.message, false);
  }
}

function closeTeamModal() {
  document.getElementById("teamModal").classList.add("hidden");
}

// -------------------------------------------------------
// SCHEDULE
// -------------------------------------------------------

async function loadSchedule() {
  const content = document.getElementById("scheduleContent");
  const staleEl = document.getElementById("scheduleStale");
  content.innerHTML = "<span style='color:#444'>Loading...</span>";
  staleEl.style.display = "none";
  try {
    const res = await fetch(`${API}/schedule`);
    const data = await res.json();
    if (!res.ok) { setStatus("scheduleStatus", data.detail || "Failed to load", false); content.innerHTML = ""; return; }

    if (data.stale) {
      staleEl.textContent = `Cached data from ${data.cached_at ? new Date(data.cached_at).toLocaleString() : "unknown"}`;
      staleEl.style.display = "";
    }
    if (data.error && !data.weeks?.length) {
      content.innerHTML = `<span style='color:#555'>${data.error}</span>`;
      setStatus("scheduleStatus", "");
      return;
    }
    if (!data.weeks?.length) {
      content.innerHTML = "<span style='color:#555'>No schedule data available.</span>";
      setStatus("scheduleStatus", "");
      return;
    }

    // Flatten all weeks, both divisions; drop entries with no datetime
    const allSeries = [];
    for (const week of data.weeks) {
      for (const s of (week.div1 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div1"});
      for (const s of (week.div2 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div2"});
    }

    const upcoming = allSeries.filter(s => s.match_status !== "past")
                              .sort((a, b) => b.datetime_iso.localeCompare(a.datetime_iso));
    const past     = allSeries.filter(s => s.match_status === "past")
                              .sort((a, b) => b.datetime_iso.localeCompare(a.datetime_iso));

    const renderRow = s => {
      const isPast = s.match_status === "past";
      const divLabel = s.division === "div1"
        ? `<span class="badge badge-division div1">Div 1</span>`
        : `<span class="badge badge-division div2">Div 2</span>`;

      const r = s.series_result;
      const scoreHtml = r
        ? `<span class="series-score">${r.team1_wins}–${r.team2_wins}</span>`
        : `<span class="series-score no-result">vs</span>`;

      let meta;
      if (r && r.start_time) {
        const d = new Date(r.start_time * 1000);
        meta = d.toLocaleDateString("fi-FI", {day: "numeric", month: "numeric"})
             + " " + d.toLocaleTimeString("fi-FI", {hour: "2-digit", minute: "2-digit"});
      } else {
        meta = `${s.date || ""}${s.date && s.time ? " " : ""}${s.time || ""}`;
      }

      const streamHtml = s.stream_url
        ? `<a class="stream-link" href="${s.stream_url}" target="_blank" rel="noopener">${s.stream_label || "Watch"} ↗</a>`
        : (s.stream_label ? `<span style="color:#555;">${s.stream_label}</span>` : `<span></span>`);

      return `<div class="series-row${isPast ? " past" : ""}">
        ${divLabel}
        <span class="series-team">${s.team1_id ? teamLink(s.team1_id, s.team1) : (s.team1 || "—")}</span>
        ${scoreHtml}
        <span class="series-team right">${s.team2_id ? teamLink(s.team2_id, s.team2) : (s.team2 || "—")}</span>
        <span class="series-meta">${meta}</span>
        ${streamHtml}
      </div>`;
    };

    const upcomingHtml = upcoming.map(renderRow).join("");
    const pastHtml     = past.map(renderRow).join("");
    const divider      = upcoming.length && past.length
      ? `<div style="border-top:1px solid #2a2a2a;margin:16px 0 12px;"></div>`
      : "";

    content.innerHTML = upcomingHtml + divider + pastHtml;
    if (!allSeries.length) content.innerHTML = "<span style='color:#555'>No dated fixtures found.</span>";

    setStatus("scheduleStatus", "");
  } catch (e) {
    setStatus("scheduleStatus", e.message, false);
    content.innerHTML = "";
  }
}

// -------------------------------------------------------
// INIT
// -------------------------------------------------------

async function init() {
  await loadConfig();
  await loadMe();
  applyAuthState();
  if (!activeUserId) {
    showLogin();
  } else {
    loadDeck();
    loadWeeks().then(() => loadRoster(_rosterWeekId));
  }
  loadWeeks().then(() => { _populateLbWeekSelect(); loadSeasonLeaderboard(); });
  loadLeaderboard();
  loadTop();
}

init();
