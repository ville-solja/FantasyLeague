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
    const res = await adminFetch(`${API}/admin/backups`);
    const data = await res.json();
    if (!res.ok) return setStatus("dbBackupsStatus", data.detail, false);
    document.getElementById("dbBackupsRetention").textContent = data.retention_days;
    if (!data.backups.length) {
      tbody.innerHTML = "<tr><td colspan='4' style='color:#444'>No backups yet</td></tr>";
      return;
    }
    tbody.innerHTML = data.backups.map(b => {
      const name = _escHtml(b.filename);
      const created = new Date(b.created_at * 1000).toLocaleString();
      // A plain link could not answer a re-auth prompt, so the download goes through adminFetch.
      return `<tr><td style="font-size:0.8rem;">${name}</td><td style="font-size:0.8rem;">${_escHtml(created)}</td>`
        + `<td>${_formatBytes(b.size_bytes)}</td><td><button class="secondary" data-filename="${name}" onclick="downloadBackup(this.dataset.filename)">Download</button></td></tr>`;
    }).join("");
  } catch (e) {
    setStatus("dbBackupsStatus", e.message, false);
  }
}

async function createBackup() {
  const btn = document.getElementById("createBackupBtn");
  btn.disabled = true;
  try {
    const res = await adminFetch(`${API}/admin/backups`, {method: "POST"});
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

async function downloadBackup(filename) {
  const confirmText = await typedConfirm("backup_download", `Download ${filename}. It holds every account's data.`);
  if (confirmText === null) return;
  try {
    const res = await adminFetch(`${API}/admin/backups/${encodeURIComponent(filename)}?confirm=${encodeURIComponent(confirmText)}`);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return setStatus("dbBackupsStatus", data.detail || "Download failed", false);
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    setStatus("dbBackupsStatus", e.message, false);
  }
}
