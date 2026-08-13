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
