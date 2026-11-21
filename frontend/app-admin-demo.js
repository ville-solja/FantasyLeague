// ---------------------------------------------------------------------------
// Demo Mode — clock override, disposable account seeding and season scenarios.
// Env-gated (window.demoMode, set from GET /config in app-globals.js) and
// admin-only: the panel markup is injected, and GET /admin/demo/clock requested,
// only when demo mode is on and activeIsAdmin. applyAuthState() calls
// renderDemoModePanel() after every sign-in state change.
// ---------------------------------------------------------------------------

function renderDemoModePanel() {
  const container = document.getElementById("demoModePanelContainer");
  if (!container) return;
  if (!window.demoMode || !activeIsAdmin) {
    container.innerHTML = "";
    return;
  }
  if (document.getElementById("demoModePanel")) return; // already rendered

  container.innerHTML = `
    <div class="panel admin-panel" id="demoModePanel">
      <div class="admin-panel-head">
        <div class="admin-panel-heading">
          <h3 class="admin-panel-title">Demo Mode</h3>
          <p class="admin-panel-desc">Override the app's simulated "now" to walk through pre-lock, lock, and post-week
            scoring on demand, seed disposable accounts pre-loaded with random cards, or load a whole test season.</p>
        </div>
      </div>

      <h3 style="margin-bottom:8px;">Clock</h3>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px;align-items:center;">
        <input id="demoClockInput" type="datetime-local" title="Simulated now" />
        <button onclick="setDemoClock()">Set Clock</button>
        <button class="secondary" onclick="clearDemoClock()">Clear Clock</button>
        <button class="secondary" onclick="loadDemoClock()">Refresh</button>
      </div>
      <div style="font-size:0.8rem;color:#888;margin-bottom:12px;" id="demoClockDisplay">—</div>

      <h3 style="margin-bottom:8px;">Seed Demo Accounts</h3>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;align-items:center;">
        <input id="demoSeedCount" type="number" placeholder="Accounts" min="1" max="100" style="max-width:100px;" />
        <input id="demoSeedCards" type="number" placeholder="Cards each" min="0" max="50" style="max-width:100px;" />
        <button onclick="seedDemoAccounts()">Seed Accounts</button>
      </div>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr><th>Username</th><th>Password</th></tr></thead>
          <tbody id="demoSeedResultsBody"><tr><td colspan="2" style="color:#444">—</td></tr></tbody>
        </table>
      </div>
      <h3 style="margin:16px 0 8px;">Season Scenario</h3>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px;align-items:center;">
        <select id="demoScenarioSelect" title="Scenario" onchange="describeDemoScenario()">
          <option value="pre-season">pre-season</option>
          <option value="mid-season" selected>mid-season</option>
          <option value="season-end">season-end</option>
        </select>
        <button class="danger" onclick="askLoadDemoScenario()">Load Scenario…</button>
      </div>
      <div style="font-size:0.8rem;color:#888;margin-bottom:8px;" id="demoScenarioDesc"></div>
      <div id="demoScenarioConfirm" hidden style="margin-bottom:8px;">
        <p style="margin:0 0 8px;">Replaces every account except yours and all game data with the
          <strong id="demoScenarioConfirmName"></strong> scenario. Player accounts use the
          DEMO_ACCOUNT_PASSWORD password; scenario-admin gets a new password, shown once.</p>
        <label for="demoScenarioConfirmInput" style="display:block;margin-bottom:4px;">Type
          <strong id="demoScenarioConfirmPhrase"></strong> to confirm</label>
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
          <input id="demoScenarioConfirmInput" type="text" autocomplete="off" spellcheck="false" />
          <button class="danger" onclick="loadDemoScenario()">Load</button>
          <button class="secondary" onclick="cancelDemoScenario()">Cancel</button>
        </div>
        <div class="status err" id="demoScenarioConfirmStatus"></div>
      </div>
      <div style="font-size:0.8rem;margin-bottom:8px;" id="demoScenarioResult"></div>
      <div style="font-size:0.8rem;margin-bottom:8px;" id="demoScenarioAdminPassword" hidden></div>

      <h3 style="margin:16px 0 8px;">Snapshots</h3>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px;align-items:center;">
        <input id="demoSnapshotName" type="text" placeholder="Name (letters, digits, -)" maxlength="40"
          pattern="[A-Za-z0-9-]{1,40}" autocomplete="off" spellcheck="false" title="Snapshot name" />
        <button onclick="saveDemoSnapshot()">Save Snapshot</button>
        <button class="secondary" onclick="loadDemoSnapshots()">Refresh</button>
      </div>
      <div style="overflow-x:auto;margin-bottom:8px;">
        <table>
          <thead><tr><th>Name</th><th>Size</th><th>Saved</th><th></th></tr></thead>
          <tbody id="demoSnapshotsBody"><tr><td colspan="4" style="color:#444">—</td></tr></tbody>
        </table>
      </div>
      <div id="demoSnapshotConfirm" hidden style="margin-bottom:8px;">
        <p style="margin:0 0 8px;">Replaces all data with snapshot <strong id="demoSnapshotConfirmName"></strong>;
          everyone else is logged out. You stay logged in.</p>
        <label for="demoSnapshotConfirmInput" style="display:block;margin-bottom:4px;">Type
          <strong id="demoSnapshotConfirmPhrase"></strong> to confirm</label>
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
          <input id="demoSnapshotConfirmInput" type="text" autocomplete="off" spellcheck="false" />
          <button class="danger" onclick="restoreDemoSnapshot()">Restore</button>
          <button class="secondary" onclick="cancelDemoSnapshot()">Cancel</button>
        </div>
        <div class="status err" id="demoSnapshotConfirmStatus"></div>
      </div>
      <div class="status" id="demoModeStatus"></div>
    </div>
  `;
  describeDemoScenario();
  loadDemoClock();
  loadDemoSnapshots();
}

// Issue #145: season scenarios (POST /admin/demo/scenario). In-page confirmation, then
// adminFetch, which asks for the password again when the re-auth is not recent.
const DEMO_SCENARIOS = {
  "pre-season": "10 open weeks and no matches. Accounts have starter tokens and 3 cards each.",
  "mid-season": "Weeks 1–5 locked and scored, week 6 open for edits. Benches, a bench substitution, MVPs, one unparsed and one excluded match.",
  "season-end": "All 10 weeks locked and scored, with no archive yet, so End Season can run.",
};

function describeDemoScenario() {
  const sel = document.getElementById("demoScenarioSelect");
  const desc = document.getElementById("demoScenarioDesc");
  if (sel && desc) desc.textContent = DEMO_SCENARIOS[sel.value] || "";
}

function askLoadDemoScenario() {
  const name = document.getElementById("demoScenarioSelect").value;
  document.getElementById("demoScenarioConfirmName").textContent = name;
  document.getElementById("demoScenarioConfirmPhrase").textContent = ADMIN_CONFIRM_PHRASES.demo_scenario;
  document.getElementById("demoScenarioConfirmInput").value = "";
  document.getElementById("demoScenarioConfirmStatus").textContent = "";
  document.getElementById("demoScenarioConfirm").hidden = false;
}

function cancelDemoScenario() {
  document.getElementById("demoScenarioConfirm").hidden = true;
}

async function loadDemoScenario() {
  const name = document.getElementById("demoScenarioSelect").value;
  const typed = document.getElementById("demoScenarioConfirmInput").value.trim();
  if (typed.toUpperCase() !== ADMIN_CONFIRM_PHRASES.demo_scenario) {
    document.getElementById("demoScenarioConfirmStatus").textContent =
      `Type "${ADMIN_CONFIRM_PHRASES.demo_scenario}" to confirm.`;
    return;
  }
  document.getElementById("demoScenarioConfirm").hidden = true;
  const adminPw = document.getElementById("demoScenarioAdminPassword");
  adminPw.hidden = true;
  adminPw.textContent = "";
  setStatus("demoModeStatus", `Loading ${name}…`);
  try {
    const res = await adminFetch(`${API}/admin/demo/scenario`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name, confirm: typed}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `Loading failed (${res.status})`;
      return setStatus("demoModeStatus", detail, false);
    }
    const c = data.counts || {};
    document.getElementById("demoScenarioResult").textContent =
      `${data.scenario}: ${c.locked_weeks} of ${c.weeks} weeks locked, ${c.matches} matches, ` +
      `${c.cards} cards, ${c.substitutions} substitution(s). Accounts: ${(data.accounts || []).join(", ")}`;
    if (data.admin_password) {
      adminPw.textContent = `scenario-admin password (shown once, copy it now): ${data.admin_password}`;
      adminPw.hidden = false;
    }
    setStatus("demoModeStatus", `Scenario ${data.scenario} loaded`);
    loadDemoClock();
    if (typeof loadAdminWeeks === "function") loadAdminWeeks();
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

async function loadDemoClock() {
  if (!window.demoMode || !activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/demo/clock`);
    const data = await res.json();
    if (!res.ok) return setStatus("demoModeStatus", data.detail, false);
    const display = document.getElementById("demoClockDisplay");
    if (display) {
      const override = data.override_timestamp
        ? new Date(data.override_timestamp * 1000).toLocaleString()
        : "unset (real time)";
      const effective = new Date(data.effective_now * 1000).toLocaleString();
      display.textContent = `Override: ${override} · Effective now: ${effective}`;
    }
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

async function setDemoClock() {
  const val = document.getElementById("demoClockInput").value;
  if (!val) return setStatus("demoModeStatus", "Pick a date/time first", false);
  const timestamp = Math.floor(new Date(val).getTime() / 1000);
  try {
    const res = await fetch(`${API}/admin/demo/clock`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({timestamp}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("demoModeStatus", data.detail, false);
    setStatus("demoModeStatus", "Clock set — auto-lock re-run");
    loadDemoClock();
    if (typeof loadAdminWeeks === "function") loadAdminWeeks();
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

async function clearDemoClock() {
  try {
    const res = await fetch(`${API}/admin/demo/clock`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) return setStatus("demoModeStatus", data.detail, false);
    setStatus("demoModeStatus", "Clock override cleared");
    document.getElementById("demoClockInput").value = "";
    loadDemoClock();
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

async function seedDemoAccounts() {
  const countVal = document.getElementById("demoSeedCount").value;
  const cardsVal = document.getElementById("demoSeedCards").value;
  const body = {};
  if (countVal) body.count = parseInt(countVal);
  if (cardsVal) body.cards_per_account = parseInt(cardsVal);
  try {
    const res = await fetch(`${API}/admin/demo/seed-accounts`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("demoModeStatus", data.detail, false);
    const tbody = document.getElementById("demoSeedResultsBody");
    tbody.innerHTML = "";
    data.accounts.forEach(a => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${_escHtml(a.username)}</td><td style="font-family:monospace;">${_escHtml(a.password)}</td>`;
      tbody.appendChild(tr);
    });
    setStatus("demoModeStatus", `Created ${data.accounts.length} account(s)`);
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

// Issue #147: named database snapshots. Save and list need admin only; Restore opens
// an in-page confirmation with the typed phrase, then adminFetch (password prompt when
// the re-auth is not recent). A restore replaces every row, so the page reloads.
let _demoSnapshotPending = null;

function _formatSnapshotSize(bytes) {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

async function loadDemoSnapshots() {
  if (!window.demoMode || !activeIsAdmin) return;
  const tbody = document.getElementById("demoSnapshotsBody");
  if (!tbody) return;
  try {
    const res = await fetch(`${API}/admin/demo/snapshots`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setStatus("demoModeStatus", data.detail || `Loading snapshots failed (${res.status})`, false);
    const snaps = data.snapshots || [];
    tbody.innerHTML = "";
    if (!snaps.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.style.color = "#444";
      td.textContent = "No snapshots yet";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    snaps.forEach(s => {
      const tr = document.createElement("tr");
      const cells = [s.name, _formatSnapshotSize(s.size_bytes), new Date(s.saved_at * 1000).toLocaleString()];
      cells.forEach(text => {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      const td = document.createElement("td");
      const btn = document.createElement("button");
      btn.className = "danger";
      btn.textContent = "Restore…";
      btn.addEventListener("click", () => askRestoreDemoSnapshot(s.name));
      td.appendChild(btn);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

async function saveDemoSnapshot() {
  const name = document.getElementById("demoSnapshotName").value.trim();
  if (!/^[A-Za-z0-9-]{1,40}$/.test(name)) {
    return setStatus("demoModeStatus", "Name: 1–40 letters, digits or hyphens", false);
  }
  try {
    const res = await fetch(`${API}/admin/demo/snapshots`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `Saving failed (${res.status})`;
      return setStatus("demoModeStatus", detail, false);
    }
    document.getElementById("demoSnapshotName").value = "";
    setStatus("demoModeStatus", `Snapshot ${data.name} saved`);
    loadDemoSnapshots();
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}

function askRestoreDemoSnapshot(name) {
  _demoSnapshotPending = name;
  document.getElementById("demoSnapshotConfirmName").textContent = name;
  document.getElementById("demoSnapshotConfirmPhrase").textContent = ADMIN_CONFIRM_PHRASES.demo_snapshot_restore;
  document.getElementById("demoSnapshotConfirmInput").value = "";
  document.getElementById("demoSnapshotConfirmStatus").textContent = "";
  document.getElementById("demoSnapshotConfirm").hidden = false;
}

function cancelDemoSnapshot() {
  _demoSnapshotPending = null;
  document.getElementById("demoSnapshotConfirm").hidden = true;
}

async function restoreDemoSnapshot() {
  const name = _demoSnapshotPending;
  if (!name) return;
  const typed = document.getElementById("demoSnapshotConfirmInput").value.trim();
  if (typed.toUpperCase() !== ADMIN_CONFIRM_PHRASES.demo_snapshot_restore) {
    document.getElementById("demoSnapshotConfirmStatus").textContent =
      `Type "${ADMIN_CONFIRM_PHRASES.demo_snapshot_restore}" to confirm.`;
    return;
  }
  document.getElementById("demoSnapshotConfirm").hidden = true;
  _demoSnapshotPending = null;
  setStatus("demoModeStatus", `Restoring ${name}…`);
  try {
    const res = await adminFetch(`${API}/admin/demo/snapshots/${encodeURIComponent(name)}/restore`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({confirm: typed}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `Restoring failed (${res.status})`;
      return setStatus("demoModeStatus", detail, false);
    }
    setStatus("demoModeStatus", `Snapshot ${data.restored} restored. Reloading…`);
    location.reload();
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}
