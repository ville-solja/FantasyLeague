// Issue 246: the OBS pause-screen overlay. A standalone page (no app modules): it reads
// `teams` (and optional `theme=transparent`) from its URL, polls GET /obs/last-game every
// 30 seconds and redraws the 1920x1080 stage only when the answer changed. A failed
// request keeps the last view; nothing is ever shown as an error over the stream.
(function () {
  "use strict";

  var POLL_MS = 30000;
  var STAGE_W = 1920;
  var STAGE_H = 1080;

  var stage = document.getElementById("obs-stage");
  var params = new URLSearchParams(window.location.search || "");
  var lastKey = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function parseTeams(raw) {
    if (!raw) return null;
    var parts = String(raw).split(",").map(function (p) { return p.trim(); });
    if (parts.length !== 2) return null;
    for (var i = 0; i < 2; i++) {
      if (!/^[0-9]{1,19}$/.test(parts[i]) || /^0+$/.test(parts[i])) return null;
    }
    if (parts[0] === parts[1]) return null;
    return parts;
  }

  function fmtDuration(sec) {
    if (sec == null || !isFinite(sec)) return "";
    var s = Math.max(0, Math.round(sec));
    var m = Math.floor(s / 60);
    var r = s % 60;
    return m + ":" + (r < 10 ? "0" : "") + r;
  }

  function fmtPoints(x) {
    var n = Number(x);
    return isFinite(n) ? n.toFixed(1) : "0.0";
  }

  function safeIcon(u) {
    return typeof u === "string" && /^https?:\/\//i.test(u) ? u : null;
  }

  function scale() {
    var s = Math.min((window.innerWidth || STAGE_W) / STAGE_W, (window.innerHeight || STAGE_H) / STAGE_H);
    stage.style.transform = "scale(" + s + ")";
  }

  function write(html) {
    stage.innerHTML = html;
  }

  function teamName(t) {
    return esc(t && t.team_name ? t.team_name : "Team " + (t ? t.team_id : ""));
  }

  function headerHtml(data, game) {
    var a = data.teams[0], b = data.teams[1];
    var score = data.series_score || {};
    var winA = game && game.winner_team_id === a.team_id;
    var winB = game && game.winner_team_id === b.team_id;
    var mid = "";
    if (game) {
      mid = '<div class="obs-game">Game ' + esc(game.game_number) + '</div>' +
        '<div class="obs-score">Series ' + esc(score[String(a.team_id)] || 0) + "–" +
        esc(score[String(b.team_id)] || 0) + '</div>' +
        '<div class="obs-duration">' + esc(fmtDuration(game.duration)) + '</div>';
    } else {
      mid = '<div class="obs-vs">vs</div>';
    }
    function side(t, win, cls) {
      return '<div class="obs-team ' + cls + (win ? ' obs-winner' : '') + '">' +
        '<span class="obs-team-name">' + teamName(t) + '</span>' +
        (win ? '<span class="obs-winner-mark">Winner</span>' : '') + '</div>';
    }
    return '<header class="obs-header">' + side(a, winA, "obs-team-a") +
      '<div class="obs-meta">' + mid + '</div>' + side(b, winB, "obs-team-b") + '</header>';
  }

  function rowHtml(p) {
    var icon = safeIcon(p.hero_icon);
    return '<tr class="obs-row' + (p.top ? ' obs-top' : '') + '">' +
      '<td class="obs-hero">' + (icon ? '<img src="' + esc(icon) + '" alt="">' : '<span class="obs-hero-empty"></span>') + '</td>' +
      '<td class="obs-name">' + esc(p.player_name || "Unknown") +
      (p.is_mvp ? ' <span class="obs-mvp" title="Match MVP">★</span>' : '') + '</td>' +
      '<td class="obs-kda">' + esc(p.kills) + ' / ' + esc(p.deaths) + ' / ' + esc(p.assists) + '</td>' +
      '<td class="obs-pts">' + esc(fmtPoints(p.raw_points)) + '</td></tr>';
  }

  function columnsHtml(game) {
    return '<div class="obs-columns">' + (game.teams || []).map(function (t) {
      return '<section class="obs-col"><h2 class="obs-col-title">' + teamName(t) + '</h2>' +
        '<table class="obs-players"><thead><tr><th></th><th>Player</th><th>K / D / A</th><th>Points</th></tr></thead>' +
        '<tbody>' + (t.players || []).map(rowHtml).join("") + '</tbody></table></section>';
    }).join("") + '</div>' +
      '<p class="obs-note">Raw fantasy points: before card bonuses</p>';
  }

  function render(data) {
    var html = "";
    if (data.pending_game) {
      html += '<div class="obs-pending">Game ' + esc(data.pending_game) + ' stats are on their way</div>';
    }
    html += headerHtml(data, data.game);
    if (data.game) {
      html += columnsHtml(data.game);
    } else if (!data.pending_game) {
      html += '<p class="obs-waiting">Stats appear here a few minutes after each game ends.</p>';
    }
    return '<div class="obs-frame">' + html + '</div>';
  }

  function refresh(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) return null;
      return res.json();
    }).then(function (data) {
      if (!data || !data.teams || data.teams.length !== 2) return;
      var key = JSON.stringify(data);
      if (key === lastKey) return;
      lastKey = key;
      write(render(data));
    }).catch(function () { /* keep the last view; try again at the next refresh */ });
  }

  if (params.get("theme") === "transparent") {
    document.documentElement.classList.add("theme-transparent");
  }
  scale();
  window.addEventListener("resize", scale);

  var teams = parseTeams(params.get("teams"));
  if (!teams) {
    write('<div class="obs-frame"><p class="obs-setup">This overlay is not set up yet. ' +
      'Build its URL on Kana Cards: How to Play › Streamers › Pause screen overlay.</p></div>');
    return;
  }
  var url = "/obs/last-game?teams=" + teams[0] + "," + teams[1];
  refresh(url);
  setInterval(function () { return refresh(url); }, POLL_MS);
})();
