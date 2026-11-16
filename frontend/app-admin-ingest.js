async function loadWeights() {
  try {
    const res = await fetch(`${API}/weights`);
    const weights = await res.json();
    document.getElementById("weightsBody").innerHTML = weights.map(w => `
      <tr>
        <td>${w.label}</td>
        <td>${w.value}</td>
      </tr>`).join("");
    setStatus("weightsStatus", "");
  } catch (e) {
    setStatus("weightsStatus", e.message, false);
  }
}

async function refreshSchedule() {
  const btn = document.getElementById("scheduleRefreshBtn");
  if (btn) btn.disabled = true;
  setStatus("scheduleRefreshStatus", "Refreshing...");
  try {
    const res = await fetch(`${API}/schedule/refresh`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("scheduleRefreshStatus", data.detail, false);
    const count = data.weeks?.length ?? 0;
    setStatus("scheduleRefreshStatus", count > 0 ? `Done. ${count} weeks loaded.` : (data.error || "No data returned"), count > 0);
  } catch (e) {
    setStatus("scheduleRefreshStatus", e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}


async function loadAuditLog() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/audit-logs`);
    const rows = await res.json();
    if (!res.ok) return setStatus("auditStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("auditBody").innerHTML = "<tr><td colspan='4' style='color:#444'>No entries yet</td></tr>";
      return;
    }
    document.getElementById("auditBody").innerHTML = rows.map(r => {
      const dt = new Date(r.timestamp * 1000).toLocaleString();
      return `<tr>
        <td style="white-space:nowrap;font-size:0.8rem;color:#888;">${dt}</td>
        <td>${r.actor_username ? _escHtml(r.actor_username) : "<em style='color:#555'>system</em>"}</td>
        <td><code style="font-size:0.8rem;">${_escHtml(r.action)}</code></td>
        <td style="font-size:0.8rem;color:#888;">${_escHtml(r.detail || "")}</td>
      </tr>`;
    }).join("");
    setStatus("auditStatus", "");
  } catch (e) {
    setStatus("auditStatus", e.message, false);
  }
}

async function recalculate() {
  const btn = document.getElementById("recalculateBtn");
  if (btn) btn.disabled = true;
  setStatus("recalcStatus", "Recalculating...");
  try {
    const res = await fetch(`${API}/recalculate`, { method: "POST" });
    const data = await res.json();
    setStatus("recalcStatus", res.ok ? `Done. ${data.recalculated} records updated, ${data.card_points} stored card points rebuilt.` : data.detail, res.ok);
  } catch (e) {
    setStatus("recalcStatus", e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Issue #250: read-only check of a week's stored card points (GET /admin/points-check).
async function loadPointsCheckWeeks() {
  const sel = document.getElementById("pointsCheckWeekSelect");
  if (!sel) return;
  try {
    const res = await fetch(`${API}/weeks`);
    const weeks = await res.json();
    if (!res.ok) return setStatus("pointsCheckStatus", weeks.detail || "Failed to load weeks", false);
    const locked = weeks.filter(w => w.is_locked);
    const prev = sel.value;
    sel.innerHTML = locked.map(w => `<option value="${Number(w.id)}">${_escHtml(w.label)}</option>`).join("");
    if (prev && locked.some(w => String(w.id) === prev)) sel.value = prev;
    else if (locked.length) sel.value = String(locked[locked.length - 1].id);  // latest locked week
    const btn = document.getElementById("pointsCheckBtn");
    if (btn) btn.disabled = !locked.length;
    if (!locked.length) setStatus("pointsCheckStatus", "No locked weeks to check yet", false);
  } catch (e) {
    setStatus("pointsCheckStatus", e.message, false);
  }
}

function _pointsCheckValue(v) {
  return v === null || v === undefined ? "—" : _escHtml(String(v));
}

function _renderPointsCheck(data) {
  const box = document.getElementById("pointsCheckResult");
  const summary = `${data.cards} cards, ${data.games} games checked in ${data.week.label}.`;  // shown via setStatus (textContent)
  if (!data.mismatches.length) {
    box.innerHTML = "";
    setStatus("pointsCheckStatus", `All ${data.checked} card points match. ${summary}`, true);
    return;
  }
  const rows = data.mismatches.map(m => `<tr>
      <td>${_escHtml(m.user || "")}</td>
      <td>${_escHtml(m.player || "")} (${_escHtml(m.card_type || "")})</td>
      <td>${Number(m.match_id)}</td>
      <td>${_pointsCheckValue(m.stored)}</td>
      <td>${_pointsCheckValue(m.fresh)}</td>
    </tr>`).join("");
  box.innerHTML = `<table>
      <thead><tr><th>User</th><th>Card</th><th>Match</th><th>Stored</th><th>Fresh</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  setStatus("pointsCheckStatus", `${data.mismatches.length} of ${data.checked} card points differ. ${summary} Run Recalculate Fantasy Points to fix them.`, false);
}

async function checkPoints() {
  const sel = document.getElementById("pointsCheckWeekSelect");
  const weekId = parseInt(sel && sel.value, 10);
  if (!Number.isFinite(weekId)) return setStatus("pointsCheckStatus", "Pick a week first", false);
  const btn = document.getElementById("pointsCheckBtn");
  if (btn) btn.disabled = true;
  setStatus("pointsCheckStatus", "Checking...");
  try {
    const res = await fetch(`${API}/admin/points-check?week_id=${weekId}`);
    const data = await res.json();
    if (!res.ok) return setStatus("pointsCheckStatus", data.detail || "Check failed", false);
    _renderPointsCheck(data);
  } catch (e) {
    setStatus("pointsCheckStatus", e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function enrichProfiles() {
  const btn = document.getElementById("enrichBtn");
  if (btn) btn.disabled = true;
  setStatus("enrichStatus", "Enriching...");
  try {
    const res = await fetch(`${API}/admin/enrich-profiles`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      setStatus("enrichStatus", `Done. Enriched: ${data.enriched}, skipped: ${data.skipped}, errors: ${data.errors}`, true);
    } else {
      setStatus("enrichStatus", data.detail || "Failed", false);
    }
  } catch (e) {
    setStatus("enrichStatus", e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}
