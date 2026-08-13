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
