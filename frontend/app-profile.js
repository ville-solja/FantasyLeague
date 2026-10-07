async function loadProfile() {
  _twitchMergeDismissed = false;
  document.getElementById("profileUsername").value = activeUsername || "";
  document.getElementById("pwUsername").value = activeUsername || "";
  document.getElementById("profilePlayerPreview").style.display = "none";
  document.getElementById("playerIdStatus").textContent = "";
  document.getElementById("usernameStatus").textContent = "";
  try {
    const res = await fetch(`${API}/profile/${activeUserId}`);
    const data = await res.json();
    document.getElementById("profileAdminBadge").innerHTML = adminBadgeHtml(data.is_admin);
    if (data.player_id) {
      document.getElementById("profilePlayerId").value = data.player_id;
      if (data.player_name) _showLinkedPlayer(data.player_name, data.player_avatar_url, data.player_verified === true);
    } else {
      document.getElementById("profilePlayerId").value = "";
    }
    _renderRenameHint();
    loadTwitchConnection();
    _renderSteamProfile();
    const tags = data.tags || [];
    const container = document.getElementById("profileTagsContainer");
    if (container) {
      container.innerHTML = tags.length
        ? tags.map(t => `<span class="tag-chip">${_escHtml(t.label)}</span>`).join("")
        : `<span style="color:#555;font-size:0.85rem;">No tags</span>`;
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

// Issue #169: a claimed player shows its avatar only when the id is verified through
// Steam; a typed-in id is labelled "Self-reported", as other players see it.
function _showLinkedPlayer(name, avatarUrl, verified) {
  showPlayerPreview(name, verified ? avatarUrl : null);
  const label = document.getElementById("profilePlayerSource");
  label.textContent = verified ? "Verified with Steam" : "Self-reported";
  label.className = verified ? "player-source player-source-verified" : "player-source";
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
      text.textContent = `Your Twitch collection: ${pending.cards} cards, ${pending.tokens} tokens. Add it to this account?`;
      document.getElementById("twitchMergeActions").style.display = "";
    }
    prompt.style.display = "block";
  } else {
    prompt.style.display = "none";
  }
  document.getElementById("twitchGuidance").style.display =
    data.connected && !pending && !data.merge_used ? "block" : "none";
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
    setStatus("twitchStatus", `${data.cards} cards and ${data.tokens} tokens added`);
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
    _promptReauth().then(ok => {
      if (ok) connectTwitch();
      else setStatus("twitchStatus", "Confirm your password to connect Twitch.", false);
    });
    return true;
  }
  const msg = _TWITCH_RETURN_MESSAGES[key];
  if (msg) setStatus("twitchStatus", msg[0], msg[1]);
  return true;
}

// ---------------------------------------------------------------------------
// Steam link (issue #150). Link navigates to GET /auth/steam/start?purpose=link,
// which needs a recent identity check (back here with ?steam=reauth_required
// otherwise; handleSteamReturn in app-auth.js opens the password prompt and starts
// again). Profile only ever learns linked yes/no, never the Steam id.
// ---------------------------------------------------------------------------

function _renderSteamProfile() {
  const me = {steam_linked: activeSteamLinked, has_password: activeHasPassword, is_demo: activeIsDemo};
  const ui = steamUiState(_loginMethod, me);
  const show = (id, on) => { document.getElementById(id).style.display = on ? "" : "none"; };
  show("steamProfilePanel", ui.profileSteamPanel);
  show("steamUnlinkedState", ui.linkSteam);
  show("steamLinkedState", activeSteamLinked);
  show("btnUnlinkSteam", ui.unlinkSteam);
  show("steamLinkReminder", ui.linkReminder);
  // A Steam-only account has no password to change.
  show("changePasswordForm", activeHasPassword);
  show("profileNoPasswordNote", !activeHasPassword);
  // A linked Steam account sets the verified player id.
  document.getElementById("profilePlayerId").disabled = activeSteamLinked;
  document.getElementById("btnSavePlayerId").disabled = activeSteamLinked;
  show("profilePlayerIdVerified", activeSteamLinked);
}

function linkSteam() {
  // A top-level navigation: the server checks the recent identity confirmation and
  // sends the browser to steamcommunity.com, or back here asking for the password.
  window.location.href = `${API}/auth/steam/start?purpose=link`;
}

async function unlinkSteam() {
  if (!confirm("Unlink Steam from this account? Your verified player id stays. You can link Steam again later.")) return;
  try {
    const res = await adminFetch(`${API}/profile/steam/unlink`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setStatus("steamStatus", data.detail || "Could not unlink Steam", false);
    setStatus("steamStatus", "Steam unlinked.");
    await loadMe();
    _renderSteamProfile();
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
      _showLinkedPlayer(data.player_name, data.player_avatar_url, false);
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
