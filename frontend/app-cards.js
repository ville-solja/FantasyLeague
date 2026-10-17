let _openCardId = null;

/** Min ms before revealing art after PNG is ready (flash overlay is ~0.5s CSS) */
const DRAW_REVEAL_MIN_MS = 220;
/** Strip burst classes shortly after drawRevealFlash ends */
const DRAW_REVEAL_FLASH_MS = 1520;
let _drawBurstHideTimer = null;
const REROLL_IMAGE_MIN_MS = 280;

const DRAW_RARITY_KEYS = ["common", "rare", "epic", "legendary"];

// Issue #205: draw from the deck, and the landing in My Team.
const DRAW_PREPARE_MAX_MS = 3000;  // the deck stirs until the card image is decoded, at most this long
const DRAW_LIFT_MS = 220;          // the lift, as the first part of one continuous move
const DRAW_TRAVEL_MS = 460;
const DRAW_FLIP_MS = 520;
const DRAW_FLIP_OVERLAP_MS = 120;  // the flip starts this long before the card arrives
const DRAW_CARD_BACK_PX = 16;      // .card-back's base font-size; its pattern is sized in em
const DRAW_DETAILS_MS = 400;
const DRAW_LANDING_MS = 520;
const DRAW_PHONE_MAX_PX = 768;     // below this the roster sits above the Draw panel
const DRAW_NOTICE_MS = 5000;
const DRAW_FLIGHT_EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";
// Lift and travel are one animation: a gentle start from the deck, no stop between
// them, and a soft arrival (#205).
const DRAW_MOVE_EASE = "cubic-bezier(0.45, 0, 0.2, 1)";
let _revealEntering = false;       // the reveal is open but its card is still flying in
let _revealDrawn = null;           // the drawn card the reveal shows, for the landing
let _drawRosterReload = null;      // the loadRoster() a draw started; the landing waits for it
let _revealDetailsTimer = null;
let _landedNoticeTimer = null;
let _landedCardId = null;

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
  modal.classList.remove(
    "reveal-overlay--draw",
    "reveal-overlay--entering",
    "reveal-overlay--dim",
    "reveal-overlay--details-in",
    "reveal-overlay--fade-in",
  );
  _revealEntering = false;
  _stripDrawBurstClasses(document.getElementById("revealDrawBurst"));
  _stripRevealImgWrapRarity(imgWrap);
  if (imgWrap) {
    imgWrap.classList.remove("reveal-img-wrap--draw", "reveal-img-wrap--draw-soft", "reveal-img-wrap--holo");
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

/** Full-screen flash in the card's rarity colour (none with reduced motion). */
function _playDrawBurst(card) {
  const burst = document.getElementById("revealDrawBurst");
  if (_prefersReducedMotion() || !burst) return;
  _stripDrawBurstClasses(burst);
  burst.classList.add("reveal-draw-burst--active", `reveal-draw-burst--rarity-${_normalizeDrawRarity(card.card_type)}`);
  _drawBurstHideTimer = setTimeout(() => {
    _drawBurstHideTimer = null;
    _stripDrawBurstClasses(burst);
  }, DRAW_REVEAL_FLASH_MS);
}

/** The rarity label: the card type ("legendary", shown in capitals), with " · Holo"
 * for a Holo card, so it reads "Legendary · Holo" (issue 50). */
function _rarityLabel(card) {
  const t = String((card && card.card_type) || "");
  return card && card.is_holo ? `${t} · Holo` : t;
}

/**
 * Issue 50: the player's accolade pips as an HTML overlay down the card's right edge
 * (accoladePipsHtml), and in the card viewer their chips below the card
 * (accoladeChipsHtml). Not part of the card image, so they stay hoverable.
 */
function _renderCardAccolades(card, drawFx) {
  const pipsEl = document.getElementById("revealPips");
  const chipsEl = document.getElementById("revealAccolades");
  const list = card && card.player_id && typeof playerAccolades === "function" ? playerAccolades(card.player_id) : [];
  const pips = list.length && typeof accoladePipsHtml === "function" ? accoladePipsHtml(list) : "";
  const titles = list.filter(a => a.kind !== "played");
  if (pipsEl) pipsEl.innerHTML = pips ? `<div class="card-pips">${pips}</div>` : "";
  if (chipsEl) {
    chipsEl.innerHTML = !drawFx && titles.length && typeof accoladeChipsHtml === "function" ? accoladeChipsHtml(titles) : "";
  }
  if (typeof refreshAccoladeIcons === "function" && (pips || titles.length)) refreshAccoladeIcons();
}

/** @param {object} card @param {string} [footer] @param {{ drawAnimation?: boolean, showActionBtn?: boolean, deferBurst?: boolean }} [opts] */
function showCard(card, footer, opts = {}) {
  const drawFx = Boolean(opts.drawAnimation);
  const actionBtn = document.getElementById("revealActionBtn");
  if (actionBtn) actionBtn.style.display = opts.showActionBtn ? "" : "none";
  const reduceMotion = _prefersReducedMotion();

  const modal = document.getElementById("revealModal");
  const cardEl = document.getElementById("revealCard");
  const imgWrap = document.getElementById("revealImgWrap") || modal.querySelector(".reveal-img-wrap");
  const img = document.getElementById("revealCardImg");
  const placeholder = document.getElementById("revealImgPlaceholder");

  _stripRevealDrawFx(modal, imgWrap, placeholder, img);

  _openCardId = card.id || null;
  _revealDrawn = null;
  cardEl.className = `reveal-card ${card.card_type}${card.is_holo ? " holo" : ""}`;
  document.getElementById("revealRarity").textContent = _rarityLabel(card);
  _renderCardAccolades(card, drawFx);
  // Draw reveal: names are painted on the PNG; duplicate HTML lines made _PLAYER_NAME_Y / _TEAM_NAME_Y tuning misleading.
  const revealPlayerEl = document.getElementById("revealPlayer");
  if (card.player_id && !drawFx) {
    const span = document.createElement("span");
    span.className = "entity-link";
    span.tabIndex = 0;
    span.setAttribute("role", "button");
    span.onclick = () => openPlayerModal(card.player_id);
    span.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPlayerModal(card.player_id); } };
    span.textContent = card.player_name || "";
    revealPlayerEl.replaceChildren(span);
  } else {
    revealPlayerEl.textContent = drawFx ? "" : (card.player_name || "");
  }
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
          // Clear the inline value rather than forcing "visible": the stylesheet then
          // shows the image, except while a deck draw is still flying in and flipping
          // (.reveal-overlay--entering hides it; an inline style would override that).
          img.style.visibility = "";
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
    const isCommon = (card.card_type || "").toLowerCase() === "common";
    rerollBtn.style.display = isCommon ? "none" : "";
    if (!isCommon) {
      const hasTokens = _tokenBalance !== null && _tokenBalance >= 1;
      rerollBtn.disabled = !hasTokens;
      rerollBtn.style.opacity = hasTokens ? "1" : "0.4";
      rerollBtn.style.cursor = hasTokens ? "pointer" : "not-allowed";
    }
  }

  modal.classList.remove("hidden");

  // Backdrop dismiss: clicking outside the card content closes the modal
  modal.onclick = e => {
    if (e.target === modal) {
      modal.classList.add("hidden");
      _openCardId = null;
    }
  };

  if (drawFx && imgWrap) {
    // Issue #205: a draw from the deck plays the burst at flip time instead.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!opts.deferBurst) _playDrawBurst(card);
        if (reduceMotion) imgWrap.classList.add("reveal-img-wrap--draw-soft");
        // Issue 50: a Holo card's art gets one iridescent sweep (none under reduced motion).
        else if (card.is_holo) imgWrap.classList.add("reveal-img-wrap--holo");
      });
    });
  }
}

let _revealBoosterTeamId = null;

function _updateRevealActionBtn() {
  const btn = document.getElementById("revealActionBtn");
  if (!btn) return;
  const cost = _revealBoosterTeamId ? (_teamBoosterCost ?? 3) : 1;
  const canAfford = _tokenBalance !== null && _tokenBalance >= cost;
  btn.textContent = canAfford ? "Draw another card" : "Continue";
}

function revealAction() {
  // Issue #205: nothing to act on until the flying card has landed in the reveal.
  if (_revealEntering) return;
  if (_revealOnClose) return closeReveal();
  const cost = _revealBoosterTeamId ? (_teamBoosterCost ?? 3) : 1;
  const canAfford = _tokenBalance !== null && _tokenBalance >= cost;
  if (canAfford) {
    if (_revealBoosterTeamId) {
      const teamId = _revealBoosterTeamId;
      closeReveal();
      _drawBoosterForTeam(teamId);
    } else {
      closeReveal();
      drawCard();
    }
  } else {
    // Continue: the drawn card flies to where it was added (issue #205).
    const landing = _takeRevealLanding();
    closeReveal();
    if (landing) _playLandingFlight(landing);
  }
}

let _revealKeyHandler = null;
// Run once when the card viewer closes (issue #188: the own player card popup is
// dismissed by Nice, the X or a backdrop click).
let _revealOnClose = null;

/**
 * The draw reveal. Issue #205: with motion it opens invisibly ("entering") so
 * _playDrawFlight can measure the card's place and fly the card in; the caller
 * always follows with _playDrawFlight, which shows the rest. With reduced motion
 * the finished reveal fades in.
 */
function showReveal(card, boosterTeamId = null) {
  _revealBoosterTeamId = boosterTeamId ?? null;
  const entering = !_prefersReducedMotion();
  showCard(card, card.is_active ? "Added to active roster" : "Added to bench", {
    drawAnimation: true,
    showActionBtn: true,
    deferBurst: entering,
  });
  _revealDrawn = card;
  _revealEntering = entering;
  document.getElementById("revealModal").classList.add(entering ? "reveal-overlay--entering" : "reveal-overlay--fade-in");
  _updateRevealActionBtn();
  if (!_revealKeyHandler) {
    _revealKeyHandler = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      revealAction();
    };
    document.addEventListener("keydown", _revealKeyHandler);
  }
}

function closeReveal() {
  const modal = document.getElementById("revealModal");
  const imgWrap = document.getElementById("revealImgWrap") || modal.querySelector(".reveal-img-wrap");
  const placeholder = document.getElementById("revealImgPlaceholder");
  const img = document.getElementById("revealCardImg");
  _stripRevealDrawFx(modal, imgWrap, placeholder, img);
  modal.classList.add("hidden");
  _revealBoosterTeamId = null;
  _revealDrawn = null;
  closeRerollConfirm();
  document.getElementById("revealDestination").classList.remove("reveal-own-card-note");
  if (_revealOnClose) {
    const onClose = _revealOnClose;
    _revealOnClose = null;
    onClose();
  }
  if (_revealKeyHandler) {
    document.removeEventListener("keydown", _revealKeyHandler);
    _revealKeyHandler = null;
  }
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
  const confirmBtn = document.getElementById("rerollConfirmBtn");
  if (confirmBtn && confirmBtn.disabled) return;
  statusEl.textContent = "";
  await withBusy(confirmBtn, async () => {
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
              img.style.visibility = "";
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
  });
}

async function loadDeck() {
  try {
    const res = await fetch(`${API}/config`);
    const cfg = await res.json();
    if (!res.ok) throw new Error(cfg.detail || "Failed to load draw rates");
    const rates = cfg.draw_rates || { common: 60, rare: 25, epic: 10, legendary: 5 };
    for (const r of DRAW_RARITY_KEYS) {
      renderIfChanged(document.getElementById(`deck-${r}`), _escHtml(`${rates[r]}%`));
    }

    // The token balance is shown once, in #drawCounter. #deckStatus only carries
    // errors, so a successful reload clears any previous one.
    setStatus("deckStatus", "");
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  }
}

// ── Draw from the deck (issue #205) ─────────────────────────────────────────

function _setDeckStirring(on) {
  const deck = document.getElementById("drawDeck");
  if (deck) deck.classList.toggle("draw-deck--stirring", Boolean(on));
}

/**
 * Load and decode the drawn card's image before anything moves. Resolves with
 * { state: "ready" | "slow" | "error" | "none", src }: "slow" after
 * DRAW_PREPARE_MAX_MS, while the image keeps loading for the reveal.
 */
function _prepareDrawnCard(card) {
  return new Promise(resolve => {
    if (!card || !card.id) { resolve({ state: "none", src: "" }); return; }
    const src = cardImageUrl(card.id);
    let done = false;
    let timer = null;
    const finish = state => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve({ state, src });
    };
    timer = setTimeout(() => finish("slow"), DRAW_PREPARE_MAX_MS);
    const img = new window.Image();
    img.onload = () => {
      if (typeof img.decode === "function") img.decode().then(() => finish("ready"), () => finish("ready"));
      else finish("ready");
    };
    img.onerror = () => finish("error");
    img.src = src;
  });
}

/** element.animate(), or null where the Web Animations API is missing or fails. */
function _drawAnimate(el, keyframes, opts) {
  if (!el || typeof el.animate !== "function") return null;
  try {
    return el.animate(keyframes, { fill: "forwards", ...opts });
  } catch (e) {
    return null;
  }
}

function _animationDone(anim) {
  return anim && anim.finished ? anim.finished.then(() => {}, () => {}) : Promise.resolve();
}

/** A transform that shows an element laid out at rect `to` at rect `from` (origin top left). */
function _rectTransform(from, to, extra = "") {
  const sx = to.width ? from.width / to.width : 1;
  const sy = to.height ? from.height / to.height : 1;
  return `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${sx}, ${sy})${extra}`;
}

function _fixedClone(className, rect) {
  const el = document.createElement("div");
  el.className = className;
  el.setAttribute("aria-hidden", "true");
  el.style.left = `${rect.left}px`;
  el.style.top = `${rect.top}px`;
  el.style.width = `${rect.width}px`;
  el.style.height = `${rect.height}px`;
  return el;
}

/** The card's face in flight: its decoded image, else its rarity face. */
function _drawCardFace(card, prep) {
  if (prep && prep.state === "ready" && prep.src) {
    const img = document.createElement("img");
    img.className = "draw-flight-img";
    img.alt = "";
    img.src = prep.src;
    return img;
  }
  const face = document.createElement("div");
  face.className = `draw-flight-rarity draw-flight-rarity--${_normalizeDrawRarity(card.card_type)}`;
  face.textContent = (card.card_type || "").toUpperCase() || "Card";
  return face;
}

/** The deck's rectangle; the Draw button's when the deck is not laid out. */
function _drawDeckRect() {
  for (const id of ["drawDeck", "drawBtn"]) {
    const el = document.getElementById(id);
    const r = el && el.getBoundingClientRect();
    if (r && r.width > 0 && r.height > 0) return r;
  }
  return null;
}

/**
 * The deck's top card lifts, flies to the reveal card's place while the page dims,
 * and flips face up with the rarity burst; then the rest of the reveal fades in.
 * Without the Web Animations API (or a layout to measure) the reveal just shows.
 */
async function _playDrawFlight(card, prep) {
  let flight = null;
  let burst = false;
  try {
    if (!_revealEntering) return;
    const modal = document.getElementById("revealModal");
    const wrap = document.getElementById("revealImgWrap");
    const to = wrap && wrap.getBoundingClientRect();
    const from = _drawDeckRect();
    if (!to || !to.width || !to.height || !from) return;
    flight = _fixedClone("draw-flight", to);
    if (typeof flight.animate !== "function") { flight = null; return; }
    const inner = document.createElement("div");
    inner.className = "draw-flight-inner";
    const front = document.createElement("div");
    front.className = "draw-flight-face draw-flight-face--front";
    front.appendChild(_drawCardFace(card, prep));
    const back = document.createElement("div");
    back.className = "draw-flight-face draw-flight-face--back card-back";
    // The clone is laid out at the reveal card's size and starts scaled down to the
    // deck's: a larger em base makes its pattern match the deck's card exactly.
    back.style.fontSize = `${(DRAW_CARD_BACK_PX * to.width / from.width).toFixed(2)}px`;
    inner.appendChild(front);
    inner.appendChild(back);
    flight.appendChild(inner);
    const start = _rectTransform(from, to);
    const lifted = _rectTransform({ ...from, top: from.top - 24 }, to, " rotate(-3deg)");
    flight.style.transform = start;
    document.body.appendChild(flight);

    const moveMs = DRAW_LIFT_MS + DRAW_TRAVEL_MS;
    modal.classList.add("reveal-overlay--dim");
    const move = _animationDone(_drawAnimate(flight, [
      { transform: start, offset: 0 },
      { transform: lifted, offset: DRAW_LIFT_MS / moveMs },
      { transform: "none", offset: 1 },
    ], { duration: moveMs, easing: DRAW_MOVE_EASE }));
    await new Promise(resolve => setTimeout(resolve, moveMs - DRAW_FLIP_OVERLAP_MS));
    if (!_revealEntering) return;
    burst = true;
    _playDrawBurst(card);
    const flip = _animationDone(_drawAnimate(inner, [
      { transform: "rotateY(180deg)" },
      { transform: "rotateY(-12deg) scale(1.06)", offset: 0.75 },
      { transform: "rotateY(0deg) scale(1)" },
    ], { duration: DRAW_FLIP_MS, easing: "ease-out" }));
    await Promise.all([move, flip]);
  } catch (e) {
    // A failed animation must not hide the result: the reveal still shows below.
  } finally {
    if (flight) flight.remove();
    if (_revealEntering && !burst) _playDrawBurst(card);
    _finishRevealEntering(card, prep);
  }
}

/** The flown card has reached its place: show the reveal card and fade the details in. */
function _finishRevealEntering(card, prep) {
  if (!_revealEntering) return;
  _revealEntering = false;
  const modal = document.getElementById("revealModal");
  modal.classList.remove("reveal-overlay--entering", "reveal-overlay--dim");
  modal.classList.add("reveal-overlay--details-in");
  clearTimeout(_revealDetailsTimer);
  _revealDetailsTimer = setTimeout(() => modal.classList.remove("reveal-overlay--details-in"), DRAW_DETAILS_MS + 200);
  // A slow image flew in as its rarity face; the reveal keeps that face until the PNG loads.
  const placeholder = document.getElementById("revealImgPlaceholder");
  if (prep && prep.state === "slow" && placeholder && placeholder.style.display !== "none"
      && placeholder.classList.contains("reveal-img-placeholder--drawing")) {
    placeholder.classList.remove("reveal-img-placeholder--drawing", "reveal-img-placeholder--static");
    placeholder.textContent = (card.card_type || "").toUpperCase() || "Card";
  }
}

/** Before Continue closes the reveal: the drawn card and where it is on screen. */
function _takeRevealLanding() {
  const card = _revealDrawn;
  if (!card || !card.id) return null;
  const wrap = document.getElementById("revealImgWrap");
  const img = document.getElementById("revealCardImg");
  const from = wrap ? wrap.getBoundingClientRect() : null;
  const src = img && img.style.display !== "none" && img.src ? img.src : "";
  return { card, from, src };
}

function _isPhoneWidth() {
  const w = window.innerWidth || 0;
  return w > 0 && w < DRAW_PHONE_MAX_PX;
}

/** An element's rectangle when it is laid out and on screen, else null. */
function _onScreenRect(el) {
  const r = el && el.getBoundingClientRect();
  if (!r || !r.width || !r.height) return null;
  if (r.bottom <= 0 || r.top >= (window.innerHeight || 0)) return null;
  return r;
}

/** Continue: after the roster re-rendered, the card flies to its slot (or off the
 * top edge on a phone or when the slot is off screen) and glows once there. */
async function _playLandingFlight({ card, from, src }) {
  try { await _drawRosterReload; } catch (e) { /* loadRoster shows its own error */ }
  const phone = _isPhoneWidth();
  const slot = typeof rosterArrivalSlot === "function" ? rosterArrivalSlot(card) : null;
  const to = phone ? null : _onScreenRect(slot);
  if (!_prefersReducedMotion() && from && from.width && from.height) {
    const target = to || {
      left: from.left + from.width / 4, top: -from.height / 2 - 40,
      width: from.width / 2, height: from.height / 2,
    };
    await _flyToSlot(card, src, from, target, to ? slot : null);
  }
  if (phone) _showLandedNotice(card);
  else if (typeof markArrived === "function") markArrived(card.id);
}

async function _flyToSlot(card, src, from, to, slot) {
  const clone = _fixedClone("draw-landing", to);
  if (typeof clone.animate !== "function") return;
  clone.appendChild(_drawCardFace(card, { state: src ? "ready" : "none", src }));
  const start = _rectTransform(from, to);
  clone.style.transform = start;
  document.body.appendChild(clone);
  if (slot) slot.style.visibility = "hidden";
  try {
    await _animationDone(_drawAnimate(clone, [{ transform: start }, { transform: "none" }],
      { duration: DRAW_LANDING_MS, easing: DRAW_FLIGHT_EASE }));
  } finally {
    clone.remove();
    if (slot) slot.style.visibility = "";
  }
}

/** Phone: "Added to active roster" / "Added to bench" with See roster, for 5 seconds. */
function _showLandedNotice(card) {
  const notice = document.getElementById("drawLandedNotice");
  if (!notice) return;
  _landedCardId = card.id;
  document.getElementById("drawLandedNoticeText").textContent = card.is_active ? "Added to active roster" : "Added to bench";
  notice.style.display = "";
  clearTimeout(_landedNoticeTimer);
  _landedNoticeTimer = setTimeout(_hideLandedNotice, DRAW_NOTICE_MS);
}

function _hideLandedNotice() {
  clearTimeout(_landedNoticeTimer);
  _landedNoticeTimer = null;
  const notice = document.getElementById("drawLandedNotice");
  if (notice) notice.style.display = "none";
}

/** See roster: scroll up to the roster and glow the new card once. */
function seeLandedCard() {
  const grid = document.getElementById("rosterActiveGrid");
  if (grid && typeof grid.scrollIntoView === "function") {
    grid.scrollIntoView({ block: "start", behavior: _prefersReducedMotion() ? "auto" : "smooth" });
  }
  if (_landedCardId != null && typeof markArrived === "function") markArrived(_landedCardId);
  _landedCardId = null;
  _hideLandedNotice();
}

// ── Team Draw (internal name: booster) ──────────────────────────────────────────────────────

let _selectedBoosterTeamId = null;

function _updateBoosterBtn() {
  const btn = document.getElementById("boosterBtn");
  if (!btn) return;
  const cost = _teamBoosterCost ?? 3;
  // Always show the real cost on the button itself — it differs from the
  // 1-token standard draw, and #drawCounter/#deckStatus only reflect the
  // standard-draw balance, not what a team draw actually costs.
  btn.textContent = `Draw from a team (${cost} ${_tokenName})`;
  if (!activeUserId) {
    btn.disabled = true;
    btn.title = "Log in to draw";
  } else if (_tokenBalance !== null && _tokenBalance < cost) {
    btn.disabled = true;
    btn.title = `Not enough ${_tokenName} (need ${cost})`;
  } else {
    btn.disabled = false;
    btn.title = "";
  }
}

async function loadBoosterTeams() {
  const grid = document.getElementById("boosterTeamGrid");
  const costLabel = document.getElementById("boosterCostLabel");
  const drawBtn = document.getElementById("boosterDrawBtn");
  if (!grid) return;
  // Issue #159: the placeholder shows only on the very first load; later the
  // previous tiles stay until the new list replaces them.
  const firstLoad = grid.innerHTML.trim() === "";
  if (firstLoad) renderIfChanged(grid, '<span style="color:#555;font-size:0.85rem;">Loading…</span>');
  if (drawBtn) drawBtn.disabled = true;
  _selectedBoosterTeamId = null;
  // A kept tile may still carry the previous selection.
  grid.querySelectorAll(".booster-team-tile--selected").forEach(t => t.classList.remove("booster-team-tile--selected"));
  const showError = msg => {
    if (firstLoad) renderIfChanged(grid, `<span style="color:#c44;">${_escHtml(msg)}</span>`);
    else setStatus("boosterStatus", msg, false);
  };

  try {
    const res = await fetch(`${API}/deck/booster`);
    const teams = await res.json();
    if (!res.ok) { showError(teams.detail ?? "Error"); return; }
    setStatus("boosterStatus", "");

    const cost = _teamBoosterCost ?? 3;
    if (costLabel) costLabel.textContent = `Costs ${cost} ${_tokenName} for 1 card`;

    if (!teams.length) { renderIfChanged(grid, '<span style="color:#555;">No teams available.</span>'); return; }

    renderIfChanged(grid, teams.map(t => {
      const exhausted = t.remaining === 0;
      const logo = t.logo_url
        ? `<img draggable="false" src="${_imgSrc(t.logo_url)}" alt="" style="width:36px;height:36px;border-radius:50%;object-fit:contain;margin-bottom:6px;" onerror="this.style.display='none'">`
        : `<div style="width:36px;height:36px;border-radius:50%;background:#222;margin-bottom:6px;"></div>`;
      return `<div class="booster-team-tile${exhausted ? " booster-team-tile--exhausted" : ""}"
                   data-team-id="${t.team_id}"
                   onclick="${exhausted ? "" : `selectBoosterTeam(${t.team_id}, this)`}"
                   style="cursor:${exhausted ? "default" : "pointer"}">
        ${logo}
        <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;line-height:1.2;">${_escHtml(t.team_name ?? "")}</div>
        <div style="font-size:0.7rem;color:${exhausted ? "#444" : "#888"};margin-top:3px;">${exhausted ? "Complete" : `${t.remaining} left`}</div>
      </div>`;
    }).join(""));
  } catch (e) {
    showError(e.message);
  }
}

function selectBoosterTeam(teamId, el) {
  _selectedBoosterTeamId = teamId;
  document.querySelectorAll(".booster-team-tile").forEach(t => t.classList.remove("booster-team-tile--selected"));
  if (el) el.classList.add("booster-team-tile--selected");
  const drawBtn = document.getElementById("boosterDrawBtn");
  if (drawBtn) drawBtn.disabled = false;
}

function openBoosterModal() {
  _updateBoosterBtn();
  const modal = document.getElementById("boosterModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  loadBoosterTeams();
}

function closeBoosterModal() {
  const modal = document.getElementById("boosterModal");
  if (modal) modal.classList.add("hidden");
  _selectedBoosterTeamId = null;
  const drawBtn = document.getElementById("boosterDrawBtn");
  if (drawBtn) drawBtn.disabled = true;
}

// Issue #185: the reveal's "Draw another card" (button or Enter) repeats a team draw
// without the modal's button, so this flag keeps it to one request at a time.
let _boosterDrawInFlight = false;

async function _drawBoosterForTeam(teamId) {
  if (_boosterDrawInFlight) return;
  _boosterDrawInFlight = true;
  _setDeckStirring(true);
  try {
    const res = await fetch(`${API}/draw/booster/${teamId}`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) { setStatus("deckStatus", data.detail, false); return; }
    updateTokenDisplay(data.tokens ?? null);
    _updateBoosterBtn();
    // Issue #205: the team picker steps aside so the card flies from the deck.
    const picker = document.getElementById("boosterModal");
    if (picker) picker.classList.add("hidden");
    const prep = await _prepareDrawnCard(data);
    _setDeckStirring(false);
    showReveal(data, teamId);
    loadDeck();
    await _playDrawFlight(data, prep);
    _drawRosterReload = loadRoster(_rosterWeekId);
  } catch (e) {
    setStatus("deckStatus", e.message, false);
  } finally {
    _setDeckStirring(false);
    _boosterDrawInFlight = false;
  }
}

async function drawBooster() {
  if (!_selectedBoosterTeamId) return;
  const btn = document.getElementById("boosterDrawBtn");
  if (!btn || btn.disabled) return;
  try {
    await withBusy(btn, () => _drawBoosterForTeam(_selectedBoosterTeamId));
  } catch (e) {
    setStatus("boosterStatus", e.message, false);
  }
  // After withBusy re-enabled the button: closing disables it until a team is picked.
  closeBoosterModal();
}

/**
 * Issue #205: the deck stirs while the draw answers and its image loads and decodes
 * (3 s at most), then the card flies from the deck into the reveal. The button stays
 * busy until the reveal shows. The roster reloads after the flight, so the new card
 * appears in its slot when it lands.
 */
async function drawCard() {
  const btn = document.getElementById("drawBtn");
  await withBusy(btn, async () => {
    _setDeckStirring(true);
    try {
      const res = await fetch(`${API}/draw`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return setStatus("deckStatus", data.detail, false);
      updateTokenDisplay(data.tokens ?? null);
      const prep = await _prepareDrawnCard(data);
      _setDeckStirring(false);
      showReveal(data);
      loadDeck();
      await _playDrawFlight(data, prep);
      _drawRosterReload = loadRoster(_rosterWeekId);
    } catch (e) {
      setStatus("deckStatus", e.message, false);
    } finally {
      _setDeckStirring(false);
    }
  });
}
