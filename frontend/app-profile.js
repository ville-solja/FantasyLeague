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
