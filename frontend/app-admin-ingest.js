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
        <td>${r.actor_username || "<em style='color:#555'>system</em>"}</td>
        <td><code style="font-size:0.8rem;">${r.action}</code></td>
        <td style="font-size:0.8rem;color:#888;">${r.detail || ""}</td>
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
    setStatus("recalcStatus", res.ok ? `Done. ${data.recalculated} records updated.` : data.detail, res.ok);
  } catch (e) {
    setStatus("recalcStatus", e.message, false);
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
