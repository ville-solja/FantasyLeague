function _formatBytes(n) {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

async function loadBackups() {
  if (!activeIsAdmin) return;
  const tbody = document.getElementById("dbBackupsBody");
  if (!tbody) return;
  try {
    const res = await fetch(`${API}/admin/backups`);
    const data = await res.json();
    if (!res.ok) return setStatus("dbBackupsStatus", data.detail, false);
    document.getElementById("dbBackupsRetention").textContent = data.retention_days;
    if (!data.backups.length) {
      tbody.innerHTML = "<tr><td colspan='4' style='color:#444'>No backups yet</td></tr>";
      return;
    }
    tbody.innerHTML = data.backups.map(b => {
      const name = _escHtml(b.filename);
      const href = _escHtml(`${API}/admin/backups/${encodeURIComponent(b.filename)}`);
      const created = new Date(b.created_at * 1000).toLocaleString();
      return `<tr><td style="font-size:0.8rem;">${name}</td><td style="font-size:0.8rem;">${_escHtml(created)}</td>`
        + `<td>${_formatBytes(b.size_bytes)}</td><td><a href="${href}" download="${name}">Download</a></td></tr>`;
    }).join("");
  } catch (e) {
    setStatus("dbBackupsStatus", e.message, false);
  }
}

async function createBackup() {
  const btn = document.getElementById("createBackupBtn");
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/admin/backups`, {method: "POST"});
    const data = await res.json();
    if (!res.ok) return setStatus("dbBackupsStatus", data.detail, false);
    setStatus("dbBackupsStatus", `Created ${data.filename}`);
    loadBackups();
  } catch (e) {
    setStatus("dbBackupsStatus", e.message, false);
  } finally {
    btn.disabled = false;
  }
}
