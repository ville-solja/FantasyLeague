"use strict";

var _seriesData     = [];
var _selectedSeries = null;
var _selectedMatch  = null;
var _selectedPlayer = null;

// Issue #234: the viewer vote this tool started or found open (GET /twitch/mvp-poll shape).
var POLL_REFRESH_MS = 5000;
var _poll           = null;
var _pollPick       = null;   // player chosen in the result view
var _pollOffset     = 0;      // server clock minus local clock, in seconds
var _pollTimer      = null;   // vote count refresh while open
var _pollTick       = null;   // countdown

// ── Navigation ──────────────────────────────────────────────────────────────

function mvpGoTo(step) {
    [0, 1, 2, 3, 4].forEach(function(n) {
        el("mvp-step-" + n).classList.toggle("active", n === step);
    });
    if (step === 0) { _selectedSeries = null; _selectedMatch = null; _selectedPlayer = null; }
}

// ── Init ────────────────────────────────────────────────────────────────────

el("btn-start-mvp").addEventListener("click", function() {
    // A vote left with Back is still running: go back to it.
    if (_poll) { showPoll(_poll); refreshPoll(); } else { loadSeries(); }
});
el("btn-refresh-series").addEventListener("click", loadSeries);
el("btn-confirm-mvp").addEventListener("click", confirmMVP);

el("btn-back-0").addEventListener("click", function() { mvpGoTo(0); });
el("btn-back-1").addEventListener("click", function() { mvpGoTo(1); });
el("btn-back-2").addEventListener("click", function() { mvpGoTo(2); });
el("btn-back-4").addEventListener("click", function() { stopPollTimers(); mvpGoTo(0); });

el("btn-mode-pick").addEventListener("click", function() { showMatchMode("pick"); });
el("btn-mode-vote").addEventListener("click", function() { showMatchMode("vote"); });
el("btn-open-vote").addEventListener("click", startViewerVote);
el("btn-poll-end").addEventListener("click", endViewerVote);
el("btn-poll-cancel").addEventListener("click", cancelViewerVote);
el("btn-poll-confirm").addEventListener("click", confirmPollMVP);

function onReady() {
    el("mvp-unavailable").hidden = true;
    resumePoll();
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
    showMatchMode("pick");

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

        var dropMsg = dropNote(data.token_drop || {});

        var bonusMsg = _selectedMatch.provisional ? " · Fantasy bonus is applied when the stats arrive" : "";
        showBanner(el("banner"), "MVP: " + data.player_name + dropMsg + bonusMsg, false);
        mvpGoTo(0);
    }).catch(function() {
        showBanner(el("banner"), "Request failed" + failReasonSuffix(), true);
    }).finally(function() {
        el("btn-confirm-mvp").disabled = false;
    });
}

function dropNote(drop) {
    if (drop.already_dropped) return " (tokens already dropped for this match)";
    if (drop.enabled === false) return " · Token drops are off";
    // Winner count only (issue #157): no viewer names in the dashboard either.
    if (drop.winner_count > 0) return " · " + drop.winner_count + (drop.winner_count === 1 ? " viewer" : " viewers") + " received a token";
    if (drop.pool_size === 0) return " · No joined viewers in the pool";
    return "";
}

function errorDetail(data, fallback) {
    return data && typeof data.detail === "string" && data.detail ? data.detail : fallback;
}

// ── Viewer vote (issue #234) ────────────────────────────────────────────────

// The match view's two modes: Pick MVP (the player grid) or Start viewer vote.
function showMatchMode(mode) {
    el("pick-section").hidden = mode !== "pick";
    el("vote-section").hidden = mode !== "vote";
    el("btn-mode-pick").classList.toggle("selected", mode === "pick");
    el("btn-mode-vote").classList.toggle("selected", mode === "vote");
}

function startViewerVote() {
    if (!_selectedMatch) return;
    var btn = el("btn-open-vote");
    btn.disabled = true;
    ebsPost("/twitch/mvp-poll", {
        match_id: _selectedMatch.match_id,
        duration_seconds: Number(el("poll-duration").value) || 120,
    }).then(function(data) {
        if (!data || data._status || !data.poll_id) {
            showBanner(el("banner"), errorDetail(data, "Could not start the vote"), true);
            return;
        }
        showPoll(data);
    }).catch(function() {
        showBanner(el("banner"), "Request failed" + failReasonSuffix(), true);
    }).finally(function() {
        btn.disabled = false;
    });
}

// A vote that is open, or closed and waiting for confirmation, comes back after a reload.
function resumePoll() {
    ebsGet("/twitch/mvp-poll").then(function(data) {
        var poll = data && data.poll;
        if (poll && (poll.status === "open" || poll.status === "closed")) showPoll(poll);
    }).catch(function() {});
}

function showPoll(poll) {
    _poll = poll;
    _pollPick = null;
    _pollOffset = poll.now ? poll.now - Date.now() / 1000 : 0;
    stopPollTimers();
    mvpGoTo(4);
    renderPoll();
    if (_poll && _poll.status === "open") {
        _pollTimer = setInterval(refreshPoll, POLL_REFRESH_MS);
        _pollTick = setInterval(renderCountdown, 1000);
    }
}

function stopPollTimers() {
    if (_pollTimer) clearInterval(_pollTimer);
    if (_pollTick) clearInterval(_pollTick);
    _pollTimer = null;
    _pollTick = null;
}

function refreshPoll() {
    if (!_poll) return;
    var pollId = _poll.poll_id;
    ebsGet("/twitch/mvp-poll").then(function(data) {
        if (!data || data._status || !_poll || _poll.poll_id !== pollId) return;
        var poll = data.poll;
        if (!poll || poll.poll_id !== pollId) {
            stopPollTimers();
            _poll = null;
            mvpGoTo(0);
            return;
        }
        var wasOpen = _poll.status === "open";
        _poll = poll;
        if (poll.status !== "open") stopPollTimers();
        if (wasOpen || poll.status === "open") renderPoll();
    }).catch(function() {});
}

function pollSecondsLeft(poll, nowSec) {
    return Math.max(0, Math.ceil(poll.closes_at - nowSec));
}

function countdownText(seconds) {
    var s = seconds % 60;
    return Math.floor(seconds / 60) + ":" + (s < 10 ? "0" : "") + s + " left";
}

function voteCountText(n) {
    n = Number(n || 0);
    return n + (n === 1 ? " vote" : " votes");
}

function renderCountdown() {
    if (!_poll || _poll.status !== "open") return;
    var left = pollSecondsLeft(_poll, Date.now() / 1000 + _pollOffset);
    el("poll-countdown").textContent = countdownText(left);
    // The backend closes the vote on the first read after closes_at.
    if (left === 0) refreshPoll();
}

function renderPoll() {
    var p = _poll;
    el("poll-title").textContent = "Viewer vote · Match " + p.match_number + " · " +
        p.team1_name + " vs " + p.team2_name;
    var open = p.status === "open";
    el("poll-open").hidden = !open;
    el("poll-result").hidden = open;
    if (open) {
        renderCountdown();
        el("poll-votes").textContent = voteCountText(p.total_votes);
        return;
    }
    renderPollResult();
}

// What the result view preselects: the sole winner, nobody on a tie (the tied players
// are marked), and with no votes the streamer picks instead.
function pollResultState(poll) {
    if (!poll || !poll.total_votes) return { kind: "none", preselect: null, tied: [] };
    if (poll.winner_player_id) return { kind: "winner", preselect: poll.winner_player_id, tied: [] };
    return { kind: "tie", preselect: null, tied: (poll.tied_player_ids || []).slice() };
}

function renderPollResult() {
    var p = _poll;
    var state = pollResultState(p);
    var list = el("poll-result-list");
    var note = el("poll-result-note");
    list.innerHTML = "";
    el("poll-confirm-bar").classList.remove("visible");
    el("poll-chat-preview").hidden = true;
    if (state.kind === "none") {
        note.textContent = "No votes were cast. Pick the MVP yourself.";
        pickAfterNoVotes();
        return;
    }
    var results = p.results || [];
    var byId = {};
    results.forEach(function(r) { byId[r.player_id] = r; });
    if (state.kind === "winner") {
        var w = byId[state.preselect] || {};
        note.textContent = "Viewers chose " + (w.player_name || "") + " (" + w.pct + "% of " + voteCountText(p.total_votes) + ").";
    } else {
        note.textContent = "Tie between " + state.tied.map(function(id) { return (byId[id] || {}).player_name; }).join(", ") + ": pick one.";
    }
    results.forEach(function(r) {
        var div = document.createElement("div");
        div.className = "player-item" + (state.tied.indexOf(r.player_id) >= 0 ? " tied" : "");
        div.innerHTML =
            '<div class="pname">' + _escHtml(r.player_name) + "</div>" +
            '<div class="pvotes">' + voteCountText(r.votes) + " · " + r.pct + "%</div>";
        div.addEventListener("click", function() { pickPollPlayer(r, div); });
        list.appendChild(div);
        if (r.player_id === state.preselect) pickPollPlayer(r, div);
    });
}

function pickPollPlayer(result, div) {
    _pollPick = result;
    Array.prototype.forEach.call(el("poll-result-list").children || [], function(d) { d.classList.remove("selected"); });
    div.classList.add("selected");
    el("poll-selected-name").textContent = result.player_name;
    var name = result.chat_name || result.player_name;
    var preview = el("poll-chat-preview");
    preview.textContent = result.player_id === _poll.winner_player_id
        ? 'Chat will say: "Match MVP by viewer vote: ' + name + " (" + result.pct + "% of " + voteCountText(_poll.total_votes) + ')!"'
        : 'Chat will say: "Match MVP: ' + name + '!"';
    preview.hidden = false;
    el("poll-confirm-bar").classList.add("visible");
}

// No votes: say so and open Pick MVP, on the same match when it is still selected.
function pickAfterNoVotes() {
    var pollMatch = _poll && _poll.match_id;
    stopPollTimers();
    _poll = null;
    showBanner(el("banner"), "No votes were cast. Pick the MVP yourself.", false);
    if (_selectedMatch && _selectedMatch.match_id === pollMatch) {
        selectMatch(_selectedMatch);
    } else {
        loadSeries();
    }
}

function endViewerVote() {
    if (!_poll) return;
    var btn = el("btn-poll-end");
    btn.disabled = true;
    ebsPost("/twitch/mvp-poll/" + _poll.poll_id + "/end").then(function(data) {
        if (!data || data._status || !data.poll_id) {
            showBanner(el("banner"), errorDetail(data, "Could not end the vote"), true);
            refreshPoll();
            return;
        }
        showPoll(data);
    }).catch(function() {
        showBanner(el("banner"), "Request failed" + failReasonSuffix(), true);
    }).finally(function() {
        btn.disabled = false;
    });
}

function cancelViewerVote() {
    if (!_poll) return;
    var btn = el("btn-poll-cancel");
    btn.disabled = true;
    ebsPost("/twitch/mvp-poll/" + _poll.poll_id + "/cancel").then(function(data) {
        if (!data || data._status) {
            showBanner(el("banner"), errorDetail(data, "Could not cancel the vote"), true);
            return;
        }
        stopPollTimers();
        _poll = null;
        showBanner(el("banner"), "Vote cancelled. No MVP was set.", false);
        mvpGoTo(0);
    }).catch(function() {
        showBanner(el("banner"), "Request failed" + failReasonSuffix(), true);
    }).finally(function() {
        btn.disabled = false;
    });
}

function confirmPollMVP() {
    if (!_poll || !_pollPick) return;
    var btn = el("btn-poll-confirm");
    btn.disabled = true;
    ebsPost("/twitch/mvp", {
        match_id:  _poll.match_id,
        player_id: _pollPick.player_id,
        poll_id:   _poll.poll_id,
    }).then(function(data) {
        if (!data.player_id) {
            showBanner(el("banner"), errorDetail(data, "Error setting MVP"), true);
            return;
        }
        _poll = null;
        showBanner(el("banner"), "MVP: " + data.player_name + dropNote(data.token_drop || {}), false);
        mvpGoTo(0);
    }).catch(function() {
        showBanner(el("banner"), "Request failed" + failReasonSuffix(), true);
    }).finally(function() {
        btn.disabled = false;
    });
}

function onPubSub() {}

init();
