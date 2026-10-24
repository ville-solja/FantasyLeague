async function loadProfile() {
  _twitchMergeDismissed = false;
  document.getElementById("profileUsername").value = activeUsername || "";
  document.getElementById("pwUsername").value = activeUsername || "";
  document.getElementById("playerIdStatus").textContent = "";
  document.getElementById("usernameStatus").textContent = "";
  _renderRenameHint();
  _renderPlayerIdentity({});
  loadTwitchConnection();
  try {
    const res = await fetch(`${API}/profile/${activeUserId}`);
    const data = await res.json();
    document.getElementById("profileAdminBadge").innerHTML = adminBadgeHtml(data.is_admin);
    _renderPlayerIdentity(data);
    const tags = data.tags || [];
    const container = document.getElementById("profileTagsContainer");
    if (container) {
      container.innerHTML = tags.length
        ? tags.map(t => tagBadgeHtml(t)).join("")
        : `<span class="profile-tags-empty">No tags</span>`;
    }
    const gapHint = document.getElementById("profileTagGapHint");
    if (gapHint) {
      gapHint.style.display = (tags.length > 0 && !data.player_id) ? "block" : "none";
    }
    _renderPastSeasons(data.past_seasons || []);
    loadSessions();
  } catch (e) {
    setStatus("playerIdStatus", e.message, false);
  }
}

// ---------------------------------------------------------------------------
// Player identity (issue #188): one panel for the Steam link, the league player
// and the tags. Only Steam links an account to a player (issues #150, #209); with
// LOGIN_METHOD=password there is no player linking. Profile only ever learns linked
// yes/no, never the Steam id.
// ---------------------------------------------------------------------------

/** The panel's state: "steam_required" (LOGIN_METHOD=password: no player linking),
 *  "not_linked", "linked" (with a league player) or "linked_no_match". */
function playerIdentityState(loginMethod, me, profile) {
  const steam = loginMethod === "both" || loginMethod === "steam_signup";
  if (!steam) return "steam_required";
  if (me && me.steam_linked) return profile && profile.player_name ? "linked" : "linked_no_match";
  return "not_linked";
}

function _renderPlayerIdentity(profile) {
  const me = {steam_linked: activeSteamLinked, has_password: activeHasPassword, is_demo: activeIsDemo};
  const ui = steamUiState(_loginMethod, me);
  const state = playerIdentityState(_loginMethod, me, profile);
  const show = (id, on) => { document.getElementById(id).style.display = on ? "" : "none"; };
  show("identitySteamLinked", state === "linked" || state === "linked_no_match");
  show("identityNotLinkedState", state === "not_linked");
  show("identityNoMatch", state === "linked_no_match");
  show("identitySteamRequired", state === "steam_required");
  show("btnLinkSteam", ui.linkSteam);
  show("btnUnlinkSteam", ui.unlinkSteam);
  show("identitySteamNote", ui.linkSteam);
  show("steamLinkReminder", ui.linkReminder);
  // A Steam-only account has no password to change.
  show("changePasswordForm", activeHasPassword);
  show("profileNoPasswordNote", !activeHasPassword);
  if (state === "linked") {
    _showLinkedPlayer(profile.player_name, profile.player_avatar_url, profile.player_team_name);
  } else {
    document.getElementById("profilePlayerPreview").style.display = "none";
  }
}

function _showLinkedPlayer(name, avatarUrl, teamName) {
  showPlayerPreview(name, avatarUrl);
  const label = document.getElementById("profilePlayerSource");
  label.textContent = "Verified with Steam";
  label.className = "player-source player-source-verified";
  document.getElementById("profilePlayerTeam").textContent = teamName || "";
}

function _renderRenameHint() {
  const hint = document.getElementById("profileRenameHint");
  if (!hint) return;
  if (activeUsernameChangeAvailableAt) {
    const when = new Date(activeUsernameChangeAvailableAt * 1000).toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
    hint.textContent = `You can rename again on ${when}.`;
    hint.style.display = "";
  } else {
    hint.textContent = "";
    hint.style.display = "none";
  }
}

// Sessions list (issue #117). Built with createElement/textContent only.
async function loadSessions() {
  const tbody = document.getElementById("profileSessionsBody");
  if (!tbody) return;
  try {
    const res = await fetch(`${API}/sessions`);
    const data = await res.json();
    if (!res.ok) return setStatus("profileSessionsStatus", data.detail, false);
    _renderSessions(data);
  } catch (e) {
    setStatus("profileSessionsStatus", e.message, false);
  }
}

function _renderSessions(rows) {
  const tbody = document.getElementById("profileSessionsBody");
  tbody.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.textContent = "No active sessions";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  rows.forEach(s => {
    const tr = document.createElement("tr");
    const created = document.createElement("td");
    created.textContent = new Date(Number(s.created_at) * 1000).toLocaleString();
    const lastSeen = document.createElement("td");
    lastSeen.textContent = new Date(Number(s.last_seen_at) * 1000).toLocaleString()
      + (s.current ? " (this device)" : "");
    const action = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "secondary";
    btn.textContent = "Sign out";
    btn.addEventListener("click", () => signOutSession(s.id, s.current));
    action.appendChild(btn);
    tr.append(created, lastSeen, action);
    tbody.appendChild(tr);
  });
}

async function signOutSession(sessionId, isCurrent) {
  try {
    const res = await fetch(`${API}/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return setStatus("profileSessionsStatus", data.detail || "Could not sign out that session", false);
    }
    if (isCurrent) return _clearLocalAuthState();
    setStatus("profileSessionsStatus", "Session signed out");
    loadSessions();
  } catch (e) {
    setStatus("profileSessionsStatus", e.message, false);
  }
}

function _ordinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function _renderPastSeasons(seasons) {
  const panel = document.getElementById("profilePastSeasonsPanel");
  const container = document.getElementById("profilePastSeasonsContainer");
  if (!panel || !container) return;
  if (!seasons.length) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";
  container.innerHTML = seasons.map(s =>
    `<div>${_escHtml(s.season_label)} — ${_ordinal(s.rank)}, ${Number(s.points).toFixed(1)} pts</div>`
  ).join("");
}

// ---------------------------------------------------------------------------
// Twitch connection (issue #160). Twitch sign-in replaces the old link code:
// Connect navigates to GET /auth/twitch/start, which redirects to Twitch (or back
// here with ?twitch=reauth_required when the password check is missing). Twitch
// returns to /auth/twitch/callback, which redirects to /#profile?twitch=<key>.
// No Twitch id ever reaches the page.
// ---------------------------------------------------------------------------

const _TWITCH_RETURN_MESSAGES = {
  connected:        ["Twitch connected.", true],
  connected_bonus:  [() => Number.isInteger(_twitchConnectBonusTokens) && _twitchConnectBonusTokens > 0
    ? `Twitch connected. You received ${_twitchConnectBonusTokens} Twitch starter tokens.`
    : "Twitch connected. You received your Twitch starter tokens.", true],
  merge_ready:      ["Twitch connected. Your Twitch collection is waiting below.", true],
  cancelled:        ["Twitch sign-in was cancelled. Nothing was changed.", false],
  failed:           ["Twitch sign-in did not complete. Nothing was changed. Try again.", false],
  no_session:       ["Log in to Kana Cards first, then connect Twitch.", false],
  login_required:   ["Log in to Kana Cards first, then connect Twitch.", false],
  in_use:           ["This Twitch account is connected to another Kana Cards account", false],
  disconnect_first: ["Disconnect your current Twitch account first", false],
  unavailable:      ["Connecting Twitch is not available right now.", false],
};

let _twitchMergeDismissed = false;

function _showTwitchState(id) {
  ["twitchConnectState", "twitchUnavailableState", "twitchConnectedState"].forEach(el => {
    document.getElementById(el).style.display = el === id ? "block" : "none";
  });
}

async function loadTwitchConnection() {
  try {
    const res = await fetch(`${API}/twitch/connection`);
    const data = await res.json();
    if (!res.ok) return setStatus("twitchStatus", data.detail, false);
    _renderTwitchConnection(data);
  } catch (e) {
    setStatus("twitchStatus", e.message, false);
  }
}

function _renderTwitchConnection(data) {
  if (data.connected) _showTwitchState("twitchConnectedState");
  else _showTwitchState(data.available ? "twitchConnectState" : "twitchUnavailableState");
  const activity = document.getElementById("twitchLastActivity");
  activity.textContent = data.last_twitch_activity_at
    ? `Last Twitch activity: ${new Date(Number(data.last_twitch_activity_at) * 1000).toLocaleString()}`
    : "Last Twitch activity: none yet";

  const prompt = document.getElementById("twitchMergePrompt");
  const pending = data.pending_merge;
  if (pending && !_twitchMergeDismissed) {
    const text = document.getElementById("twitchMergeText");
    if (data.merge_used) {
      text.textContent = `Your Twitch collection: ${pending.cards} cards, ${pending.tokens} tokens. This account has already added a Twitch collection once, so this one stays in the Twitch panel.`;
      document.getElementById("twitchMergeActions").style.display = "none";
    } else {
      text.textContent = `Your Twitch collection: ${pending.cards} cards, ${pending.tokens} tokens. Add it to this account?` +
        _mergePromptNote(pending);
      document.getElementById("twitchMergeActions").style.display = "";
    }
    prompt.style.display = "block";
  } else {
    prompt.style.display = "none";
  }
  document.getElementById("twitchGuidance").style.display =
    data.connected && !pending && !data.merge_used ? "block" : "none";
}

// Issue #187: one Twitch starter per website account. When this account already got
// the Twitch starter bonus on connect, the merge takes that bonus back: from the
// collection's tokens first, then (if the collection's starter was spent) from this
// account's balance.
function _starterDeductedNote(n) {
  return Number.isInteger(n) && n > 0
    ? ` (${n} Twitch starter tokens stay behind: this account already received the Twitch starter bonus.)`
    : "";
}

function _mergePromptNote(pending) {
  const change = pending.balance_change;
  if (Number.isInteger(change) && change < 0) {
    return ` Adding it removes ${-change} tokens from your balance: this account already received the Twitch starter bonus, and the collection's starter tokens were spent.`;
  }
  return _starterDeductedNote(pending.starter_deducted);
}

function _mergeResultNote(data) {
  if (Number.isInteger(data.from_website) && data.from_website > 0) {
    return `. ${data.from_website} tokens were removed from your balance: this account already received the Twitch starter bonus.`;
  }
  return _starterDeductedNote(data.starter_deducted);
}

function connectTwitch() {
  // A top-level navigation: the server checks the recent password confirmation and
  // sends the browser to Twitch, or back here asking for the password.
  window.location.href = `${API}/auth/twitch/start`;
}

async function disconnectTwitch() {
  if (!confirm("Disconnect Twitch from this account? Your cards and tokens stay here. In the Twitch panel you are then not joined until you join again.")) return;
  try {
    const res = await adminFetch(`${API}/twitch/disconnect`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("twitchStatus", data.detail, false);
    setStatus("twitchStatus", "Twitch disconnected.");
    loadTwitchConnection();
  } catch (e) {
    setStatus("twitchStatus", e.message, false);
  }
}

async function confirmTwitchMerge() {
  try {
    const res = await adminFetch(`${API}/twitch/merge/confirm`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setStatus("twitchStatus", data.detail, false);
      return loadTwitchConnection();
    }
    setStatus("twitchStatus", `${data.cards} cards and ${data.tokens} tokens added` +
      _mergeResultNote(data));
    loadTwitchConnection();
    if (typeof loadMe === "function") loadMe();
  } catch (e) {
    setStatus("twitchStatus", e.message, false);
  }
}

function dismissTwitchMerge() {
  // "Not now": nothing changes on the server; the prompt returns on the next Profile visit.
  _twitchMergeDismissed = true;
  document.getElementById("twitchMergePrompt").style.display = "none";
}

/** Reads /#profile?twitch=<key> left by the Twitch sign-in redirects, strips it from
 *  the address bar, opens Profile and shows the message. Returns true when handled. */
function handleTwitchReturn() {
  const hash = window.location.hash || "";
  if (!hash.startsWith("#profile")) return false;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const key = new URLSearchParams(query).get("twitch");
  history.replaceState(null, "", window.location.pathname);
  if (!activeUserId) return false;
  switchTab("profile");
  if (!key) return true;
  _twitchMergeDismissed = false;
  if (key === "reauth_required") {
    _promptReauth("connectTwitch").then(ok => {
      if (ok) connectTwitch();
      else setStatus("twitchStatus", "Confirm your password to connect Twitch.", false);
    });
    return true;
  }
  const msg = _TWITCH_RETURN_MESSAGES[key];
  if (msg) setStatus("twitchStatus", typeof msg[0] === "function" ? msg[0]() : msg[0], msg[1]);
  return true;
}

// When Twitch refuses the sign-in before reaching /auth/twitch/callback (most often
// redirect_mismatch: the callback URL is not registered on the client), it sends the
// browser to a registered redirect URL with ?error=&error_description=&state=. Only
// the error code, checked against [a-z_], ever reaches the page; error_description
// is never shown.
const _TWITCH_ERROR_MESSAGES = {
  redirect_mismatch: "Twitch sign-in failed: this site's Twitch redirect URL isn't registered with Twitch. Tell the league admins.",
  access_denied:     _TWITCH_RETURN_MESSAGES.cancelled[0],
};

function handleTwitchErrorReturn() {
  const q = new URLSearchParams(window.location.search);
  if (!q.has("error") || !q.has("state")) return false;
  const raw = q.get("error") || "";
  const code = /^[a-z_]{1,64}$/.test(raw) ? raw : "unknown";
  ["error", "error_description", "error_uri", "state"].forEach(k => q.delete(k));
  const rest = q.toString();
  history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : "") + window.location.hash);
  if (!activeUserId) return true;
  switchTab("profile");
  setStatus("twitchStatus", (Object.hasOwn(_TWITCH_ERROR_MESSAGES, code) && _TWITCH_ERROR_MESSAGES[code]) ||
    `Twitch sign-in did not complete. Nothing was changed. Try again. (${code})`, false);
  return true;
}

// ---------------------------------------------------------------------------
// Steam link (issue #150). Link navigates to GET /auth/steam/start?purpose=link,
// which needs a recent identity check (back here with ?steam=reauth_required
// otherwise; handleSteamReturn in app-auth.js opens the password prompt and starts
// again). Profile only ever learns linked yes/no, never the Steam id.
// ---------------------------------------------------------------------------

function linkSteam() {
  // A top-level navigation: the server checks the recent identity confirmation and
  // sends the browser to steamcommunity.com, or back here asking for the password.
  window.location.href = `${API}/auth/steam/start?purpose=link`;
}

async function unlinkSteam() {
  if (!confirm("Unlink Steam from this account? This also removes your player link. You can link Steam again later.")) return;
  try {
    const res = await adminFetch(`${API}/profile/steam/unlink`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setStatus("steamStatus", data.detail || "Could not unlink Steam", false);
    setStatus("steamStatus", "Steam unlinked.");
    await loadMe();
    loadProfile();
  } catch (e) {
    setStatus("steamStatus", e.message, false);
  }
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
    activeUsernameChangeAvailableAt = data.username_change_available_at ?? null;
    _renderRenameHint();
    document.getElementById("pwUsername").value = activeUsername;
    localStorage.setItem("username", activeUsername);
    document.getElementById("headerUserLabel").textContent = activeUsername;
    setStatus("usernameStatus", "Username updated");
  } catch (e) {
    setStatus("usernameStatus", e.message, false);
  }
}

document.getElementById("changePasswordForm").addEventListener("submit", e => { e.preventDefault(); changePassword(); });

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
    loadSessions();  // other devices were signed out
  } catch (e) {
    setStatus("passwordStatus", e.message, false);
  }
}

async function logoutEverywhere() {
  if (!confirm("Log out on every device, including this one?")) return;
  try {
    const res = await fetch(`${API}/logout-everywhere`, { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return setStatus("logoutEverywhereStatus", data.detail || "Could not log out everywhere", false);
    }
    _clearLocalAuthState();
  } catch (e) {
    setStatus("logoutEverywhereStatus", e.message, false);
  }
}

// ---------------------------------------------------------------------------
// Own player card popup (issue #188). GET /me returns own_card_grant until the
// player dismisses it (POST /profile/own-card-grant/seen). A granted card opens in
// the card viewer (#revealModal); "already owned" uses a small notice. Text is set
// with textContent only.
// ---------------------------------------------------------------------------

let _ownCardGrantShown = false;

function ownCardGrantText(grant) {
  const name = (grant && grant.player_name) || "your player";
  return grant && grant.outcome === "granted"
    ? `Your own player card. You linked Steam, and you play in this season's league, so this card of ${name} is yours.`
    : `You already have a card of ${name}, so no new card was added.`;
}

async function showOwnCardGrant() {
  const grant = activeOwnCardGrant;
  if (!grant || _ownCardGrantShown) return;
  _ownCardGrantShown = true;
  if (grant.outcome === "granted" && Number.isInteger(grant.card_id)) {
    let card = {id: grant.card_id, card_type: "common", player_name: grant.player_name};
    try {
      const res = await fetch(`${API}/cards/${grant.card_id}`);
      if (res.ok) card = {...(await res.json()), id: grant.card_id};
    } catch (_) { /* the viewer still shows the image and the text */ }
    showCard(card, ownCardGrantText(grant), {showActionBtn: true});
    document.getElementById("revealDestination").classList.add("reveal-own-card-note");
    document.getElementById("revealActionBtn").textContent = "Nice";
    _revealOnClose = dismissOwnCardGrant;
    const modal = document.getElementById("revealModal");
    modal.onclick = e => { if (e.target === modal) closeReveal(); };
    return;
  }
  document.getElementById("ownCardNoticeText").textContent = ownCardGrantText(grant);
  document.getElementById("ownCardNoticeModal").classList.remove("hidden");
}

async function dismissOwnCardGrant() {
  document.getElementById("ownCardNoticeModal").classList.add("hidden");
  if (!activeOwnCardGrant) return;
  activeOwnCardGrant = null;
  try {
    await fetch(`${API}/profile/own-card-grant/seen`, { method: "POST" });
  } catch (_) { /* shown again on the next page load */ }
}
