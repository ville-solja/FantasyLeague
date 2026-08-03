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
  const label = document.getElementById("weekLabel").value.trim();
  const startEl = document.getElementById("weekStart");
  const endEl   = document.getElementById("weekEnd");
  const start_date = dateInputIso(startEl);
  const end_date   = dateInputIso(endEl);
  if (!label)                 return setStatus("weeksAdminStatus", "Enter a label", false);
  if (!start_date || !end_date) return setStatus("weeksAdminStatus", "Set start and end date (pp.kk.vvvv)", false);
  try {
    const res = await fetch(`${API}/admin/weeks`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label, start_date, end_date}),
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

// Convert a Unix timestamp to its UTC calendar date (YYYY-MM-DD).
function _utcDateStr(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function openWeekEdit(id, label, startTs, endTs) {
  document.getElementById("editWeekId").value    = id;
  document.getElementById("editWeekLabel").value = label;
  setDateInputIso(document.getElementById("editWeekStart"), _utcDateStr(startTs));
  // end_time is stored as (end_date + 1 day) 03:00 UTC — subtract a day to
  // show the date the admin originally picked.
  setDateInputIso(document.getElementById("editWeekEnd"), _utcDateStr(endTs - 24 * 3600));
  document.getElementById("weekEditForm").classList.remove("hidden");
}

function cancelWeekEdit() {
  document.getElementById("weekEditForm").classList.add("hidden");
}

async function saveWeekEdit() {
  const id        = parseInt(document.getElementById("editWeekId").value, 10);
  const label     = document.getElementById("editWeekLabel").value.trim() || undefined;
  const start_date = dateInputIso(document.getElementById("editWeekStart")) || undefined;
  const end_date   = dateInputIso(document.getElementById("editWeekEnd")) || undefined;
  const body = {};
  if (label)     body.label      = label;
  if (start_date) body.start_date = start_date;
  if (end_date)   body.end_date   = end_date;
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

let _allTags = [];
let _cachedUsers = [];

async function loadUsers() {
  try {
    const res = await fetch(`${API}/users`);
    const rows = await res.json();
    if (!res.ok) return setStatus("usersStatus", rows.detail, false);
    _cachedUsers = rows;
    _renderUsers(rows);
    setStatus("usersStatus", "");
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

function _renderUsers(rows) {
  const search = (document.getElementById("userSearch")?.value || "").toLowerCase();
  const visible = search ? rows.filter(u => u.username.toLowerCase().includes(search)) : rows;
  document.getElementById("usersBody").innerHTML = visible.map(u => {
    const testerBadge = u.is_tester
      ? ` <span class="badge" style="background:var(--k-ink-700,#2a2a30);color:#888;font-size:0.7rem;">TESTER</span>`
      : "";
    const tagChips = (u.tags || []).map(t =>
      `<span style="display:inline-block;background:var(--k-flame-500,#DC5014);color:#fff;font-size:0.65rem;padding:1px 6px;border-radius:2px;margin-right:3px;">${t.label}</span>`
    ).join("");
    return `<tr data-user-id="${u.id}">
      <td>${u.username}${testerBadge}</td>
      <td>${tagChips || '<span style="color:#555;font-size:0.8rem;">—</span>'}</td>
      <td>${u.tokens}</td>
      <td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
        <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
        <button class="ghost" style="font-size:0.8rem;" onclick="toggleTester(${u.id})">${u.is_tester ? "Unmark tester" : "Mark tester"}</button>
        <button class="ghost" style="font-size:0.8rem;" onclick="openTagManager(${u.id})">Manage tags</button>
      </td>
    </tr>`;
  }).join("");
}

function filterUsers() {
  _renderUsers(_cachedUsers);
}

function openTagManager(userId) {
  const existing = document.getElementById(`tagManager_${userId}`);
  if (existing) { existing.remove(); return; }
  const row = document.querySelector(`[data-user-id="${userId}"]`);
  if (!row) return;
  const user = _cachedUsers.find(u => u.id === userId);
  if (!user) return;
  const userTagKeys = new Set((user.tags || []).map(t => t.key));
  const tagControls = _allTags.length
    ? _allTags.map(t => {
        const has = userTagKeys.has(t.key);
        const btn = has
          ? `<button class="danger" style="padding:2px 8px;font-size:0.75rem;" onclick="revokeUserTag(${userId},${t.id})">Revoke</button>`
          : `<button class="secondary" style="padding:2px 8px;font-size:0.75rem;" onclick="grantUserTag(${userId},${t.id})">Grant</button>`;
        return `<span style="display:inline-flex;align-items:center;gap:4px;margin:2px 4px 2px 0;">
          <span style="font-size:0.8rem;">${t.label}</span>${btn}
        </span>`;
      }).join("")
    : `<span style="color:#555;font-size:0.8rem;">No tag definitions yet.</span>`;
  const managerRow = document.createElement("tr");
  managerRow.id = `tagManager_${userId}`;
  managerRow.innerHTML = `<td colspan="4" style="padding:8px 12px;background:var(--k-ink-900,#111);">
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:2px;">
      ${tagControls}
      <button class="ghost" style="padding:2px 8px;font-size:0.75rem;margin-left:8px;" onclick="document.getElementById('tagManager_${userId}')?.remove()">Close</button>
    </div>
  </td>`;
  row.after(managerRow);
}

async function grantUserTag(userId, tagId) {
  try {
    const res = await fetch(`${API}/admin/users/${userId}/tags/${tagId}`, { method: "POST" });
    if (!res.ok) { const d = await res.json(); return setStatus("usersStatus", d.detail, false); }
    setStatus("usersStatus", "Tag granted");
    document.getElementById(`tagManager_${userId}`)?.remove();
    await loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function revokeUserTag(userId, tagId) {
  try {
    const res = await fetch(`${API}/admin/users/${userId}/tags/${tagId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("usersStatus", d.detail, false); }
    setStatus("usersStatus", "Tag revoked");
    document.getElementById(`tagManager_${userId}`)?.remove();
    await loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function loadTags() {
  try {
    const res = await fetch(`${API}/admin/tags`);
    const rows = await res.json();
    if (!res.ok) return setStatus("tagsStatus", rows.detail, false);
    _allTags = rows;
    document.getElementById("tagsBody").innerHTML = rows.length
      ? rows.map(t => `<tr data-tag-id="${t.id}">
          <td><code style="font-size:0.8rem;">${t.key}</code></td>
          <td>${t.label}</td>
          <td><button class="danger" style="padding:2px 8px;" onclick="deleteTag(${t.id})">Delete</button></td>
        </tr>`).join("")
      : `<tr><td colspan="3" style="color:#444">No tags defined</td></tr>`;
    setStatus("tagsStatus", "");
  } catch (e) {
    setStatus("tagsStatus", e.message, false);
  }
}

async function createTag() {
  const key   = document.getElementById("tagKeyInput").value.trim().toLowerCase().replace(/\s+/g, "_");
  const label = document.getElementById("tagLabelInput").value.trim();
  if (!key)   return setStatus("tagsStatus", "Enter a key", false);
  if (!label) return setStatus("tagsStatus", "Enter a label", false);
  try {
    const res = await fetch(`${API}/admin/tags`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({key, label}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("tagsStatus", data.detail, false);
    document.getElementById("tagKeyInput").value   = "";
    document.getElementById("tagLabelInput").value = "";
    setStatus("tagsStatus", `Tag "${data.label}" created`);
    loadTags();
  } catch (e) {
    setStatus("tagsStatus", e.message, false);
  }
}

async function deleteTag(tagId) {
  try {
    const res = await fetch(`${API}/admin/tags/${tagId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("tagsStatus", d.detail, false); }
    setStatus("tagsStatus", "Tag deleted");
    loadTags();
    loadUsers();
  } catch (e) {
    setStatus("tagsStatus", e.message, false);
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

// ---------------------------------------------------------------------------
// Player Pool
// ---------------------------------------------------------------------------

let _playerPoolRows = [];

async function loadPlayerPool() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/players`);
    const rows = await res.json();
    if (!res.ok) return setStatus("playerPoolStatus", rows.detail, false);
    _playerPoolRows = rows;
    _renderPlayerPool(rows);
    setStatus("playerPoolStatus", "");
  } catch (e) {
    setStatus("playerPoolStatus", e.message, false);
  }
}

function _renderPlayerPool(rows) {
  const search = (document.getElementById("playerPoolSearch")?.value || "").toLowerCase();
  const visible = search
    ? rows.filter(p => p.name.toLowerCase().includes(search) || (p.team_name || "").toLowerCase().includes(search) || String(p.id).includes(search))
    : rows;
  const tbody = document.getElementById("playerPoolBody");
  if (!visible.length) {
    tbody.innerHTML = `<tr><td colspan='6' style='color:#444'>${search ? "No matches" : "No players in pool"}</td></tr>`;
    _updateRemoveBtn();
    return;
  }
  tbody.innerHTML = visible.map(p => `
    <tr data-player-id="${p.id}" data-player-name="${_escHtml(p.name)}">
      <td><input type="checkbox" class="player-pool-cb" onchange="_updateRemoveBtn()" /></td>
      <td><img src="${p.avatar_url || ''}" style="width:20px;height:20px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${_escHtml(p.name)}</td>
      <td>${_escHtml(p.team_name || "—")}</td>
      <td style="font-size:0.8rem;color:#888;">${p.id}</td>
      <td>${p.active_card_count}</td>
      <td>${p.is_active ? "" : "<span style='color:#888;font-size:0.75rem;'>INACTIVE</span>"}</td>
    </tr>`).join("");
  _updateRemoveBtn();
}

function filterPlayerPool() {
  _renderPlayerPool(_playerPoolRows);
}

function _updateRemoveBtn() {
  const btn = document.getElementById("removePlayersBtn");
  if (!btn) return;
  const checked = document.querySelectorAll(".player-pool-cb:checked").length;
  btn.disabled = checked === 0;
}

function openAddPlayerPopup() {
  document.getElementById("addPlayerModal").classList.remove("hidden");
  setStatus("addPlayerStatus", "");
  document.getElementById("addPlayerIdInput").value = "";
}

function closeAddPlayerPopup() {
  document.getElementById("addPlayerModal").classList.add("hidden");
}

async function addPlayer() {
  const idVal = document.getElementById("addPlayerIdInput").value.trim();
  if (!idVal) return setStatus("addPlayerStatus", "Enter an OpenDota account ID", false);
  const player_id = parseInt(idVal, 10);
  if (isNaN(player_id)) return setStatus("addPlayerStatus", "ID must be an integer", false);
  try {
    const res = await fetch(`${API}/admin/players`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_id}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("addPlayerStatus", data.detail, false);
    setStatus("addPlayerStatus", `Added: ${data.name} (${data.id})`);
    document.getElementById("addPlayerIdInput").value = "";
    loadPlayerPool();
  } catch (e) {
    setStatus("addPlayerStatus", e.message, false);
  }
}

function openBulkAddPlayersPopup() {
  document.getElementById("bulkAddPlayersModal").classList.remove("hidden");
  setStatus("bulkAddPlayersStatus", "");
  document.getElementById("bulkAddIdsInput").value = "";
}

function closeBulkAddPlayersPopup() {
  document.getElementById("bulkAddPlayersModal").classList.add("hidden");
}

async function bulkAddPlayers() {
  const csv = document.getElementById("bulkAddIdsInput").value.trim();
  if (!csv) return setStatus("bulkAddPlayersStatus", "Enter at least one ID", false);
  try {
    const res = await fetch(`${API}/admin/players/bulk`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_ids: csv}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("bulkAddPlayersStatus", data.detail, false);
    const msg = `Added: ${data.added}. Skipped: ${data.skipped.length}.`;
    setStatus("bulkAddPlayersStatus", msg);
    if (data.added > 0) loadPlayerPool();
  } catch (e) {
    setStatus("bulkAddPlayersStatus", e.message, false);
  }
}

function openRemovePlayersConfirm() {
  const checked = document.querySelectorAll(".player-pool-cb:checked");
  if (!checked.length) return;
  const names = Array.from(checked).map(cb => {
    const row = cb.closest("tr");
    return row ? row.dataset.playerName : "Unknown";
  });
  document.getElementById("removePlayersNames").textContent = names.join(", ");
  document.getElementById("removePlayersModal").classList.remove("hidden");
  setStatus("removePlayersStatus", "");
}

function closeRemovePlayersConfirm() {
  document.getElementById("removePlayersModal").classList.add("hidden");
}

async function removeSelectedPlayers() {
  const checked = document.querySelectorAll(".player-pool-cb:checked");
  const player_ids = Array.from(checked).map(cb => {
    const row = cb.closest("tr");
    return row ? parseInt(row.dataset.playerId, 10) : null;
  }).filter(id => id !== null);
  if (!player_ids.length) return;
  try {
    const res = await fetch(`${API}/admin/players/remove`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({player_ids}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("removePlayersStatus", data.detail, false);
    setStatus("removePlayersStatus", "Players removed and refunds issued");
    closeRemovePlayersConfirm();
    loadPlayerPool();
  } catch (e) {
    setStatus("removePlayersStatus", e.message, false);
  }
}

// ---------------------------------------------------------------------------
// League Management
// ---------------------------------------------------------------------------

let _leaguesCached = [];
let _purgeTargetLeagueId = null;

async function loadLeagues() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/leagues`);
    const data = await res.json();
    if (!res.ok) return;
    _leaguesCached = data;
    _renderLeagues();
  } catch (e) { /* silently ignore network errors */ }
}

function _renderLeagues() {
  const tbody = document.getElementById('leagueTableBody');
  if (!_leaguesCached.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:#444">No leagues</td></tr>`;
    return;
  }
  tbody.innerHTML = _leaguesCached.map(l => `
    <tr>
      <td>${l.id}</td>
      <td>${_escHtml(l.name)}</td>
      <td>${l.match_count}</td>
      <td>${l.is_monitored ? 'Yes' : 'No'}</td>
      <td>
        ${l.is_monitored
          ? `<button onclick="unmonitorLeague(${l.id})">Unmonitor</button>`
          : `<button onclick="monitorLeague(${l.id})">Monitor</button>`
        }
        ${l.match_count > 0
          ? `<button onclick="openPurgeLeagueModal(${l.id}, '${_escHtml(l.name)}')">Purge data</button>`
          : ''
        }
      </td>
    </tr>`).join('');
}

function openAddLeagueModal() { document.getElementById('addLeagueModal').style.display = 'flex'; }
function closeAddLeagueModal() { document.getElementById('addLeagueModal').style.display = 'none'; }

async function submitAddLeague() {
  const id = parseInt(document.getElementById('addLeagueIdInput').value);
  if (!id) return alert('Enter a valid league ID');
  const res = await fetch(`${API}/admin/leagues/${id}/monitor`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) { alert(data.detail); return; }
  closeAddLeagueModal();
  loadLeagues();
}

async function monitorLeague(id) {
  const res = await fetch(`${API}/admin/leagues/${id}/monitor`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) alert(data.detail);
  loadLeagues();
}

async function unmonitorLeague(id) {
  const res = await fetch(`${API}/admin/leagues/${id}/monitor`, { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) alert(data.detail);
  loadLeagues();
}

function openPurgeLeagueModal(id, name) {
  _purgeTargetLeagueId = id;
  document.getElementById('purgeLeagueDescription').textContent = `League: ${name} (ID ${id})`;
  document.getElementById('purgeLeagueModal').style.display = 'flex';
}
function closePurgeLeagueModal() {
  document.getElementById('purgeLeagueModal').style.display = 'none';
  _purgeTargetLeagueId = null;
}
async function confirmPurgeLeague() {
  if (!_purgeTargetLeagueId) return;
  const res = await fetch(`${API}/admin/leagues/${_purgeTargetLeagueId}/data`, { method: 'DELETE' });
  const data = await res.json();
  alert(`Purged: ${data.deleted_matches} matches, ${data.deleted_stats} stats. ${data.note}`);
  closePurgeLeagueModal();
  loadLeagues();
}

// ---------------------------------------------------------------------------
// Admin tab navigation
// ---------------------------------------------------------------------------

function initAdminTabs() {
  const tabBar = document.getElementById('admin-tab-bar');
  if (!tabBar) return;

  tabBar.querySelectorAll('.admin-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchAdminTab(btn.dataset.tab));
  });

  initWeekDateInputs();

  // Restore previously selected tab from sessionStorage, defaulting to user-management
  const saved = sessionStorage.getItem('adminTab') || 'user-management';
  switchAdminTab(saved);
}

function switchAdminTab(tabName) {
  // Update button active states
  document.querySelectorAll('.admin-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  // Show the matching section; hide all others
  document.querySelectorAll('[data-admin-tab]').forEach(el => {
    el.style.display = el.dataset.adminTab === tabName ? '' : 'none';
  });

  // Persist selection so navigating away and back remembers the tab
  sessionStorage.setItem('adminTab', tabName);

  // Lazily load data for the matches tab on first activation
  if (tabName === 'matches') loadAdminMatches();
}

// ---------------------------------------------------------------------------
// Matches tab — load and render
// ---------------------------------------------------------------------------

async function loadAdminMatches() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/matches`);
    const rows = await res.json();
    if (!res.ok) return setStatus('adminMatchesStatus', rows.detail, false);

    const tbody = document.getElementById('adminMatchesBody');
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='7' style='color:#444'>No matches</td></tr>";
      setStatus('adminMatchesStatus', '');
      return;
    }
    tbody.innerHTML = '';
    rows.forEach(m => {
      const tr = document.createElement('tr');
      const start = m.start_time ? new Date(m.start_time * 1000).toLocaleString() : '—';
      tr.innerHTML = `
        <td><a class="stream-link" href="https://www.opendota.com/matches/${m.match_id}" target="_blank" rel="noopener noreferrer">${m.match_id} ↗</a></td>
        <td>${m.league_id || '—'}</td>
        <td style="font-size:0.85rem;">${teamLink(m.radiant_team_id, m.team1)}</td>
        <td style="font-size:0.85rem;">${teamLink(m.dire_team_id, m.team2)}</td>
        <td style="font-size:0.8rem;">${start}</td>
        <td class="mvp-cell">${m.mvp_player_name || '—'}</td>
        <td></td>`;
      const setMvpBtn = document.createElement('button');
      setMvpBtn.className = 'secondary';
      setMvpBtn.style.cssText = 'padding:2px 7px;';
      setMvpBtn.textContent = 'Set MVP';
      setMvpBtn.addEventListener('click', () => openMvpModal(m.match_id, tr));
      tr.cells[6].appendChild(setMvpBtn);
      tbody.appendChild(tr);
    });
    setStatus('adminMatchesStatus', '');
  } catch (e) {
    setStatus('adminMatchesStatus', e.message, false);
  }
}

// ---------------------------------------------------------------------------
// MVP selection modal
// ---------------------------------------------------------------------------

let _mvpTargetMatchId = null;
let _mvpTargetRow = null;

async function openMvpModal(matchId, row) {
  _mvpTargetMatchId = matchId;
  _mvpTargetRow = row;
  document.getElementById('mvpModalStatus').textContent = '';
  document.getElementById('mvpPlayerList').innerHTML = '<p style="color:#888">Loading…</p>';
  document.getElementById('mvpModal').style.display = 'flex';

  try {
    const res = await fetch(`${API}/admin/matches/${matchId}/players`);
    const players = await res.json();
    if (!res.ok) {
      document.getElementById('mvpPlayerList').innerHTML =
        `<p style='color:#e05'>${players.detail}</p>`;
      return;
    }
    if (!players.length) {
      document.getElementById('mvpPlayerList').innerHTML =
        '<p style="color:#888">No players found for this match.</p>';
      return;
    }
    document.getElementById('mvpPlayerList').innerHTML = players.map(p =>
      `<label style="display:block;padding:6px 0;cursor:pointer;">` +
      `<input type="radio" name="mvpPlayer" value="${p.id}" style="margin-right:8px;">${p.name}` +
      `</label>`
    ).join('');
  } catch (e) {
    document.getElementById('mvpPlayerList').innerHTML =
      `<p style='color:#e05'>${e.message}</p>`;
  }
}

function closeMvpModal() {
  document.getElementById('mvpModal').style.display = 'none';
  _mvpTargetMatchId = null;
  _mvpTargetRow = null;
}

async function confirmSetMvp() {
  const selected = document.querySelector('input[name="mvpPlayer"]:checked');
  if (!selected) {
    document.getElementById('mvpModalStatus').textContent = 'Select a player first.';
    return;
  }
  const playerId = parseInt(selected.value);

  try {
    const res = await fetch(`${API}/admin/matches/${_mvpTargetMatchId}/mvp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_id: playerId }),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('mvpModalStatus').textContent = data.detail;
      return;
    }
    // Update the MVP cell in the table row immediately
    if (_mvpTargetRow) {
      const mvpCell = _mvpTargetRow.querySelector('.mvp-cell');
      if (mvpCell) mvpCell.textContent = data.player_name;
    }
    closeMvpModal();
  } catch (e) {
    document.getElementById('mvpModalStatus').textContent = e.message;
  }
}

// ---------------------------------------------------------------------------
// Season Lifecycle — End Season archive + Season Reset
// ---------------------------------------------------------------------------

async function loadSeasonArchives() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/leaderboard/seasons`);
    const rows = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", rows.detail, false);
    const tbody = document.getElementById("seasonArchivesBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No archived seasons yet</td></tr>";
      return;
    }
    tbody.innerHTML = "";
    rows.forEach(s => {
      const tr = document.createElement("tr");
      const archived = new Date(s.archived_at * 1000).toLocaleString();
      tr.innerHTML = `<td>${s.season_label}</td><td style="font-size:0.8rem;">${archived}</td><td>${s.user_count}</td>`;
      tbody.appendChild(tr);
    });
  } catch (e) {
    setStatus("seasonLifecycleStatus", e.message, false);
  }
}

async function endSeason() {
  const label = document.getElementById("endSeasonLabel").value.trim();
  if (!label) return setStatus("seasonLifecycleStatus", "Enter a season label", false);
  try {
    const res = await fetch(`${API}/admin/season/end`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({season_label: label}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("seasonLifecycleStatus", data.detail, false);
    setStatus("seasonLifecycleStatus", `Archived "${data.season_label}" (${data.archived_users} users)`);
    document.getElementById("endSeasonLabel").value = "";
    loadSeasonArchives();
  } catch (e) {
    setStatus("seasonLifecycleStatus", e.message, false);
  }
}

function openSeasonResetConfirm() {
  document.getElementById("seasonResetConfirmInput").value = "";
  document.getElementById("seasonResetModalStatus").textContent = "";
  document.getElementById("seasonResetModal").style.display = "flex";
}

function closeSeasonResetConfirm() {
  document.getElementById("seasonResetModal").style.display = "none";
}

async function confirmSeasonReset() {
  const typed = document.getElementById("seasonResetConfirmInput").value.trim();
  if (typed !== "RESET") {
    document.getElementById("seasonResetModalStatus").textContent = 'Type "RESET" to confirm.';
    return;
  }
  try {
    const res = await fetch(`${API}/admin/season/reset`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({force: false}),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById("seasonResetModalStatus").textContent = data.detail;
      return;
    }
    closeSeasonResetConfirm();
    setStatus("seasonLifecycleStatus", "Season reset complete");
    loadSeasonArchives();
    loadAdminWeeks();
    loadLeagues();
  } catch (e) {
    document.getElementById("seasonResetModalStatus").textContent = e.message;
  }
}

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

// ---------------------------------------------------------------------------
// Nordic date inputs (d.m.yyyy, e.g. "15.5.2026") with click-to-open calendar
// picker. Backend endpoints still take/return strict ISO yyyy-mm-dd —
// dateInputIso() and setDateInputIso() are the only two functions callers need.
// ---------------------------------------------------------------------------

const _DATE_RE = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/;

function _isoToNordic(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${parseInt(d, 10)}.${parseInt(m, 10)}.${y}`;
}

function _nordicToIso(str) {
  const m = _DATE_RE.exec((str || "").trim());
  if (!m) return "";
  const dd = parseInt(m[1], 10), mm = parseInt(m[2], 10), yyyy = parseInt(m[3], 10);
  const d = new Date(Date.UTC(yyyy, mm - 1, dd));
  const valid = d.getUTCFullYear() === yyyy && d.getUTCMonth() === mm - 1 && d.getUTCDate() === dd;
  if (!valid) return "";
  return `${yyyy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
}

// Reads the ISO (yyyy-mm-dd) value behind a Nordic date input, "" if empty/invalid.
function dateInputIso(el) {
  return _nordicToIso(el.value);
}

// Sets a Nordic date input's displayed value from an ISO (yyyy-mm-dd) string.
function setDateInputIso(el, iso) {
  el.value = _isoToNordic(iso);
  el.classList.remove("invalid");
}

let _datePickerPopup = null;
let _datePickerTarget = null;

function _closeDatePicker() {
  if (_datePickerPopup) _datePickerPopup.remove();
  _datePickerPopup = null;
  _datePickerTarget = null;
  document.removeEventListener("mousedown", _onDatePickerOutsideClick, true);
}

function _onDatePickerOutsideClick(e) {
  if (_datePickerPopup && !_datePickerPopup.contains(e.target) && e.target !== _datePickerTarget) {
    _closeDatePicker();
  }
}

const _DATE_PICKER_WEEKDAYS = ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"]; // Monday-first
const _DATE_PICKER_MONTHS = ["January", "February", "March", "April", "May", "June",
                              "July", "August", "September", "October", "November", "December"];

function _renderDatePicker(viewYear, viewMonth) {
  const popup = _datePickerPopup;
  const todayIso = _utcDateStr(Math.floor(Date.now() / 1000));
  const selectedIso = dateInputIso(_datePickerTarget);
  const firstWeekday = (new Date(Date.UTC(viewYear, viewMonth, 1)).getUTCDay() + 6) % 7; // Monday=0
  const daysInMonth = new Date(Date.UTC(viewYear, viewMonth + 1, 0)).getUTCDate();

  let cells = "";
  for (let i = 0; i < firstWeekday; i++) cells += `<span class="date-picker-day empty"></span>`;
  for (let day = 1; day <= daysInMonth; day++) {
    const iso = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cls = ["date-picker-day"];
    if (iso === todayIso) cls.push("today");
    if (iso === selectedIso) cls.push("selected");
    cells += `<button type="button" class="${cls.join(" ")}" data-iso="${iso}">${day}</button>`;
  }

  popup.innerHTML = `
    <div class="date-picker-header">
      <button type="button" class="date-picker-nav" data-nav="-1" aria-label="Previous month">‹</button>
      <span class="date-picker-title">${_DATE_PICKER_MONTHS[viewMonth]} ${viewYear}</span>
      <button type="button" class="date-picker-nav" data-nav="1" aria-label="Next month">›</button>
    </div>
    <div class="date-picker-weekdays">${_DATE_PICKER_WEEKDAYS.map(w => `<span>${w}</span>`).join("")}</div>
    <div class="date-picker-grid">${cells}</div>
  `;

  popup.querySelector('[data-nav="-1"]').addEventListener("click", () => {
    viewMonth === 0 ? _renderDatePicker(viewYear - 1, 11) : _renderDatePicker(viewYear, viewMonth - 1);
  });
  popup.querySelector('[data-nav="1"]').addEventListener("click", () => {
    viewMonth === 11 ? _renderDatePicker(viewYear + 1, 0) : _renderDatePicker(viewYear, viewMonth + 1);
  });
  popup.querySelectorAll(".date-picker-day[data-iso]").forEach(btn => {
    btn.addEventListener("click", () => {
      setDateInputIso(_datePickerTarget, btn.dataset.iso);
      _datePickerTarget.dispatchEvent(new Event("change"));
      _closeDatePicker();
    });
  });
}

function _openDatePicker(inputEl) {
  if (_datePickerTarget === inputEl) return;
  _closeDatePicker();
  _datePickerTarget = inputEl;
  _datePickerPopup = document.createElement("div");
  _datePickerPopup.className = "date-picker-popup";
  document.body.appendChild(_datePickerPopup);

  const iso = dateInputIso(inputEl);
  const base = iso ? new Date(`${iso}T00:00:00Z`) : new Date();
  _renderDatePicker(base.getUTCFullYear(), base.getUTCMonth());

  const rect = inputEl.getBoundingClientRect();
  _datePickerPopup.style.left = `${rect.left + window.scrollX}px`;
  _datePickerPopup.style.top  = `${rect.bottom + window.scrollY + 4}px`;

  setTimeout(() => document.addEventListener("mousedown", _onDatePickerOutsideClick, true), 0);
}

// Strips anything that isn't a digit or "." as the admin types — day/month
// aren't fixed-width in this format (5.5.2026 is as valid as 15.05.2026), so
// separators aren't auto-inserted; the admin types the dots themselves.
function _restrictDateChars(e) {
  e.target.value = e.target.value.replace(/[^\d.]/g, "");
}

// Wires a d.m.yyyy text input to open the calendar picker on click/focus and
// to flag itself invalid on blur if it holds unparseable text. Idempotent.
function _initNordicDateInput(id) {
  const el = document.getElementById(id);
  if (!el || el.dataset.datePickerInit) return;
  el.dataset.datePickerInit = "1";
  el.addEventListener("focus", () => _openDatePicker(el));
  el.addEventListener("click", () => _openDatePicker(el));
  el.addEventListener("input", _restrictDateChars);
  el.addEventListener("blur", () => {
    el.classList.toggle("invalid", !!el.value && !dateInputIso(el));
  });
}

function initWeekDateInputs() {
  ["weekStart", "weekEnd", "editWeekStart", "editWeekEnd"].forEach(_initNordicDateInput);
}
