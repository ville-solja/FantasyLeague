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
el("btn-refresh-series").addEventListener("click", loadSeries);
el("btn-confirm-mvp").addEventListener("click", confirmMVP);

el("btn-back-0").addEventListener("click", function() { mvpGoTo(0); });
el("btn-back-1").addEventListener("click", function() { mvpGoTo(1); });
el("btn-back-2").addEventListener("click", function() { mvpGoTo(2); });

function onReady() {
    el("mvp-unavailable").hidden = true;
}

// Issue #180: no usable backend URL (E-ORIGIN at once, E-CONFIG after 8 seconds).
function onConfigTimeout() {
    var note = el("mvp-unavailable");
    note.textContent = "MVP selection is not available on this channel right now." + failReasonSuffix();
    note.hidden = false;
}

// ── Step 1: load series ─────────────────────────────────────────────────────

// A live check older than this (or none, or no live source) shows the warning line.
var _LIVE_STALE_SECONDS = 5 * 60;

function liveFreshness(data, nowSec) {
    var checked = data && data.live_checked_at;
    if (!data || !data.live_source_configured || !checked || nowSec - checked > _LIVE_STALE_SECONDS) {
        return { text: "Live games not checked recently — your match will appear once its stats are in", warn: true };
    }
    var age = Math.max(0, nowSec - checked);
    var ago = age < 60 ? age + " s ago" : Math.floor(age / 60) + " min ago";
    return { text: "Live games checked " + ago, warn: false };
}

function renderFreshness(data) {
    var line = el("live-freshness");
    if (!data) {
        line.textContent = "";
        line.classList.remove("warn");
        return;
    }
    var f = liveFreshness(data, Math.floor(Date.now() / 1000));
    line.textContent = f.text;
    line.classList.toggle("warn", f.warn);
}

function approvalMessage(approval) {
    if (approval === "rejected") return "This channel isn't approved to set match MVPs.";
    return "This channel is waiting for the league's approval to set match MVPs.";
}

function loadSeries() {
    el("series-list").innerHTML = '<p class="muted">Loading…</p>';
    mvpGoTo(1);
    var refreshBtn = el("btn-refresh-series");
    refreshBtn.disabled = true;
    ebsGet("/twitch/matches/current").then(function(data) {
        var container = el("series-list");
        if (data && data._status && data.mvp_allowed === undefined) {
            renderFreshness(null);
            _seriesData = [];
            container.innerHTML = '<p class="muted">' + _escHtml("Failed to load matches." + failReasonSuffix()) + "</p>";
            return;
        }
        // Issue #175: a channel the league hasn't approved can't set MVPs yet.
        if (data && data.mvp_allowed === false) {
            renderFreshness(null);
            _seriesData = [];
            container.innerHTML = '<p class="muted">' + approvalMessage(data.approval) + "</p>";
            return;
        }
        renderFreshness(data || {});
        _seriesData = (data && data.series) || [];
        if (_seriesData.length === 0) {
            container.innerHTML = '<p class="muted">No recent matches found. A match appears here as soon as it goes live.</p>';
            return;
        }
        container.innerHTML = "";
        _seriesData.forEach(function(series, idx) {
            var div = document.createElement("div");
            div.className = "series-item";
            var matchCount = series.matches.length;
            var mvpCount   = series.matches.filter(function(m) { return m.mvp_player_id; }).length;
            div.innerHTML =
                '<div class="versus">' + _escHtml(series.team1_name) + " vs " + _escHtml(series.team2_name) + "</div>" +
                '<div class="meta">' + matchCount + " match" + (matchCount !== 1 ? "es" : "") +
                (mvpCount > 0 ? " · " + mvpCount + " MVP set" : "") + "</div>";
            div.addEventListener("click", function() { selectSeries(idx); });
            container.appendChild(div);
        });
    }).catch(function() {
        renderFreshness(null);
        el("series-list").innerHTML = '<p class="muted">' + _escHtml("Failed to load matches." + failReasonSuffix()) + "</p>";
    }).finally(function() {
        refreshBtn.disabled = false;
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
        var mvpNote = match.mvp_player_name ? " · MVP: " + _escHtml(match.mvp_player_name) : "";
        var statusNote = match.provisional ? " · " + (match.live ? "Live" : "Stats pending") : "";
        div.innerHTML =
            '<div style="font-weight:600">Match ' + match.match_number + "</div>" +
            '<div class="meta">' + date + statusNote + mvpNote + "</div>";
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
    el("chat-preview").hidden = true;

    var grid = el("player-grid");
    grid.innerHTML = "";

    if (!match.players || match.players.length === 0) {
        grid.innerHTML = '<p class="muted" style="grid-column:span 2">No players found for this match yet.</p>';
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
            // Provisional matches have no stats yet, so no points to show.
            var ptag = match.provisional
                ? _escHtml(teamName)
                : _escHtml(teamName) + " · " + p.fantasy_points + " pts";
            div.innerHTML =
                '<div class="pname">' + _escHtml(p.player_name) + "</div>" +
                '<div class="ptag">' + ptag + "</div>";
            div.addEventListener("click", function() { pickPlayer(p, div); });
            grid.appendChild(div);
        });
    });

    if (match.mvp_player_id) {
        var existing = match.players.find(function(p) { return p.player_id === match.mvp_player_id; });
        if (existing) {
            _selectedPlayer = existing;
            el("selected-player-name").textContent = existing.player_name;
            showChatPreview(existing);
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
    showChatPreview(player);
    el("confirm-bar").classList.add("visible");
}

// Shows the exact text the chat announcement will start with (issue #166). The
// backend cleans player-chosen names before they reach chat; chat_name is that name.
function showChatPreview(player) {
    var preview = el("chat-preview");
    preview.textContent = 'Chat will say: "Match MVP: ' + (player.chat_name || player.player_name) + '!"';
    preview.hidden = false;
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
        } else if (drop.enabled === false) {
            dropMsg = " · Token drops are off";
        } else if (drop.winner_count > 0) {
            // Winner count only (issue #157): no viewer names in the dashboard either.
            dropMsg = " · " + drop.winner_count + (drop.winner_count === 1 ? " viewer" : " viewers") + " received a token";
        } else if (drop.pool_size === 0) {
            dropMsg = " · No joined viewers in the pool";
        }

        var bonusMsg = _selectedMatch.provisional ? " · Fantasy bonus is applied when the stats arrive" : "";
        showBanner(el("banner"), "MVP: " + data.player_name + dropMsg + bonusMsg, false);
        mvpGoTo(0);
    }).catch(function() {
        showBanner(el("banner"), "Request failed" + failReasonSuffix(), true);
    }).finally(function() {
        el("btn-confirm-mvp").disabled = false;
    });
}

function onPubSub() {}

init();
