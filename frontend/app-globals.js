const API = "";

let activeUserId   = null;
let activeUsername = localStorage.getItem("username");
let activeIsAdmin  = false;
let activeMustChangePassword = false;
let _tokenName     = "Tokens";
let _tokenBalance  = null;
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
    const numEl = document.getElementById("headerTokenNum");
    if (numEl) numEl.textContent = balance;
    el.style.display = "flex";
    if (typeof lucide !== "undefined") lucide.createIcons();
  } else {
    el.style.display = "none";
  }
}

function switchTab(name) {
  if (activeMustChangePassword && name !== "profile") {
    name = "profile";
  }
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  const btn = document.getElementById(`tab-btn-${name}`);
  if (btn) btn.classList.add("active");

  if (name === "profile")  { if (!activeUserId) return; loadProfile(); }
  if (name === "team")     { if (!activeUserId) return; loadDeck(); loadWeeks().then(() => loadRoster(_rosterWeekId)); }
  if (name === "leaderboard") {
    loadSeasonLeaderboard();
    loadWeeks().then(() => {
      _populateLbWeekSelect();
      const sel = document.getElementById("lbWeekSelect");
      const weekId = sel ? parseInt(sel.value) : null;
      if (weekId) loadWeeklyLeaderboard(weekId);
    });
  }
  if (name === "players")       { loadPlayers(); loadLeaderboard(); loadTop(); }
  if (name === "teams")         loadTeams();
  if (name === "schedule")      loadSchedule();
  if (name === "howtoplay")     loadHowToPlay();
  if (name === "admin")  { if (!activeUserId || !activeIsAdmin) return; loadWeights(); loadUsers(); loadCodes(); loadAuditLog(); }
}

function setStatus(id, msg, ok = true) {
  const el = document.getElementById(id);
  el.textContent = Array.isArray(msg) ? msg.map(e => e.msg ?? JSON.stringify(e)).join("; ") : (msg ?? "Unknown error");
  el.className = "status " + (ok ? "ok" : "err");
}

function toggleScoringInfo() {
  const el = document.getElementById("scoringInfo");
  if (el) el.style.display = el.style.display === "none" ? "" : "none";
}

function _escHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function playerLink(id, name) {
  return `<span class="entity-link" onclick="openPlayerModal(${id})">${_escHtml(name)}</span>`;
}

function teamLink(id, name) {
  if (!id) return _escHtml(name) || "—";
  return `<span class="entity-link" onclick="openTeamModal(${id})">${_escHtml(name)}</span>`;
}
