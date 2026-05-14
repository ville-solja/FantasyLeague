async function loadAdminWeeks() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/weeks`);
    const rows = await res.json();
    if (!res.ok) return setStatus("weeksAdminStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("adminWeeksBody").innerHTML = "<tr><td colspan='6' style='color:#444'>No weeks</td></tr>";
      return;
    }
    const tbody = document.getElementById("adminWeeksBody");
    tbody.innerHTML = "";
    rows.forEach(w => {
      const tr = document.createElement("tr");
      const start = new Date(w.start_time * 1000).toLocaleString();
      const end   = new Date(w.end_time   * 1000).toLocaleString();
      tr.innerHTML = `
        <td></td>
        <td style="font-size:0.8rem;">${start}</td>
        <td style="font-size:0.8rem;">${end}</td>
        <td>${w.is_locked ? "<span style='color:#888;font-size:0.75rem;'>LOCKED</span>" : ""}</td>
        <td>${w.roster_count}</td>
        <td></td>`;
      tr.cells[0].textContent = w.label;
      if (!w.is_locked) {
        const editBtn = document.createElement("button");
        editBtn.className = "secondary";
        editBtn.style.cssText = "padding:2px 7px;margin-right:4px;";
        editBtn.textContent = "Edit";
        editBtn.addEventListener("click", () => openWeekEdit(w.id, w.label, w.start_time, w.end_time));
        const delBtn = document.createElement("button");
        delBtn.className = "danger";
        delBtn.style.cssText = "padding:2px 7px;";
        delBtn.textContent = "Delete";
        delBtn.addEventListener("click", () => deleteAdminWeek(w.id));
        tr.cells[5].appendChild(editBtn);
        tr.cells[5].appendChild(delBtn);
      } else {
        tr.cells[5].textContent = "—";
      }
      tbody.appendChild(tr);
    });
    setStatus("weeksAdminStatus", "");
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

async function createAdminWeek() {
  const label    = document.getElementById("weekLabel").value.trim();
  const startVal = document.getElementById("weekStart").value;
  const endVal   = document.getElementById("weekEnd").value;
  if (!label)               return setStatus("weeksAdminStatus", "Enter a label", false);
  if (!startVal || !endVal) return setStatus("weeksAdminStatus", "Set start and end time", false);
  const start_time = Math.floor(new Date(startVal).getTime() / 1000);
  const end_time   = Math.floor(new Date(endVal).getTime()   / 1000);
  if (end_time <= start_time) return setStatus("weeksAdminStatus", "End time must be after start time", false);
  try {
    const res = await fetch(`${API}/admin/weeks`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label, start_time, end_time}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("weeksAdminStatus", data.detail, false);
    setStatus("weeksAdminStatus", `Week "${data.label}" created`);
    document.getElementById("weekLabel").value = "";
    document.getElementById("weekStart").value = "";
    document.getElementById("weekEnd").value   = "";
    loadAdminWeeks();
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

function openWeekEdit(id, label, startTs, endTs) {
  const toLocal = ts => {
    const d = new Date(ts * 1000);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  };
  document.getElementById("editWeekId").value    = id;
  document.getElementById("editWeekLabel").value = label;
  document.getElementById("editWeekStart").value = toLocal(startTs);
  document.getElementById("editWeekEnd").value   = toLocal(endTs);
  document.getElementById("weekEditForm").classList.remove("hidden");
}

function cancelWeekEdit() {
  document.getElementById("weekEditForm").classList.add("hidden");
}

async function saveWeekEdit() {
  const id       = parseInt(document.getElementById("editWeekId").value, 10);
  const label    = document.getElementById("editWeekLabel").value.trim() || undefined;
  const startVal = document.getElementById("editWeekStart").value;
  const endVal   = document.getElementById("editWeekEnd").value;
  const body = {};
  if (label)    body.label      = label;
  if (startVal) body.start_time = Math.floor(new Date(startVal).getTime() / 1000);
  if (endVal)   body.end_time   = Math.floor(new Date(endVal).getTime()   / 1000);
  if (body.start_time && body.end_time && body.end_time <= body.start_time)
    return setStatus("weeksAdminStatus", "End time must be after start time", false);
  try {
    const res = await fetch(`${API}/admin/weeks/${id}`, {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("weeksAdminStatus", data.detail, false);
    setStatus("weeksAdminStatus", "Week updated");
    cancelWeekEdit();
    loadAdminWeeks();
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

async function deleteAdminWeek(weekId) {
  try {
    const res = await fetch(`${API}/admin/weeks/${weekId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("weeksAdminStatus", d.detail, false); }
    setStatus("weeksAdminStatus", "Week deleted");
    loadAdminWeeks();
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

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

async function loadUsers() {
  try {
    const res = await fetch(`${API}/users`);
    const rows = await res.json();
    if (!res.ok) return setStatus("usersStatus", rows.detail, false);
    document.getElementById("usersBody").innerHTML = rows.map(u => `
      <tr>
        <td>${u.username}${u.is_tester ? ' <span class="badge" style="background:var(--k-ink-700,#2a2a30);color:#888;font-size:0.7rem;">TESTER</span>' : ""}</td>
        <td>${u.tokens}</td>
        <td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
          <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
          <button class="ghost" style="font-size:0.8rem;" onclick="toggleTester(${u.id})">${u.is_tester ? "Unmark tester" : "Mark tester"}</button>
        </td>
      </tr>`).join("");
    setStatus("usersStatus", "");
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function toggleTester(userId) {
  try {
    const res = await fetch(`${API}/users/${userId}/toggle-tester`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("usersStatus", data.detail, false);
    setStatus("usersStatus", `${data.username} ${data.is_tester ? "marked as tester" : "unmarked as tester"}`);
    loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function grantTokens(targetId) {
  const input = document.getElementById(`grant_${targetId}`);
  const amount = parseInt(input.value);
  if (!amount || amount < 1) return setStatus("usersStatus", "Enter a valid amount", false);
  const btn = input.nextElementSibling;
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API}/grant-tokens`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({target_user_id: targetId, amount}) });
    const data = await res.json();
    setStatus("usersStatus", res.ok ? `${data.username} now has ${data.tokens} ${_tokenName}` : data.detail, res.ok);
    if (res.ok) loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadCodes() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/codes`);
    const rows = await res.json();
    if (!res.ok) return setStatus("codesStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("codesBody").innerHTML = "<tr><td colspan='4' style='color:#444'>No codes yet</td></tr>";
      return;
    }
    document.getElementById("codesBody").innerHTML = rows.map(c => `
      <tr data-code-id="${c.id}">
        <td><code>${c.code}</code></td>
        <td>${c.token_amount}</td>
        <td>${c.redemptions}</td>
        <td><button class="ghost" style="font-size:0.8rem;" onclick="deleteCode(${c.id})">Delete</button></td>
      </tr>`).join("");
    setStatus("codesStatus", "");
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

async function createCode() {
  const code   = document.getElementById("newCodeInput").value.trim().toUpperCase();
  const amount = parseInt(document.getElementById("newCodeAmount").value);
  if (!code)        return setStatus("codesStatus", "Enter a code name", false);
  if (!amount || amount < 1) return setStatus("codesStatus", "Enter a token amount ≥ 1", false);
  try {
    const res = await fetch(`${API}/codes`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code, token_amount: amount}) });
    const data = await res.json();
    if (!res.ok) return setStatus("codesStatus", data.detail, false);
    document.getElementById("newCodeInput").value  = "";
    document.getElementById("newCodeAmount").value = "";
    setStatus("codesStatus", `Code ${data.code} created`);
    loadCodes();
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

function deleteCode(codeId) {
  const existing = document.getElementById(`deleteConfirm_${codeId}`);
  if (existing) { existing.remove(); return; }
  const row = document.querySelector(`[data-code-id="${codeId}"]`);
  if (!row) return;
  const confirm = document.createElement("tr");
  confirm.id = `deleteConfirm_${codeId}`;
  confirm.className = "delete-confirm-row";
  confirm.innerHTML = `<td colspan="4" style="padding:8px 10px;">
    <span class="delete-confirm-msg">Delete this code?</span>
    <span style="margin-left:12px;display:inline-flex;gap:6px;">
      <button class="danger" style="padding:3px 10px;" onclick="_confirmDeleteCode(${codeId})">Delete</button>
      <button class="ghost" style="padding:3px 10px;" onclick="document.getElementById('deleteConfirm_${codeId}').remove()">Cancel</button>
    </span>
  </td>`;
  row.after(confirm);
}

async function _confirmDeleteCode(codeId) {
  try {
    const res = await fetch(`${API}/codes/${codeId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("codesStatus", d.detail, false); }
    setStatus("codesStatus", "Code deleted");
    loadCodes();
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

async function loadNotifications() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/notifications`);
    const rows = await res.json();
    if (!res.ok) return setStatus("notifAdminStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("notifBody").innerHTML = "<tr><td colspan='5' style='color:#444'>No notifications</td></tr>";
      return;
    }
    document.getElementById("notifBody").innerHTML = rows.map(n => {
      const start = new Date(n.start_time * 1000).toLocaleString();
      const end   = new Date(n.end_time   * 1000).toLocaleString();
      const msg   = n.message.length > 60 ? n.message.slice(0, 57) + "..." : n.message;
      return `<tr>
        <td style="font-size:0.8rem;">${msg}</td>
        <td style="font-size:0.8rem;">${start}</td>
        <td style="font-size:0.8rem;">${end}</td>
        <td>${n.dismiss_count}</td>
        <td><button class="danger" style="padding:2px 8px;" onclick="deleteNotification(${n.id})">Delete</button></td>
      </tr>`;
    }).join("");
    setStatus("notifAdminStatus", "");
  } catch (e) {
    setStatus("notifAdminStatus", e.message, false);
  }
}

async function createNotification() {
  const message  = document.getElementById("notifMsgInput").value.trim();
  const startVal = document.getElementById("notifStart").value;
  const endVal   = document.getElementById("notifEnd").value;
  if (!message)              return setStatus("notifAdminStatus", "Enter a message", false);
  if (message.length > 500)  return setStatus("notifAdminStatus", "Message must be 500 characters or fewer", false);
  if (!startVal || !endVal)  return setStatus("notifAdminStatus", "Set start and end time", false);
  const start_time = Math.floor(new Date(startVal).getTime() / 1000);
  const end_time   = Math.floor(new Date(endVal).getTime()   / 1000);
  if (end_time <= start_time) return setStatus("notifAdminStatus", "End time must be after start time", false);
  try {
    const res = await fetch(`${API}/admin/notifications`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message, start_time, end_time}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("notifAdminStatus", data.detail, false);
    setStatus("notifAdminStatus", "Notification created");
    document.getElementById("notifMsgInput").value = "";
    document.getElementById("notifStart").value    = "";
    document.getElementById("notifEnd").value      = "";
    loadNotifications();
  } catch (e) {
    setStatus("notifAdminStatus", e.message, false);
  }
}

async function deleteNotification(notifId) {
  try {
    const res = await fetch(`${API}/admin/notifications/${notifId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("notifAdminStatus", d.detail, false); }
    setStatus("notifAdminStatus", "Notification deleted");
    loadNotifications();
  } catch (e) {
    setStatus("notifAdminStatus", e.message, false);
  }
}

async function loadTokenGrantEvents() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/token-grant-events`);
    const rows = await res.json();
    if (!res.ok) return setStatus("tokenGrantStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("tokenGrantBody").innerHTML = "<tr><td colspan='5' style='color:#444'>No events</td></tr>";
      return;
    }
    document.getElementById("tokenGrantBody").innerHTML = rows.map(ev => {
      const start = new Date(ev.start_time * 1000).toLocaleString();
      const end   = new Date(ev.end_time   * 1000).toLocaleString();
      return `<tr data-grant-id="${ev.id}">
        <td>${ev.amount}</td>
        <td style="font-size:0.8rem;">${start}</td>
        <td style="font-size:0.8rem;">${end}</td>
        <td>${ev.claim_count}</td>
        <td><button class="danger" style="padding:2px 8px;" onclick="deleteTokenGrantEvent(${ev.id})">Delete</button></td>
      </tr>`;
    }).join("");
    setStatus("tokenGrantStatus", "");
  } catch (e) {
    setStatus("tokenGrantStatus", e.message, false);
  }
}

async function createTokenGrantEvent() {
  const amount = parseInt(document.getElementById("grantAmount").value, 10);
  const startVal = document.getElementById("grantStart").value;
  const endVal   = document.getElementById("grantEnd").value;
  if (!amount || amount < 1) return setStatus("tokenGrantStatus", "Enter a token amount ≥ 1", false);
  if (!startVal || !endVal)  return setStatus("tokenGrantStatus", "Set start and end time", false);
  const start_time = Math.floor(new Date(startVal).getTime() / 1000);
  const end_time   = Math.floor(new Date(endVal).getTime()   / 1000);
  if (end_time <= start_time) return setStatus("tokenGrantStatus", "End time must be after start time", false);
  try {
    const res = await fetch(`${API}/admin/token-grant-events`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({amount, start_time, end_time}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("tokenGrantStatus", data.detail, false);
    setStatus("tokenGrantStatus", "Event created");
    document.getElementById("grantAmount").value = "";
    document.getElementById("grantStart").value  = "";
    document.getElementById("grantEnd").value    = "";
    loadTokenGrantEvents();
  } catch (e) {
    setStatus("tokenGrantStatus", e.message, false);
  }
}

async function deleteTokenGrantEvent(eventId) {
  try {
    const res = await fetch(`${API}/admin/token-grant-events/${eventId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("tokenGrantStatus", d.detail, false); }
    setStatus("tokenGrantStatus", "Event deleted");
    loadTokenGrantEvents();
  } catch (e) {
    setStatus("tokenGrantStatus", e.message, false);
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

async function ingestLeague() {
  const id = document.getElementById("leagueId").value;
  if (!id) return setStatus("ingestStatus", "Enter a league ID", false);
  const btn = document.getElementById("ingestBtn");
  if (btn) btn.disabled = true;
  setStatus("ingestStatus", "Ingesting... this may take a while");
  try {
    const res = await fetch(`${API}/ingest/league/${id}`, { method: "POST" });
    const data = await res.json();
    setStatus("ingestStatus", res.ok ? `Done. League ${data.league_id} ingested.` : data.detail, res.ok);
  } catch (e) {
    setStatus("ingestStatus", e.message, false);
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
