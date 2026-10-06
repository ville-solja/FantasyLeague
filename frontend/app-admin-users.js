let _allTags = [];
let _cachedUsers = [];

function _userAccountType() {
  return document.getElementById("userAccountType")?.value === "twitch" ? "twitch" : "full";
}

async function loadUsers() {
  try {
    const res = await fetch(`${API}/users?account_type=${_userAccountType()}`);
    const rows = await res.json();
    if (!res.ok) return setStatus("usersStatus", rows.detail, false);
    _cachedUsers = rows;
    _renderUsers(rows);
    setStatus("usersStatus", "");
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

function _fmtUserDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString() : "—";
}

// Issue #157: Twitch viewer soft accounts — tokens, card count, created and last
// seen; no password, tag or admin actions; delete is available.
function _renderTwitchViewerRow(u) {
  return `<tr data-user-id="${u.id}">
      <td>${_escHtml(u.username)}${u.twitch_identity_shared ? ' <span class="badge" style="background:var(--k-ink-700,#2a2a30);color:#aaa;font-size:0.7rem;">ID SHARED</span>' : ""}</td>
      <td style="font-size:0.8rem;color:#aaa;">${u.card_count} cards · created ${_fmtUserDate(u.created_at)} · last seen ${_fmtUserDate(u.last_seen_at)}</td>
      <td>${u.tokens}</td>
      <td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
        <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
        <button class="danger" style="font-size:0.8rem;" onclick="deleteTwitchViewer(${u.id})">Delete</button>
      </td>
    </tr>`;
}

async function deleteTwitchViewer(userId) {
  const user = _cachedUsers.find(u => u.id === userId);
  if (!confirm(`Delete ${user ? user.username : "this Twitch viewer"} and all their cards? This cannot be undone.`)) return;
  try {
    const res = await adminFetch(`${API}/admin/users/${userId}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) return setStatus("usersStatus", data.detail, false);
    setStatus("usersStatus", "Twitch viewer deleted");
    loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

function _renderUsers(rows) {
  const search = (document.getElementById("userSearch")?.value || "").toLowerCase();
  const visible = search ? rows.filter(u => u.username.toLowerCase().includes(search)) : rows;
  document.getElementById("usersBody").innerHTML = visible.map(u => {
    if (u.account_type === "twitch") return _renderTwitchViewerRow(u);
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
      <td>${_escHtml(u.username)}${testerBadge}${adminBadge}</td>
      <td>${tagChips || '<span style="color:#555;font-size:0.8rem;">—</span>'}</td>
      <td>${u.tokens}</td>
      <td style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
        <input type="number" min="1" value="1" id="grant_${u.id}" style="width:60px;flex:none;" />
        <button class="secondary" onclick="grantTokens(${u.id})">Grant</button>
        <button class="ghost" style="font-size:0.8rem;" onclick="toggleTester(${u.id})">${u.is_tester ? "Unmark tester" : "Mark tester"}</button>
        ${adminToggleBtn}
        <button class="ghost" style="font-size:0.8rem;" onclick="openTagManager(${u.id})">Manage tags</button>
        <button class="ghost" style="font-size:0.8rem;" onclick="forceLogout(${u.id})">Force logout</button>
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
    if (!res.ok) {
      // A 422 detail is a list of validation errors; show the msg fields as text.
      const msg = Array.isArray(data.detail)
        ? data.detail.map(e => {
            const field = e.loc ? e.loc[e.loc.length - 1] : "";
            return field === "key"
              ? "Key may only use lowercase letters, digits, _ and -, and must start with a letter or digit"
              : (e.msg || "Invalid value");
          }).join("; ")
        : data.detail;
      return setStatus("tagsStatus", msg, false);
    }
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
    const res = await adminFetch(`${API}/users/${userId}/toggle-admin`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("usersStatus", data.detail, false);
    setStatus("usersStatus", `${data.username} ${data.is_admin ? "promoted to admin" : "demoted from admin"}`);
    loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function forceLogout(userId) {
  const user = _cachedUsers.find(u => u.id === userId);
  const name = user ? user.username : `user ${userId}`;
  const self = userId === activeUserId ? " This includes your own session." : "";
  if (!confirm(`Force logout ${name}? Every session of this user ends now.${self}`)) return;
  try {
    const res = await fetch(`${API}/users/${userId}/force-logout`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("usersStatus", data.detail, false);
    if (userId === activeUserId) return _clearLocalAuthState();
    setStatus("usersStatus", `${data.username} logged out of every session`);
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

// Issue #160: recent Twitch collection merges with Reverse. Both calls need the
// admin password re-check (adminFetch shows the prompt). No Twitch ids are returned.
let _twitchMerges = [];

async function loadTwitchMerges() {
  try {
    const res = await adminFetch(`${API}/admin/twitch/merges`);
    const rows = await res.json();
    if (!res.ok) return setStatus("twitchMergesStatus", rows.detail, false);
    _twitchMerges = rows;
    _renderTwitchMerges(rows);
    setStatus("twitchMergesStatus", rows.length ? "" : "No merges in the last 30 days");
  } catch (e) {
    setStatus("twitchMergesStatus", e.message, false);
  }
}

function _renderTwitchMerges(rows) {
  const table = document.getElementById("twitchMergesTable");
  const tbody = document.getElementById("twitchMergesBody");
  table.style.display = rows.length ? "" : "none";
  tbody.replaceChildren();
  rows.forEach(m => {
    const tr = document.createElement("tr");
    const who = document.createElement("td");
    who.textContent = m.username || `User #${m.full_user_id}`;
    const when = document.createElement("td");
    when.textContent = new Date(Number(m.merged_at) * 1000).toLocaleString();
    const moved = document.createElement("td");
    moved.textContent = `${m.cards} cards · ${m.tokens_moved} tokens`;
    const action = document.createElement("td");
    if (m.reversible) {
      const btn = document.createElement("button");
      btn.className = "danger";
      btn.textContent = "Reverse";
      btn.addEventListener("click", () => reverseTwitchMerge(m.id));
      action.appendChild(btn);
    } else {
      action.textContent = m.reversed_at ? "Reversed" : (m.blocked_reason || "Not reversible");
    }
    tr.append(who, when, moved, action);
    tbody.appendChild(tr);
  });
}

async function reverseTwitchMerge(logId) {
  const merge = _twitchMerges.find(m => m.id === logId);
  const who = merge ? (merge.username || `user #${merge.full_user_id}`) : "this account";
  if (!confirm(`Reverse the Twitch merge into ${who}? The Twitch viewer account is recreated with its cards and tokens, and ${who} is disconnected from Twitch.`)) return;
  try {
    const res = await adminFetch(`${API}/admin/twitch/merges/${encodeURIComponent(logId)}/reverse`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("twitchMergesStatus", data.detail, false);
    const shortfall = data.token_shortfall ? ` ${data.token_shortfall} tokens had already been spent.` : "";
    setStatus("twitchMergesStatus", `Merge reversed: ${data.cards_returned} cards and ${data.tokens_returned} tokens returned.${shortfall}`);
    loadTwitchMerges();
    loadUsers();
  } catch (e) {
    setStatus("twitchMergesStatus", e.message, false);
  }
}
