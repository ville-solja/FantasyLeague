// ---------------------------------------------------------------------------
// Demo Mode — clock override + disposable account seeding.
// Entirely env-gated (window.demoMode, set from GET /config in app-globals.js):
// the panel markup is only injected into the DOM when true.
// ---------------------------------------------------------------------------

function renderDemoModePanel() {
  const container = document.getElementById("demoModePanelContainer");
  if (!container) return;
  if (!window.demoMode) {
    container.innerHTML = "";
    return;
  }
  if (document.getElementById("demoModePanel")) return; // already rendered

  container.innerHTML = `
    <div class="panel" id="demoModePanel">
      <h2>Demo Mode</h2>
      <p style="font-size:0.8rem;color:#555;margin-bottom:12px;">
        Override the app's simulated "now" to walk through pre-lock, lock, and post-week
        scoring on demand, and seed disposable accounts pre-loaded with random cards.
      </p>

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
      <div class="status" id="demoModeStatus"></div>
    </div>
  `;
  loadDemoClock();
}

async function loadDemoClock() {
  if (!window.demoMode) return;
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
      tr.innerHTML = `<td>${a.username}</td><td style="font-family:monospace;">${a.password}</td>`;
      tbody.appendChild(tr);
    });
    setStatus("demoModeStatus", `Created ${data.accounts.length} account(s)`);
  } catch (e) {
    setStatus("demoModeStatus", e.message, false);
  }
}
