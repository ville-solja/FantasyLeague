let _playersData = [];

async function loadPlayers() {
  try {
    const res = await fetch(`${API}/players`);
    const rows = await res.json();
    _playersData = rows;
    renderPlayers(rows);
    setStatus("playersStatus", `${rows.length} players`);
  } catch (e) {
    setStatus("playersStatus", e.message, false);
  }
}

function filterPlayers() {
  const q = document.getElementById("playersSearch").value.toLowerCase();
  const filtered = _playersData.filter(p =>
    p.name.toLowerCase().includes(q) || (p.team_name || "").toLowerCase().includes(q)
  );
  renderPlayers(filtered);
}

function renderPlayers(rows) {
  const tbody = document.getElementById("playersBody");
  if (!rows.length) {
    tbody.innerHTML = "<tr><td colspan='5' style='color:#444'>No players found</td></tr>";
    return;
  }
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td><img src="${p.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" />${playerLink(p.id, p.name)}</td>
      <td>${p.team_id ? teamLink(p.team_id, p.team_name) : (p.team_name || "—")}</td>
      <td>${p.matches}</td>
      <td>${Number(p.avg_points).toFixed(1)}</td>
      <td>${Number(p.total_points).toFixed(1)}</td>
    </tr>`).join("");
}

async function loadTeams() {
  try {
    const res = await fetch(`${API}/teams`);
    const rows = await res.json();
    const tbody = document.getElementById("teamsBody");
    if (!rows.length) {
      tbody.innerHTML = "<tr><td colspan='3' style='color:#444'>No teams found</td></tr>";
      setStatus("teamsStatus", "");
      return;
    }
    tbody.innerHTML = rows.map(t => `
      <tr>
        <td>${teamLink(t.id, t.name)}</td>
        <td>${t.matches}</td>
        <td>${t.player_count}</td>
      </tr>`).join("");
    setStatus("teamsStatus", `${rows.length} teams`);
  } catch (e) {
    setStatus("teamsStatus", e.message, false);
  }
}

async function openPlayerModal(playerId) {
  const modal = document.getElementById("playerModal");
  modal.classList.remove("hidden");
  document.getElementById("playerModalName").textContent = "Loading...";
  document.getElementById("playerModalTeam").innerHTML = "";
  document.getElementById("playerModalAvatar").style.display = "none";
  document.getElementById("playerModalStats").innerHTML = "";
  document.getElementById("playerModalHistory").innerHTML = "";
  document.getElementById("playerModalStatus").textContent = "";
  const profileEl = document.getElementById("playerProfile");
  if (profileEl) { profileEl.style.display = "none"; profileEl.innerHTML = ""; }

  try {
    const res = await fetch(`${API}/players/${playerId}`);
    const p = await res.json();
    if (!res.ok) {
      document.getElementById("playerModalName").textContent = "";
      setStatus("playerModalStatus", p.detail || "Failed to load", false);
      return;
    }

    const avatar = document.getElementById("playerModalAvatar");
    if (p.avatar_url) { avatar.src = p.avatar_url; avatar.style.display = ""; }

    document.getElementById("playerModalName").textContent = p.name;
    document.getElementById("playerModalTeam").innerHTML = p.team_id
      ? `<span class="entity-link" onclick="closePlayerModal();openTeamModal(${p.team_id})">${p.team_name}</span>`
      : (p.team_name || "");

    document.getElementById("playerModalStats").innerHTML = `
      <div class="player-modal-stat-grid">
        <div class="player-modal-stat"><div class="val">${p.matches}</div><div class="lbl">Matches</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.avg_points).toFixed(1)}</div><div class="lbl">Avg pts</div></div>
        <div class="player-modal-stat"><div class="val">${Number(p.total_points).toFixed(1)}</div><div class="lbl">Total pts</div></div>
        ${p.best_match ? `<div class="player-modal-stat"><div class="val">${Number(p.best_match.fantasy_points).toFixed(1)}</div><div class="lbl">Best match</div></div>` : ""}
      </div>`;

    if (!p.match_history.length) {
      document.getElementById("playerModalHistory").innerHTML =
        "<tr><td colspan='4' style='color:#444'>No matches yet</td></tr>";
    } else {
      document.getElementById("playerModalHistory").innerHTML = p.match_history.map(m => {
        const date = m.start_time
          ? new Date(m.start_time * 1000).toLocaleDateString("fi-FI", {day: "numeric", month: "numeric", year: "2-digit"})
          : "—";
        const mvpBadge = m.is_mvp ? ' <span style="font-size:0.7rem;color:#f5c842;font-weight:700;letter-spacing:0.05em;">MVP</span>' : '';
        return `<tr>
          <td>${date}</td>
          <td>${Number(m.fantasy_points).toFixed(1)}${mvpBadge}</td>
          <td>${m.kills}/${m.assists}/${m.deaths}</td>
          <td>${Math.round(m.gold_per_min)}</td>
        </tr>`;
      }).join("");
    }

    // Non-blocking profile fetch — modal shows immediately even if profile unavailable
    fetch(`${API}/players/${playerId}/profile`).then(async r => {
      if (!r.ok) return;
      renderPlayerProfile(await r.json());
    }).catch(() => {});
  } catch (e) {
    setStatus("playerModalStatus", e.message, false);
  }
}

function renderPlayerProfile(profile) {
  const facts = profile && profile.facts;
  if (!facts) return;
  const el = document.getElementById("playerProfile");
  if (!el) return;

  const statGrid = `
    <div class="player-modal-stat-grid" style="margin-top:8px;">
      <div class="player-modal-stat"><div class="val">${facts.kanaliiga_seasons}</div><div class="lbl">Seasons</div></div>
      <div class="player-modal-stat"><div class="val">${Number(facts.avg_kills).toFixed(1)}</div><div class="lbl">Avg K</div></div>
      <div class="player-modal-stat"><div class="val">${Number(facts.avg_deaths).toFixed(1)}</div><div class="lbl">Avg D</div></div>
      <div class="player-modal-stat"><div class="val">${Number(facts.avg_assists).toFixed(1)}</div><div class="lbl">Avg A</div></div>
      <div class="player-modal-stat"><div class="val">${Math.round(facts.avg_gpm)}</div><div class="lbl">Avg GPM</div></div>
      <div class="player-modal-stat"><div class="val">${Number(facts.avg_wards).toFixed(1)}</div><div class="lbl">Avg wards</div></div>
      <div class="player-modal-stat"><div class="val">${facts.role_tendency}</div><div class="lbl">Role</div></div>
    </div>`;

  function heroLine(h) {
    return h.win_rate !== undefined
      ? `<span style="color:#aaa">${h.hero_name}</span> <span style="color:#555;font-size:0.78rem;">(${h.games}g, ${Math.round(h.win_rate*100)}%wr)</span>`
      : `<span style="color:#aaa">${h.hero_name}</span> <span style="color:#555;font-size:0.78rem;">(${h.games}g)</span>`;
  }
  function heroSection(label, heroes, limit) {
    const items = (heroes || []).slice(0, limit).map(heroLine).join(", ") || "—";
    return `<div style="margin-bottom:6px;"><span class="player-bio-eyebrow">${label}</span><br><span style="font-size:var(--fs-sm);">${items}</span></div>`;
  }

  const heroes = `<div style="margin-top:14px;">
    ${heroSection("Career heroes", facts.top_heroes_alltime, 5)}
    ${heroSection("Tournament heroes", facts.tournament_heroes, 5)}
    ${heroSection("Recent pub heroes", facts.recent_pub_heroes, 5)}
  </div>`;

  const bioSection = profile.bio_text
    ? `<div style="margin-top:14px;padding:10px 14px;background:#0f1a0f;border:1px solid #1a3a1a;border-radius:6px;font-size:0.85rem;color:#aaa;line-height:1.6;">${profile.bio_text}</div>`
    : "";

  el.innerHTML = statGrid + heroes + bioSection;
  el.style.display = "block";
}

function closePlayerModal() {
  document.getElementById("playerModal").classList.add("hidden");
}

async function openTeamModal(teamId) {
  const modal = document.getElementById("teamModal");
  modal.classList.remove("hidden");
  document.getElementById("teamModalName").textContent = "Loading...";
  document.getElementById("teamModalMeta").textContent = "";
  document.getElementById("teamModalPlayers").innerHTML = "";
  document.getElementById("teamModalStatus").textContent = "";

  try {
    const res = await fetch(`${API}/teams/${teamId}`);
    const t = await res.json();
    if (!res.ok) {
      document.getElementById("teamModalName").textContent = "";
      setStatus("teamModalStatus", t.detail || "Failed to load", false);
      return;
    }

    document.getElementById("teamModalName").textContent = t.name;
    document.getElementById("teamModalMeta").textContent = `${t.matches} matches`;

    if (!t.players.length) {
      document.getElementById("teamModalPlayers").innerHTML =
        "<tr><td colspan='4' style='color:#444'>No players found</td></tr>";
    } else {
      document.getElementById("teamModalPlayers").innerHTML = t.players.map(p => `
        <tr>
          <td><img src="${p.avatar_url || ''}" style="width:24px;height:24px;border-radius:50%;vertical-align:middle;margin-right:6px;" onerror="this.style.display='none'" /><span class="entity-link" onclick="closeTeamModal();openPlayerModal(${p.id})">${p.name}</span></td>
          <td>${p.matches}</td>
          <td>${Number(p.avg_points).toFixed(1)}</td>
          <td>${Number(p.total_points).toFixed(1)}</td>
        </tr>`).join("");
    }
  } catch (e) {
    setStatus("teamModalStatus", e.message, false);
  }
}

function closeTeamModal() {
  document.getElementById("teamModal").classList.add("hidden");
}

async function loadSchedule() {
  const content = document.getElementById("scheduleContent");
  const staleEl = document.getElementById("scheduleStale");
  content.innerHTML = "<span style='color:#444'>Loading...</span>";
  staleEl.style.display = "none";
  try {
    const res = await fetch(`${API}/schedule`);
    const data = await res.json();
    if (!res.ok) { setStatus("scheduleStatus", data.detail || "Failed to load", false); content.innerHTML = ""; return; }

    if (data.stale) {
      staleEl.textContent = `Cached data from ${data.cached_at ? new Date(data.cached_at).toLocaleString() : "unknown"}`;
      staleEl.style.display = "";
    }
    if (data.error && !data.weeks?.length) {
      content.innerHTML = `<span style='color:#555'>${data.error}</span>`;
      setStatus("scheduleStatus", "");
      return;
    }
    if (!data.weeks?.length) {
      content.innerHTML = "<span style='color:#555'>No schedule data available.</span>";
      setStatus("scheduleStatus", "");
      return;
    }

    const allSeries = [];
    for (const week of data.weeks) {
      for (const s of (week.div1 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div1"});
      for (const s of (week.div2 || [])) if (s.datetime_iso) allSeries.push({...s, division: "div2"});
    }

    const upcoming = allSeries.filter(s => s.match_status !== "past")
                              .sort((a, b) => b.datetime_iso.localeCompare(a.datetime_iso));
    const past     = allSeries.filter(s => s.match_status === "past")
                              .sort((a, b) => b.datetime_iso.localeCompare(a.datetime_iso));

    function _seriesDateLabel(s) {
      const ts = (s.series_result && s.series_result.start_time)
        ? s.series_result.start_time * 1000
        : (s.datetime_iso ? new Date(s.datetime_iso).getTime() : null);
      if (!ts) return "Unknown date";
      return new Date(ts).toLocaleDateString("fi-FI", {weekday: "short", day: "numeric", month: "numeric", year: "numeric"});
    }

    function _groupByDate(series) {
      const groups = [], index = {};
      for (const s of series) {
        const key = _seriesDateLabel(s);
        if (!index[key]) { index[key] = []; groups.push({key, items: index[key]}); }
        index[key].push(s);
      }
      return groups;
    }

    const renderRow = s => {
      const isPast = s.match_status === "past";
      const divLabel = s.division === "div1"
        ? `<span class="badge badge-division div1">Div 1</span>`
        : `<span class="badge badge-division div2">Div 2</span>`;

      const r = s.series_result;
      const scoreHtml = r
        ? `<span class="series-score">${r.team1_wins}–${r.team2_wins}</span>`
        : `<span class="series-score no-result">vs</span>`;

      let linksContent = "";
      if (isPast && r && r.match_ids && r.match_ids.length) {
        linksContent = r.match_ids.map((id, i) =>
          `<a class="stream-link" href="https://www.opendota.com/matches/${id}" target="_blank" rel="noopener noreferrer">G${i + 1} ↗</a>`
        ).join("");
        if (s.stream_url) {
          linksContent += `<a class="stream-link" href="${s.stream_url}" target="_blank" rel="noopener">${s.stream_label || "Stream"} ↗</a>`;
        }
      } else if (!isPast) {
        const time = s.time ? `<span class="series-time">${s.time}</span>` : "";
        const watch = s.stream_url
          ? `<a class="stream-link" href="${s.stream_url}" target="_blank" rel="noopener">${s.stream_label || "Watch"} ↗</a>`
          : (s.stream_label ? `<span style="color:#555">${s.stream_label}</span>` : "");
        linksContent = time + (time && watch ? " · " : "") + watch;
      }

      return `<div class="series-row${isPast ? " past" : ""}">
        ${divLabel}
        <span class="series-team">${s.team1_id ? teamLink(s.team1_id, s.team1) : (s.team1 || "—")}</span>
        ${scoreHtml}
        <span class="series-team right">${s.team2_id ? teamLink(s.team2_id, s.team2) : (s.team2 || "—")}</span>
        <span class="series-links">${linksContent}</span>
      </div>`;
    };

    const renderGroup = (groups) => groups.map(g =>
      `<div class="schedule-date-hd">${g.key}</div>` + g.items.map(renderRow).join("")
    ).join("");

    let html = "";
    if (upcoming.length) {
      html += `<div class="schedule-section">Upcoming</div>` + renderGroup(_groupByDate(upcoming));
    }
    if (past.length) {
      html += `<div class="schedule-section">Results</div>` + renderGroup(_groupByDate(past));
    }
    content.innerHTML = html || "<span style='color:#555'>No dated fixtures found.</span>";

    setStatus("scheduleStatus", "");
  } catch (e) {
    setStatus("scheduleStatus", e.message, false);
    content.innerHTML = "";
  }
}

function showPlayerPreview(name, avatarUrl) {
  const preview = document.getElementById("profilePlayerPreview");
  document.getElementById("profilePlayerName").textContent = name || "";
  const avatar = document.getElementById("profilePlayerAvatar");
  if (avatarUrl) { avatar.src = avatarUrl; avatar.style.display = ""; }
  else { avatar.style.display = "none"; }
  preview.style.display = name ? "flex" : "none";
}
