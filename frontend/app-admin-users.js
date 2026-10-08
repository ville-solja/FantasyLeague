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
    loadPlayerIdClaims();
    loadTwitchStatus();
    loadTwitchChannels();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

// Issue #150: self-reported player ids cleared because a Steam-verified account has the id.
async function loadPlayerIdClaims() {
  const tbody = document.getElementById("playerIdClaimsBody");
  if (!tbody) return;
  try {
    const res = await fetch(`${API}/admin/player-id-claims`);
    const rows = await res.json();
    if (!res.ok) return setStatus("playerIdClaimsStatus", rows.detail, false);
    tbody.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.textContent = "None";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    rows.forEach(r => {
      const tr = document.createElement("tr");
      [r.superseded_username || `user ${r.superseded_user_id}`,
       r.verified_username || `user ${r.verified_user_id}`,
       String(r.player_id),
       new Date(Number(r.timestamp) * 1000).toLocaleString()].forEach(text => {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  } catch (e) {
    setStatus("playerIdClaimsStatus", e.message, false);
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
  const confirmText = await typedConfirm("delete_user",
    `Delete ${user ? user.username : "this Twitch viewer"} and all their cards? This cannot be undone.`);
  if (confirmText === null) return;
  try {
    const res = await adminFetch(`${API}/admin/users/${userId}?confirm=${encodeURIComponent(confirmText)}`, { method: "DELETE" });
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
    const res = await adminFetch(`${API}/users/${userId}/toggle-tester`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("usersStatus", data.detail, false);
    setStatus("usersStatus", `${data.username} ${data.is_tester ? "marked as tester" : "unmarked as tester"}`);
    loadUsers();
  } catch (e) {
    setStatus("usersStatus", e.message, false);
  }
}

async function toggleAdmin(userId) {
  const user = _cachedUsers.find(u => u.id === userId);
  const name = user ? user.username : `user ${userId}`;
  const confirmText = await typedConfirm("toggle_admin",
    user && user.is_admin ? `Demote ${name} from admin.` : `Promote ${name} to admin.`);
  if (confirmText === null) return;
  try {
    const res = await adminFetch(`${API}/users/${userId}/toggle-admin?confirm=${encodeURIComponent(confirmText)}`, { method: "POST" });
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
  const user = _cachedUsers.find(u => u.id === targetId);
  const confirmText = await typedConfirm("grant_tokens",
    `Grant ${amount} ${_tokenName} to ${user ? user.username : `user ${targetId}`}.`);
  if (confirmText === null) return;
  const btn = input.nextElementSibling;
  if (btn) btn.disabled = true;
  try {
    const res = await adminFetch(`${API}/grant-tokens`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({target_user_id: targetId, amount, confirm: confirmText}) });
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
      document.getElementById("codesBody").innerHTML = "<tr><td colspan='5' style='color:#444'>No codes yet</td></tr>";
      return;
    }
    document.getElementById("codesBody").innerHTML = rows.map(c => `
      <tr data-code-id="${c.id}">
        <td><code>${_escHtml(c.code)}</code></td>
        <td>${c.token_amount}</td>
        <td>${c.redemptions}${c.max_redemptions ? " / " + c.max_redemptions : ""}</td>
        <td>${_codeLimitsText(c)}</td>
        <td><button class="ghost" style="font-size:0.8rem;" onclick="deleteCode(${c.id})">Delete</button></td>
      </tr>`).join("");
    setStatus("codesStatus", "");
  } catch (e) {
    setStatus("codesStatus", e.message, false);
  }
}

// Issue #167: a code can expire and can cap its total redemptions.
function _codeLimitsText(c) {
  const parts = [];
  if (c.expires_at) {
    const expired = c.expires_at * 1000 <= Date.now();
    parts.push((expired ? "Expired " : "Expires ") + new Date(c.expires_at * 1000).toLocaleString());
  }
  if (c.max_redemptions) parts.push(`Max ${c.max_redemptions} uses`);
  return parts.length ? _escHtml(parts.join(" · ")) : "—";
}

async function createCode() {
  const code   = document.getElementById("newCodeInput").value.trim().toUpperCase();
  const amount = parseInt(document.getElementById("newCodeAmount").value);
  const maxUsesRaw = document.getElementById("newCodeMaxUses").value.trim();
  const expiresRaw = document.getElementById("newCodeExpires").value;
  if (!code)        return setStatus("codesStatus", "Enter a code name", false);
  if (!amount || amount < 1) return setStatus("codesStatus", "Enter a token amount ≥ 1", false);
  const body = {code, token_amount: amount};
  if (maxUsesRaw) {
    const maxUses = parseInt(maxUsesRaw);
    if (!maxUses || maxUses < 1) return setStatus("codesStatus", "Max uses must be 1 or more", false);
    body.max_redemptions = maxUses;
  }
  if (expiresRaw) {
    const ts = Math.floor(new Date(expiresRaw).getTime() / 1000);
    if (!ts) return setStatus("codesStatus", "Enter a valid expiry", false);
    body.expires_at = ts;
  }
  try {
    const res = await adminFetch(`${API}/codes`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) return setStatus("codesStatus", data.detail, false);
    document.getElementById("newCodeInput").value  = "";
    document.getElementById("newCodeAmount").value = "";
    document.getElementById("newCodeMaxUses").value = "";
    document.getElementById("newCodeExpires").value = "";
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
  confirm.innerHTML = `<td colspan="5" style="padding:8px 10px;">
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
    const res = await adminFetch(`${API}/codes/${codeId}`, { method: "DELETE" });
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

// Issue #180: Twitch status. Every value goes through _escHtml; the server never
// sends a secret, its length, a token or a viewer's Twitch id.
async function loadTwitchStatus() {
  try {
    const res = await fetch(`${API}/admin/twitch/status`);
    const data = await res.json();
    if (!res.ok) return setStatus("twitchStatusStatus", data.detail, false);
    _renderTwitchStatus(data);
    setStatus("twitchStatusStatus", `Updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    setStatus("twitchStatusStatus", e.message, false);
  }
}

const _TWITCH_STATE_TEXT = { ok: "OK", warning: "Warning", problem: "Problem" };

function _twitchAgo(t) {
  if (!t) return "never";
  const s = Math.max(0, Math.floor(Date.now() / 1000) - Number(t));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function _twitchStatusRow(state, label, detail) {
  const cls = ["ok", "warning", "problem"].includes(state) ? state : "problem";
  return `<tr class="twitch-status-${cls}"><td class="twitch-status-state">${_escHtml(_TWITCH_STATE_TEXT[cls])}</td>` +
    `<td>${_escHtml(label)}</td><td>${_escHtml(detail)}</td></tr>`;
}

function _renderTwitchStatus(data) {
  const t = data.traffic || {};
  const f = t.failures || {};
  const refusedTotal = (f.expired || 0) + (f.invalid || 0) + (f.not_configured || 0);
  const origins = t.refused_origins || [];
  const traffic = [
    _twitchStatusRow(t.last_extension_request_at ? "ok" : "warning", "Last request from the extension",
      t.last_extension_request_at ? _twitchAgo(t.last_extension_request_at) :
        "None since the last restart: the panel is not reaching this server. Open the panel on a channel; " +
        "if this stays empty, check the extension's ebs_url, the URL Fetching Domains in the Twitch console, " +
        "and that this server answers over HTTPS from the internet. A refused host below means a Client ID mismatch."),
    _twitchStatusRow(t.last_ok_at ? "ok" : "warning", "Last panel request with an accepted token",
      t.last_ok_at ? _twitchAgo(t.last_ok_at) : "None since the last restart. Open the panel on a channel to test."),
    _twitchStatusRow(refusedTotal ? "problem" : "ok", "Refused Twitch tokens",
      `${f.expired || 0} expired, ${f.invalid || 0} invalid, ${f.not_configured || 0} server not configured` +
      (t.last_failure_at ? `; last ${_twitchAgo(t.last_failure_at)}` : "") +
      (f.invalid ? ". Invalid tokens usually mean TWITCH_EXTENSION_SECRET belongs to another extension." : ".")),
    _twitchStatusRow(origins.length ? "warning" : "ok", "Cross-origin hosts refused on /twitch/*",
      origins.length ? `${origins.join(", ")}. If one is the extension's host, check TWITCH_EXTENSION_CLIENT_ID.` : "None."),
  ];
  const head = `<thead><tr><th>State</th><th>Check</th><th>What to do</th></tr></thead>`;
  const checks = (data.checks || []).map(c => _twitchStatusRow(c.state, c.label, c.detail)).join("");
  const consoleRows = (data.console || []).map(c =>
    `<tr><td>${_escHtml(c.label)}</td><td><code>${_escHtml(c.expected)}</code></td></tr>`).join("");
  document.getElementById("adminTwitchStatus").innerHTML =
    `<table class="twitch-status-table">${head}<tbody>${checks}</tbody></table>` +
    `<div class="twitch-merges-title">Panel traffic since the last restart</div>` +
    `<table class="twitch-status-table">${head}<tbody>${traffic.join("")}</tbody></table>` +
    `<div class="twitch-merges-title">Twitch console</div>` +
    `<p class="twitch-merges-note">Checked by hand in the Twitch developer console; each must hold the value shown.</p>` +
    `<table><thead><tr><th>Check</th><th>Expected value</th></tr></thead><tbody>${consoleRows}</tbody></table>`;
}

// Issue #175: approved streamers. Channels from TWITCH_MVP_CHANNEL_IDS are approved
// from server settings and have no Remove button. Approve / Reject / Remove need the
// admin password re-check (adminFetch shows the prompt).
async function loadTwitchChannels() {
  try {
    const res = await fetch(`${API}/admin/twitch/channels`);
    const data = await res.json();
    if (!res.ok) return setStatus("twitchChannelsStatus", data.detail, false);
    _renderTwitchChannels(data);
    setStatus("twitchChannelsStatus", "");
  } catch (e) {
    setStatus("twitchChannelsStatus", e.message, false);
  }
}

function _twitchChannelRow(c, actions) {
  const name = c.display_name
    ? `${_escHtml(c.display_name)}${c.login ? ` <span style="color:#888">(${_escHtml(c.login)})</span>` : ""}`
    : `<span style="color:#888">Name unknown</span>`;
  const date = t => t ? new Date(Number(t) * 1000).toLocaleDateString() : "—";
  const note = c.from_env ? `<div style="color:#888;font-size:12px">from server settings</div>` : "";
  const buttons = actions.map(([action, label, cls]) =>
    `<button class="${cls}" onclick="twitchChannelAction('${_escHtml(c.channel_id)}', '${action}')">${label}</button>`).join(" ");
  return `<tr><td>${name}${note}</td><td>${_escHtml(c.channel_id)}</td>` +
    `<td>${date(c.first_seen_at)}</td><td>${date(c.last_seen_at)}</td><td>${buttons}</td></tr>`;
}

function _twitchChannelTable(rows, actions, empty) {
  if (!rows.length) return `<p style="color:#888">${empty}</p>`;
  return `<table><thead><tr><th>Channel</th><th>Channel id</th><th>First seen</th><th>Last seen</th><th>Actions</th></tr></thead>` +
    `<tbody>${rows.map(c => _twitchChannelRow(c, actions(c))).join("")}</tbody></table>`;
}

function _renderTwitchChannels(data) {
  const approved = [...(data.env || []), ...(data.approved || [])];
  const pending = data.pending || [];
  const rejected = data.rejected || [];
  document.getElementById("twitchChannels").innerHTML =
    `<div class="twitch-merges-title">Waiting for approval</div>` +
    _twitchChannelTable(pending, () => [["approve", "Approve", "secondary"], ["reject", "Reject", "danger"]],
      "No channels are waiting.") +
    `<div class="twitch-merges-title">Approved</div>` +
    _twitchChannelTable(approved, c => c.from_env ? [] : [["remove", "Remove", "danger"]],
      "No channels are approved. With ENV=production no channel can set match MVPs.") +
    `<details><summary>Rejected (${rejected.length})</summary>` +
    _twitchChannelTable(rejected, () => [["approve", "Approve", "secondary"]], "No rejected channels.") +
    `</details>`;
}

async function twitchChannelAction(channelId, action) {
  const verb = { approve: "Approve", reject: "Reject", remove: "Remove" }[action];
  if (!verb) return;
  if (action !== "approve" && !confirm(`${verb} channel ${channelId}? It will not be able to set match MVPs.`)) return;
  try {
    const res = await adminFetch(`${API}/admin/twitch/channels/${encodeURIComponent(channelId)}/${action}`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) return setStatus("twitchChannelsStatus", data.detail, false);
    const who = data.display_name || data.channel_id;
    setStatus("twitchChannelsStatus", action === "approve" ? `${who} can now set match MVPs` : `${who} moved to Rejected`);
    loadTwitchChannels();
  } catch (e) {
    setStatus("twitchChannelsStatus", e.message, false);
  }
}
