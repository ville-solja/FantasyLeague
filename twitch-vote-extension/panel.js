// Kana Cards MVP Vote (issue #253) — the viewer panel.
//
// Three states, all from GET /twitch/mvp-poll:
//   no vote    the channel's last MVP, and that the streamer starts the vote
//   open vote  both teams' players, a countdown and Vote
//   result     each player's votes once the vote has closed, and the confirmed MVP
//
// Voting needs only a Twitch login. After voting, the viewer may share their Twitch
// identity to enter the token drop; that step is optional and is hidden when the
// league has switched tokens off.

"use strict";

var POLL_REFRESH_MS = 15000;   // while a vote is open, as in the full extension (issue #251 review)
var IDLE_REFRESH_MS = 60000;   // otherwise (PubSub brings changes sooner)

var WAITING_TEXT = "The streamer starts the vote after the match";
var LOGIN_TEXT = "Log in to Twitch to vote.";
var SHARE_TITLE = "Share your Twitch identity to enter the token drop";
var SHARE_REASON = "Kana Cards uses it only to give a token to voters picked in the drop.";
var PENDING_WIN_TEXT = "You won a token. Claim it at kana-cards.com by signing in with Twitch.";

var state = {
    loaded: false,
    poll: null,          // GET /twitch/mvp-poll: the channel's vote, or null
    lastMvp: null,       // the channel's last MVP, when there is no vote
    pick: null,          // player chosen, before pressing Vote
    offset: 0,           // server clock minus local clock, in seconds
    error: "",
    unavailable: "",
    refreshTimer: null,
    refreshEvery: 0,
    tick: null,
    enteredWith: null,   // the token the vote was last re-sent with, to enter the drop
};

// ── Viewer ──────────────────────────────────────────────────────────────────

// Twitch gives a logged-in viewer an opaque id starting with U, a logged-out one A.
function viewerLoggedIn(opaqueId) {
    return String(opaqueId || "").charAt(0) === "U";
}

// True once the viewer accepted Twitch's identity share for this extension.
function viewerShared() {
    var viewer = window.Twitch && window.Twitch.ext && window.Twitch.ext.viewer;
    return !!(viewer && viewer.isLinked);
}

// ── Text helpers ────────────────────────────────────────────────────────────

function votesText(n) {
    n = Number(n || 0);
    return n + (n === 1 ? " vote" : " votes");
}

function secondsLeft(poll, nowSec) {
    return Math.max(0, Math.ceil(poll.closes_at - nowSec));
}

function countdownText(seconds) {
    var s = seconds % 60;
    return Math.floor(seconds / 60) + ":" + (s < 10 ? "0" : "") + s + " left";
}

function playerName(poll, id) {
    var name = "";
    (poll.teams || []).forEach(function (t) {
        (t.players || []).forEach(function (p) { if (p.player_id === id) name = p.player_name; });
    });
    return name;
}

// ── Rendering (pure: state in, markup out) ──────────────────────────────────

// No vote on the channel: the last MVP, if any, and what happens next.
function idleHtml(lastMvp) {
    var html = "";
    if (lastMvp && lastMvp.player_name) {
        html += '<div class="box last-mvp"><h3 class="eyebrow">Last MVP</h3>' +
            "<strong>" + _escHtml(lastMvp.player_name) + "</strong></div>";
    }
    return html + '<p class="note">' + WAITING_TEXT + ".</p>";
}

// The optional token step under a cast vote. Nothing when tokens are off.
function dropStepHtml(poll, shared) {
    var drop = poll.token_drop || {};
    if (!drop.enabled || !poll.my_vote) return "";
    if (drop.entered) {
        return '<div class="box drop-step"><p>You are in the token drop for this vote.</p></div>';
    }
    if (shared) return "";   // the vote is re-sent with the shared identity
    return '<div class="box drop-step"><p class="drop-title">' + SHARE_TITLE + "</p>" +
        '<p class="note">' + SHARE_REASON + " Your vote counts either way.</p>" +
        '<button type="button" class="secondary" id="btn-share">Share identity</button></div>';
}

function openHtml(poll, view) {
    var pick = view.pick || poll.my_vote;
    var left = secondsLeft(poll, view.nowSec);
    var html = '<p class="poll-match">' + _escHtml(poll.team1_name) + " vs " + _escHtml(poll.team2_name) +
        " · game " + Number(poll.match_number) + "</p>" +
        '<p class="note" id="poll-countdown" role="status">' +
        _escHtml(countdownText(left) + " · " + votesText(poll.total_votes)) + "</p>";
    (poll.teams || []).forEach(function (t) {
        html += '<div class="poll-team">' + _escHtml(t.team_name) + "</div>";
        (t.players || []).forEach(function (p) {
            if (view.loggedIn) {
                html += '<button type="button" class="poll-player" data-player="' + Number(p.player_id) + '"' +
                    ' aria-pressed="' + (pick === p.player_id ? "true" : "false") + '">' +
                    _escHtml(p.player_name) + "</button>";
            } else {
                html += '<div class="poll-player">' + _escHtml(p.player_name) + "</div>";
            }
        });
    });
    if (!view.loggedIn) {
        return html + '<p class="note">' + LOGIN_TEXT + "</p>";
    }
    html += '<button type="button" class="poll-vote" id="btn-vote"' + (pick ? "" : " disabled") + ">" +
        (poll.my_vote ? "Change vote" : "Vote") + "</button>";
    if (poll.my_vote) {
        html += '<p class="note">You voted for ' + _escHtml(playerName(poll, poll.my_vote)) +
            ". You can change it until the vote closes.</p>";
    }
    html += '<p class="note err" id="poll-error" role="status">' + _escHtml(view.error || "") + "</p>";
    return html + dropStepHtml(poll, view.shared);
}

function resultHtml(poll) {
    var confirmed = poll.confirmed_player_id;
    var html = '<p class="poll-match">' + _escHtml(poll.team1_name) + " vs " + _escHtml(poll.team2_name) +
        " · game " + Number(poll.match_number) + "</p>";
    if (confirmed) {
        html += '<div class="box last-mvp"><h3 class="eyebrow">Match MVP</h3><strong>' +
            _escHtml(playerName(poll, confirmed)) + "</strong></div>";
    } else {
        html += '<p class="note">The vote has closed with ' + _escHtml(votesText(poll.total_votes)) +
            ". The streamer confirms the MVP.</p>";
    }
    (poll.results || []).forEach(function (r) {
        var cls = "poll-player" + (r.player_id === poll.my_vote ? " mine" : "") +
            (r.player_id === confirmed ? " mvp" : "");
        html += '<div class="' + cls + '"><span>' + _escHtml(r.player_name) + "</span>" +
            '<span class="share">' + _escHtml(votesText(r.votes) + " · " + Number(r.pct) + "%") + "</span></div>";
    });
    if (poll.token_drop && poll.token_drop.pending_win) {
        html += '<div class="box drop-won" role="status">' + PENDING_WIN_TEXT + "</div>";
    }
    return html;
}

function panelHtml(data, view) {
    if (view.unavailable) return '<p class="note">' + _escHtml(view.unavailable) + "</p>";
    if (!view.loaded) return '<p class="note">Loading…</p>';
    var poll = data.poll;
    if (!poll) return idleHtml(data.last_mvp);
    return poll.status === "open" ? openHtml(poll, view) : resultHtml(poll);
}

function render() {
    var box = el("vote-panel");
    box.innerHTML = panelHtml({ poll: state.poll, last_mvp: state.lastMvp }, {
        loaded: state.loaded,
        unavailable: state.unavailable,
        loggedIn: viewerLoggedIn(ext.userId),
        shared: viewerShared(),
        pick: state.pick,
        error: state.error,
        nowSec: Date.now() / 1000 + state.offset,
    });
    Array.prototype.forEach.call(box.querySelectorAll("button.poll-player"), function (btn) {
        btn.addEventListener("click", function () {
            state.pick = Number(btn.getAttribute("data-player"));
            state.error = "";
            render();
        });
    });
    var voteBtn = el("btn-vote");
    if (voteBtn) voteBtn.addEventListener("click", castVote);
    var shareBtn = el("btn-share");
    if (shareBtn) shareBtn.addEventListener("click", shareIdentity);
}

function renderCountdown() {
    var p = state.poll;
    var line = el("poll-countdown");
    if (!p || p.status !== "open" || !line) return;
    var now = Date.now() / 1000 + state.offset;
    line.textContent = countdownText(secondsLeft(p, now)) + " · " + votesText(p.total_votes);
    // The backend closes the vote on the first read after closes_at.
    if (p.closes_at <= now) loadPoll();
}

// ── Data ────────────────────────────────────────────────────────────────────

function setRefresh(ms) {
    if (state.refreshEvery === ms) return;
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    state.refreshEvery = ms;
    state.refreshTimer = setInterval(loadPoll, ms);
}

function setPoll(data) {
    var poll = (data && data.poll) || null;
    var prevId = state.poll && state.poll.poll_id;
    state.loaded = true;
    state.poll = poll;
    state.lastMvp = (data && data.last_mvp) || null;
    if (!poll || poll.poll_id !== prevId) { state.pick = null; state.error = ""; }
    if (poll && poll.now) state.offset = poll.now - Date.now() / 1000;
    var open = !!(poll && poll.status === "open");
    setRefresh(open ? POLL_REFRESH_MS : IDLE_REFRESH_MS);
    if (open && !state.tick) {
        state.tick = setInterval(renderCountdown, 1000);
    } else if (!open && state.tick) {
        clearInterval(state.tick);
        state.tick = null;
    }
    render();
    enterDropIfShared();
}

function loadPoll() {
    return ebsGet("/twitch/mvp-poll").then(function (data) {
        if (!data || data._status) {
            if (!state.loaded) {
                state.unavailable = "MVP voting is not available on this channel right now." + failReasonSuffix();
                render();
            }
            return;
        }
        state.unavailable = "";
        setPoll(data);
    }).catch(function () {
        if (!state.loaded) {
            state.unavailable = "MVP voting is not available on this channel right now." + failReasonSuffix();
            render();
        }
    });
}

var VOTE_ERRORS = {
    poll_closed: "The vote has closed.",
    twitch_login_required: LOGIN_TEXT,
};

function sendVote(playerId) {
    var p = state.poll;
    return ebsPost("/twitch/mvp-poll/" + encodeURIComponent(p.poll_id) + "/vote", { player_id: playerId });
}

function castVote() {
    var p = state.poll;
    var pick = state.pick || (p && p.my_vote);
    if (!p || p.status !== "open" || !pick) return;
    var btn = el("btn-vote");
    if (btn) btn.disabled = true;
    state.enteredWith = ext.token;
    sendVote(pick).then(function (data) {
        if (data && !data._status && data.poll_id === p.poll_id) {
            state.pick = null;
            state.error = "";
        } else {
            var detail = data && typeof data.detail === "string" ? data.detail : "";
            state.error = VOTE_ERRORS[detail] || "Your vote was not saved. Try again.";
        }
        return loadPoll();
    }).catch(function () {
        state.error = "Your vote was not saved. Try again." + failReasonSuffix();
        render();
    });
}

// The optional token step. Twitch asks the viewer; on acceptance it calls
// onAuthorized again with a token that carries the identity, and onReady re-sends
// the vote so it enters the drop (enterDropIfShared).
function shareIdentity() {
    var actions = window.Twitch && window.Twitch.ext && window.Twitch.ext.actions;
    if (actions && typeof actions.requestIdShare === "function") actions.requestIdShare();
}

// A cast vote that is not in the drop yet, from a viewer who has shared their
// identity: send the same vote once more with the current token.
function enterDropIfShared() {
    var p = state.poll;
    var drop = p && p.token_drop;
    if (!p || p.status !== "open" || !p.my_vote || !drop || !drop.enabled || drop.entered) return;
    if (!viewerShared() || state.enteredWith === ext.token) return;
    state.enteredWith = ext.token;
    sendVote(p.my_vote).then(function (data) {
        if (data && !data._status) loadPoll();
    }).catch(function () {});
}

// ── Twitch hooks (extension.js) ─────────────────────────────────────────────

function onReady() {
    loadPoll();
}

function onConfigTimeout() {
    state.unavailable = "MVP voting is not available on this channel right now." + failReasonSuffix();
    render();
}

// mvp_poll (opened, closed, cancelled) and mvp (confirmed): re-read the vote.
function onPubSub(msg) {
    if (msg && (msg.type === "mvp_poll" || msg.type === "mvp")) loadPoll();
}

init();
