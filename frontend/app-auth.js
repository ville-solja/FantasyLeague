function applyAuthState() {
  const loggedIn = !!activeUserId;

  const userLabel = document.getElementById("headerUserLabel");
  userLabel.textContent    = loggedIn ? activeUsername : "";
  userLabel.style.display  = loggedIn ? "" : "none";
  document.getElementById("headerLoginBtn").style.display  = loggedIn ? "none" : "";
  document.getElementById("headerLogoutBtn").style.display = loggedIn ? "" : "none";

  document.getElementById("tab-btn-team").style.display    = loggedIn ? "" : "none";
  document.getElementById("tab-btn-profile").style.display = loggedIn ? "" : "none";
  document.getElementById("tab-btn-admin").style.display   = (loggedIn && activeIsAdmin) ? "" : "none";

  const tokenEl = document.getElementById("tokenBalance");
  if (tokenEl) tokenEl.style.display = loggedIn ? "flex" : "none";

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

function closeRegisterModal() {
  document.getElementById("registerModal").classList.add("hidden");
}

function showRegister() {
  document.getElementById("loginModal").classList.add("hidden");
  document.getElementById("registerModal").classList.remove("hidden");
  _regClearErrors();
}

function _regFieldErr(inputId, errId, msg) {
  document.getElementById(inputId).classList.add("invalid");
  document.getElementById(errId).textContent = msg;
}

function _regClearField(inputId, errId) {
  document.getElementById(inputId).classList.remove("invalid");
  document.getElementById(errId).textContent = "";
}

function _regClearErrors() {
  ["regUsername", "regEmail", "regPassword"].forEach(id => _regClearField(id, id + "Err"));
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
  _regClearErrors();
  const username = document.getElementById("regUsername").value.trim();
  const email    = document.getElementById("regEmail").value.trim();
  const password = document.getElementById("regPassword").value;

  let valid = true;
  let firstInvalidId = null;
  if (!username) {
    _regFieldErr("regUsername", "regUsernameErr", "Username is required");
    firstInvalidId = firstInvalidId || "regUsername";
    valid = false;
  } else if (username.length > 64) {
    _regFieldErr("regUsername", "regUsernameErr", "Username must be 64 characters or fewer");
    firstInvalidId = firstInvalidId || "regUsername";
    valid = false;
  }
  if (!email) {
    _regFieldErr("regEmail", "regEmailErr", "Email is required");
    firstInvalidId = firstInvalidId || "regEmail";
    valid = false;
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    _regFieldErr("regEmail", "regEmailErr", "Enter a valid email address");
    firstInvalidId = firstInvalidId || "regEmail";
    valid = false;
  }
  if (!password) {
    _regFieldErr("regPassword", "regPasswordErr", "Password is required");
    firstInvalidId = firstInvalidId || "regPassword";
    valid = false;
  } else if (password.length < 6) {
    _regFieldErr("regPassword", "regPasswordErr", "Password must be at least 6 characters");
    firstInvalidId = firstInvalidId || "regPassword";
    valid = false;
  } else if (password.length > 128) {
    _regFieldErr("regPassword", "regPasswordErr", "Password must be 128 characters or fewer");
    firstInvalidId = firstInvalidId || "regPassword";
    valid = false;
  }
  if (!valid) {
    if (firstInvalidId) document.getElementById(firstInvalidId).scrollIntoView({block: "center"});
    return;
  }

  try {
    const res = await fetch(`${API}/register`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, email, password}) });
    const data = await res.json();
    if (!res.ok) {
      const detail = data.detail;
      if (Array.isArray(detail)) {
        detail.forEach(err => {
          const field = err.loc ? err.loc[err.loc.length - 1] : null;
          if (field === "username") _regFieldErr("regUsername", "regUsernameErr", err.msg);
          else if (field === "email") _regFieldErr("regEmail", "regEmailErr", err.msg);
          else if (field === "password") _regFieldErr("regPassword", "regPasswordErr", err.msg);
          else setStatus("registerStatus", err.msg, false);
        });
      } else if (typeof detail === "string" && detail.toLowerCase().includes("username")) {
        _regFieldErr("regUsername", "regUsernameErr", detail);
      } else if (typeof detail === "string" && (detail.toLowerCase().includes("email") || detail.toLowerCase().includes("mail"))) {
        _regFieldErr("regEmail", "regEmailErr", detail);
      } else {
        setStatus("registerStatus", detail, false);
      }
      return;
    }

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
