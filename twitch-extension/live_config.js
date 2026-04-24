"use strict";

var _seriesData     = [];
var _selectedSeries = null;
var _selectedMatch  = null;
var _selectedPlayer = null;

// ── Navigation ──────────────────────────────────────────────────────────────

function mvpGoTo(step) {
    [0, 1, 2, 3].forEach(function(n) {
        el("mvp-step-" + n).classList.toggle("active", n === step);
    });
    if (step === 0) { _selectedSeries = null; _selectedMatch = null; _selectedPlayer = null; }
}

// ── Init ────────────────────────────────────────────────────────────────────

el("btn-start-mvp").addEventListener("click", loadSeries);
el("btn-confirm-mvp").addEventListener("click", confirmMVP);

el("btn-back-0").addEventListener("click", function() { mvpGoTo(0); });
el("btn-back-1").addEventListener("click", function() { mvpGoTo(1); });
el("btn-back-2").addEventListener("click", function() { mvpGoTo(2); });

function onReady() {}

// ── Step 1: load series ─────────────────────────────────────────────────────

function loadSeries() {
    el("series-list").innerHTML = '<p class="muted">Loading…</p>';
    mvpGoTo(1);
    ebsGet("/twitch/matches/current").then(function(data) {
        _seriesData = (data && data.series) || [];
        var container = el("series-list");
        if (_seriesData.length === 0) {
            container.innerHTML = '<p class="muted">No started matches found for the current week.</p>';
            return;
        }
        container.innerHTML = "";
        _seriesData.forEach(function(series, idx) {
            var div = document.createElement("div");
            div.className = "series-item";
            var matchCount = series.matches.length;
            var mvpCount   = series.matches.filter(function(m) { return m.mvp_player_id; }).length;
            div.innerHTML =
                '<div class="versus">' + series.team1_name + " vs " + series.team2_name + "</div>" +
                '<div class="meta">' + matchCount + " match" + (matchCount !== 1 ? "es" : "") +
                (mvpCount > 0 ? " · " + mvpCount + " MVP set" : "") + "</div>";
            div.addEventListener("click", function() { selectSeries(idx); });
            container.appendChild(div);
        });
    }).catch(function() {
        el("series-list").innerHTML = '<p class="muted">Failed to load matches.</p>';
    });
}

// ── Step 2: matches in selected series ──────────────────────────────────────

function selectSeries(idx) {
    _selectedSeries = _seriesData[idx];
    el("step2-label").textContent =
        _selectedSeries.team1_name + " vs " + _selectedSeries.team2_name + " — select a match:";
    var container = el("match-list");
    container.innerHTML = "";
    _selectedSeries.matches.forEach(function(match) {
        var div = document.createElement("div");
        div.className = "match-item" + (match.mvp_player_id ? " mvp-set" : "");
        var date = new Date(match.start_time * 1000).toLocaleString([], {
            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
        });
        var mvpNote = match.mvp_player_name ? " · MVP: " + match.mvp_player_name : "";
        div.innerHTML =
            '<div style="font-weight:600">Match ' + match.match_number + "</div>" +
            '<div class="meta">' + date + mvpNote + "</div>";
        div.addEventListener("click", function() { selectMatch(match); });
        container.appendChild(div);
    });
    mvpGoTo(2);
}

// ── Step 3: player grid ─────────────────────────────────────────────────────

function selectMatch(match) {
    _selectedMatch  = match;
    _selectedPlayer = null;
    el("step3-label").textContent =
        "Match " + match.match_number + " · " +
        _selectedSeries.team1_name + " vs " + _selectedSeries.team2_name + ":";
    el("confirm-bar").classList.remove("visible");

    var grid = el("player-grid");
    grid.innerHTML = "";

    if (!match.players || match.players.length === 0) {
        grid.innerHTML = '<p class="muted" style="grid-column:span 2">No player stats yet — check back after match data ingests.</p>';
        mvpGoTo(3);
        return;
    }

    var teams = {};
    match.players.forEach(function(p) {
        (teams[p.team_name] = teams[p.team_name] || []).push(p);
    });
    Object.keys(teams).forEach(function(teamName) {
        teams[teamName].forEach(function(p) {
            var div = document.createElement("div");
            div.className = "player-item" + (match.mvp_player_id === p.player_id ? " selected" : "");
            div.innerHTML =
                '<div class="pname">' + p.player_name + "</div>" +
                '<div class="ptag">' + teamName + " · " + p.fantasy_points + " pts</div>";
            div.addEventListener("click", function() { pickPlayer(p, div); });
            grid.appendChild(div);
        });
    });

    if (match.mvp_player_id) {
        var existing = match.players.find(function(p) { return p.player_id === match.mvp_player_id; });
        if (existing) {
            _selectedPlayer = existing;
            el("selected-player-name").textContent = existing.player_name;
            el("confirm-bar").classList.add("visible");
        }
    }
    mvpGoTo(3);
}

function pickPlayer(player, div) {
    _selectedPlayer = player;
    document.querySelectorAll(".player-item").forEach(function(d) { d.classList.remove("selected"); });
    div.classList.add("selected");
    el("selected-player-name").textContent = player.player_name;
    el("confirm-bar").classList.add("visible");
}

// ── Confirm ─────────────────────────────────────────────────────────────────

function confirmMVP() {
    if (!_selectedMatch || !_selectedPlayer) return;
    el("btn-confirm-mvp").disabled = true;
    ebsPost("/twitch/mvp", {
        match_id:  _selectedMatch.match_id,
        player_id: _selectedPlayer.player_id,
    }).then(function(data) {
        if (!data.player_id) {
            showBanner(el("banner"), data.detail || "Error setting MVP", true);
            return;
        }
        _selectedMatch.mvp_player_id   = data.player_id;
        _selectedMatch.mvp_player_name = data.player_name;

        var drop = data.token_drop || {};
        var dropMsg = "";
        if (drop.already_dropped) {
            dropMsg = " (tokens already dropped for this match)";
        } else if (drop.winners && drop.winners.length > 0) {
            var shown = drop.winners.slice(0, 5).join(", ");
            var extra = drop.winners.length > 5 ? " +" + (drop.winners.length - 5) + " more" : "";
            dropMsg = " · Tokens → " + shown + extra;
        } else if (drop.pool_size === 0) {
            dropMsg = " · No viewers in pool";
        }

        showBanner(el("banner"), "MVP: " + data.player_name + dropMsg, false);
        mvpGoTo(0);
    }).catch(function() {
        showBanner(el("banner"), "Request failed", true);
    }).finally(function() {
        el("btn-confirm-mvp").disabled = false;
    });
}

function onPubSub() {}

init();
