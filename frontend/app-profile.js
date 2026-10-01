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
