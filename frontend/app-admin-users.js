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
    const adminBadge = u.is_admin
      ? ` <span class="badge" style="background:var(--k-flame-700,#8a2e0c);color:#fff;font-size:0.7rem;">ADMIN</span>`
      : "";
    const tagChips = (u.tags || []).map(t =>
      `<span style="display:inline-block;background:var(--k-flame-500,#DC5014);color:#fff;font-size:0.65rem;padding:1px 6px;border-radius:2px;margin-right:3px;">${t.label}</span>`
    ).join("");
    const adminToggleBtn = u.id === activeUserId ? "" :
      `<button class="ghost" style="font-size:0.8rem;" onclick="toggleAdmin(${u.id})">${u.is_admin ? "Demote from admin" : "Promote to admin"}</button>`;
    return `<tr data-user-id="${u.id}">
      <td>${u.username}${testerBadge}${adminBadge}</td>
      <td>${tagChips || '<span style="color:#555;font-size:0.8rem;">—</span>'}</td>
      <td>${u.tokens}</td>
      <td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
        <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
        <button class="ghost" style="font-size:0.8rem;" onclick="toggleTester(${u.id})">${u.is_tester ? "Unmark tester" : "Mark tester"}</button>
        ${adminToggleBtn}
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

async function toggleAdmin(userId) {
  try {
    const res = await fetch(`${API}/users/${userId}/toggle-admin`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("usersStatus", data.detail, false);
    setStatus("usersStatus", `${data.username} ${data.is_admin ? "promoted to admin" : "demoted from admin"}`);
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
