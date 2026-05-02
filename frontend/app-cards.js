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
  const revealPlayerEl = document.getElementById("revealPlayer");
  if (card.player_id && !drawFx) {
    const span = document.createElement("span");
    span.className = "entity-link";
    span.onclick = () => openPlayerModal(card.player_id);
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
  const btn = document.getElementById("drawBtn");
  if (btn && btn.disabled) return;
  if (btn) btn.disabled = true;
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
  } finally {
    if (btn) btn.disabled = false;
  }
}
