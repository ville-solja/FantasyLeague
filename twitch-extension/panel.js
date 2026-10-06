"use strict";

// Kana Cards viewer panel (issue #157): a self-contained game on Twitch.
// Live tab for every viewer; Join creates a soft account from the Twitch login;
// Cards (draw, team draw, collection) and Roster (slot-first bench picker) run
// on the EBS. All data is escaped with _escHtml before it reaches innerHTML.

var LIVE_REFRESH_MS = 60000;
var HEARTBEAT_MS    = 55000;
var RARITY_ORDER    = ["legendary", "epic", "rare", "common"];
var RARITY_SHORT    = { legendary: "Leg", epic: "Epic", rare: "Rare", common: "Com" };

var state = {
    me: null,               // GET /twitch/me when joined, else null
    meLoaded: false,
    meError: false,
    view: "live",
    tab: "live",
    liveTimer: null,
    heartbeatOn: false,
    collFilter: "all",
    teams: [],
    teamCost: 3,
    selectedTeam: null,
    pickerSlot: 0,
    pickerFilter: "all",
    pickerSort: "points",
    leaveArmed: false,
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function isLoggedInToTwitch() {
    return typeof ext.userId === "string" && ext.userId.charAt(0) === "U";
}

function isJoined() { return !!(state.me && state.me.joined); }

function fmtPts(v) {
    var n = Number(v || 0);
    return n.toFixed(1);
}

function initials(name) {
    return String(name || "?").replace(/\s+/g, "").slice(0, 4).toUpperCase();
}

function rarityClass(r) {
    return RARITY_ORDER.indexOf(r) >= 0 ? r : "common";
}

function artHtml(card, size) {
    var r = rarityClass(card.card_type);
    return '<span class="art ' + size + " " + r + '" aria-hidden="true">' + _escHtml(initials(card.player_name)) + "</span>";
}

function showToast(text) {
    var t = el("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () { t.hidden = true; }, 5000);
}

function errorText(data, fallback) {
    if (data && typeof data.detail === "string" && data.detail) return data.detail;
    return fallback;
}

// ── Views and tabs ──────────────────────────────────────────────────────────

var VIEWS = ["live", "cards", "teams", "roster", "picker", "settings"];
var VIEW_TAB = { live: "live", cards: "cards", teams: "cards", roster: "roster", picker: "roster", settings: null };

function showView(name) {
    state.view = name;
    VIEWS.forEach(function (v) { el("view-" + v).hidden = v !== name; });
    var tab = VIEW_TAB[name];
    if (tab) state.tab = tab;
    ["live", "cards", "roster"].forEach(function (t) {
        el("tab-" + t).setAttribute("aria-selected", tab === t ? "true" : "false");
    });
    if (name !== "settings") disarmLeave();
}

Array.prototype.forEach.call(document.querySelectorAll(".p-tab"), function (btn) {
    btn.addEventListener("click", function () { showView(btn.getAttribute("data-view")); });
});
el("btn-settings").addEventListener("click", function () { renderSettings(); showView("settings"); });
el("btn-settings-back").addEventListener("click", function () { showView(state.tab); });
el("btn-teams-back").addEventListener("click", function () { showView("cards"); });
el("btn-picker-back").addEventListener("click", function () { showView("roster"); });

// ── Ready / config ──────────────────────────────────────────────────────────

function onReady() {
    // onReady also fires on every Twitch token refresh: start the timers once.
    if (!state.liveTimer) {
        loadLive();
        state.liveTimer = setInterval(loadLive, LIVE_REFRESH_MS);
    }
    loadMe();
}

function onConfigTimeout() {
    ["live-mvps", "live-top", "live-next"].forEach(function (id) {
        el(id).innerHTML = '<p class="note">Kana Cards is not available on this channel right now.</p>';
    });
}

// ── Live tab ────────────────────────────────────────────────────────────────

function loadLive() {
    ebsGet("/twitch/matches/current").then(function (data) {
        if (!data || data._status) { renderMvpsUnavailable(); return; }
        renderMvps(data.series || []);
    }).catch(renderMvpsUnavailable);
    ebsGet("/twitch/panel").then(function (data) {
        if (!data || data._status) { renderPanelUnavailable(); return; }
        renderTopPerformers(data.top_performers || []);
        renderNextMatch(data.next_match);
    }).catch(renderPanelUnavailable);
}

function renderMvpsUnavailable() {
    el("live-mvps").innerHTML = '<p class="note">Live results are unavailable right now.</p>';
}

function renderPanelUnavailable() {
    el("live-top").innerHTML = '<p class="note">Top performers are unavailable right now.</p>';
    el("live-next").innerHTML = '<p class="note">The schedule is unavailable right now.</p>';
}

function renderMvps(series) {
    var rows = [];
    series.slice(0, 3).forEach(function (s) {
        var games = (s.matches || []).map(function (m) {
            var label = "G" + m.match_number;
            if (m.mvp_player_name) return label + " MVP " + _escHtml(m.mvp_player_name) + (m.live ? ' <span class="live-mark">(live)</span>' : "");
            if (m.live) return label + ' <span class="live-mark">(live)</span>';
            return label + " no MVP yet";
        });
        rows.push('<li class="row"><div class="grow"><div class="title">' + _escHtml(s.team1_name) + " vs " +
            _escHtml(s.team2_name) + '</div><div class="sub">' + games.join(" · ") + "</div></div></li>");
    });
    el("live-mvps").innerHTML = rows.length
        ? '<ul class="row-list">' + rows.join("") + "</ul>"
        : '<p class="note">No recent games yet.</p>';
}

function renderTopPerformers(top) {
    el("live-top").innerHTML = top.length
        ? '<ul class="row-list">' + top.map(function (p, i) {
            return '<li class="row"><span class="pts" style="width:16px">' + (i + 1) + '</span><div class="grow"><div class="title">' +
                _escHtml(p.player_name) + '</div></div><span class="pts">' + fmtPts(p.fantasy_points) + "</span></li>";
        }).join("") + "</ul>"
        : '<p class="note">No games scored yet.</p>';
}

function renderNextMatch(next) {
    if (!next) {
        el("live-next").innerHTML = '<p class="note">No match scheduled.</p>';
        return;
    }
    var when = "";
    var d = new Date(next.datetime_iso);
    if (!isNaN(d.getTime())) {
        when = d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    }
    el("live-next").innerHTML = '<div class="row"><div class="grow"><div class="title">' + _escHtml(next.team1) +
        " vs " + _escHtml(next.team2) + '</div><div class="sub">' + _escHtml(when) +
        (next.week_label ? " · " + _escHtml(next.week_label) : "") + "</div></div></div>";
}

// ── Account: me, join, heartbeat ────────────────────────────────────────────

function loadMe() {
    return ebsGet("/twitch/me").then(function (data) {
        state.meLoaded = true;
        state.meError = !!(data && data._status);
        state.me = data && data.joined ? data : null;
        if (isJoined()) {
            if (!state.heartbeatOn) { startHeartbeat(HEARTBEAT_MS); state.heartbeatOn = true; }
        } else if (state.heartbeatOn) {
            stopHeartbeat();
            state.heartbeatOn = false;
        }
        renderAll();
        return state.me;
    }).catch(function () {
        state.meLoaded = true;
        state.meError = true;
        renderAll();
        return null;
    });
}

function renderJoinSlots() {
    Array.prototype.forEach.call(document.querySelectorAll(".join-slot"), function (slot) {
        slot.innerHTML = "";
        if (isJoined() || !state.meLoaded) return;
        if (state.meError) {
            if (slot.closest("#view-live")) return;  // the Live sections carry their own notes
            slot.innerHTML = '<p class="note">Kana Cards is unavailable right now. Try again in a moment.</p>';
            return;
        }
        var tpl = el(isLoggedInToTwitch() ? "tpl-join" : "tpl-login");
        slot.appendChild(tpl.content.cloneNode(true));
        var btn = slot.querySelector(".btn-join");
        if (btn) btn.addEventListener("click", function () { doJoin(btn); });
    });
}

function requestIdentityShare() {
    try {
        var twitchExt = window.Twitch && window.Twitch.ext;
        if (twitchExt && twitchExt.actions && typeof twitchExt.actions.requestIdShare === "function" &&
            !(twitchExt.viewer && twitchExt.viewer.isLinked)) {
            twitchExt.actions.requestIdShare();
        }
    } catch (e) {
        console.warn("[panel] identity share request failed", e);
    }
}

function doJoin(btn) {
    // Twitch's own consent dialog; Join works whether the viewer agrees or not.
    requestIdentityShare();
    btn.disabled = true;
    var errEl = btn.parentNode.querySelector(".join-error");
    if (errEl) errEl.textContent = "";
    ebsPost("/twitch/join").then(function (data) {
        if (data && data.joined) {
            state.me = data;
            if (!state.heartbeatOn) { startHeartbeat(HEARTBEAT_MS); state.heartbeatOn = true; }
            renderAll();
            showToast(data.created ? "You joined Kana Cards with " + data.tokens + " tokens." : "Welcome back.");
            return;
        }
        var msg = data && data.detail === "twitch_login_required"
            ? "Log in to Twitch to join."
            : "Joining is unavailable right now. Try again in a moment.";
        if (errEl) errEl.textContent = msg;
    }).catch(function () {
        if (errEl) errEl.textContent = "Joining is unavailable right now. Try again in a moment.";
    }).finally(function () { btn.disabled = false; });
}

function renderAll() {
    var joined = isJoined();
    el("token-chip").hidden = !joined;
    el("btn-settings").hidden = !joined;
    if (joined) el("token-count").textContent = String(state.me.tokens);
    el("cards-main").hidden = !joined;
    el("roster-main").hidden = !joined;
    renderJoinSlots();
    if (!joined) {
        if (["teams", "picker", "settings"].indexOf(state.view) >= 0) showView(state.tab);
        return;
    }
    renderDrawButtons();
    renderCollection();
    renderRoster();
    if (state.view === "picker") renderPicker();
}

// ── Cards tab: draws, reveal, collection ────────────────────────────────────

function renderDrawButtons() {
    var tokens = state.me.tokens || 0;
    var cost = state.me.team_draw_cost || 3;
    el("btn-draw").disabled = tokens < 1;
    el("btn-team-draw").textContent = "Team draw · " + cost;
    el("draw-note").textContent = tokens < 1 ? "You need a token to draw. Tokens come from MVP drops and the weekly grant." : "";
}

el("btn-draw").addEventListener("click", function () {
    var btn = el("btn-draw");
    btn.disabled = true;
    ebsPost("/twitch/draw").then(function (card) {
        if (!card || card._status) {
            el("draw-note").textContent = errorText(card, "The draw failed. Try again in a moment.");
            return;
        }
        showReveal(card);
        return loadMe();
    }).catch(function () {
        el("draw-note").textContent = "The draw failed. Try again in a moment.";
    }).finally(function () { if (isJoined()) renderDrawButtons(); });
});

function showReveal(card) {
    var r = rarityClass(card.card_type);
    var where = card.is_active ? "Added to your roster" : "Added to your bench";
    var box = el("reveal");
    box.innerHTML = artHtml(card, "lg") +
        '<div><div class="rar ' + r + '">' + _escHtml(r) + '</div><div class="name">' + _escHtml(card.player_name) +
        '</div><div class="note" style="margin:2px 0">' + _escHtml(card.team_name || "") + '</div><div class="confirm">' +
        where + "</div></div>";
    box.hidden = false;
}

function rarityCounts(cards) {
    var counts = { all: cards.length, legendary: 0, epic: 0, rare: 0, common: 0 };
    cards.forEach(function (c) { counts[rarityClass(c.card_type)] += 1; });
    return counts;
}

function chipsHtml(counts, active) {
    var keys = ["all"].concat(RARITY_ORDER);
    return keys.map(function (k) {
        var label = k === "all" ? "All" : RARITY_SHORT[k];
        return '<button type="button" class="chip" data-filter="' + k + '" aria-pressed="' + (active === k) + '">' +
            label + " " + counts[k] + "</button>";
    }).join("");
}

function renderCollection() {
    var cards = state.me.collection || [];
    el("coll-count").textContent = cards.length + (cards.length === 1 ? " card" : " cards");
    var filters = el("coll-filters");
    filters.innerHTML = chipsHtml(rarityCounts(cards), state.collFilter);
    Array.prototype.forEach.call(filters.querySelectorAll(".chip"), function (chip) {
        chip.addEventListener("click", function () {
            state.collFilter = chip.getAttribute("data-filter");
            renderCollection();
        });
    });
    var shown = cards.filter(function (c) { return state.collFilter === "all" || rarityClass(c.card_type) === state.collFilter; });
    shown.sort(sortByRarityThenName);
    el("coll-grid").innerHTML = shown.map(function (c) {
        return '<div class="coll-card" title="' + _escHtml(c.player_name) + '">' + artHtml(c, "sm") +
            '<span class="cname">' + _escHtml(c.player_name) + "</span></div>";
    }).join("");
    el("coll-empty").hidden = cards.length > 0;
}

function sortByRarityThenName(a, b) {
    var ra = RARITY_ORDER.indexOf(rarityClass(a.card_type));
    var rb = RARITY_ORDER.indexOf(rarityClass(b.card_type));
    if (ra !== rb) return ra - rb;
    return String(a.player_name || "").localeCompare(String(b.player_name || ""));
}

// ── Team draw picker ────────────────────────────────────────────────────────

el("btn-team-draw").addEventListener("click", openTeamPicker);

function openTeamPicker() {
    state.selectedTeam = null;
    el("team-list").innerHTML = '<p class="note">Loading teams…</p>';
    showView("teams");
    renderTeamConfirm();
    ebsGet("/twitch/teams").then(function (data) {
        if (!data || data._status) {
            el("team-list").innerHTML = '<p class="note">Teams are unavailable right now.</p>';
            return;
        }
        state.teams = data.teams || [];
        state.teamCost = data.cost || 3;
        renderTeams();
    }).catch(function () {
        el("team-list").innerHTML = '<p class="note">Teams are unavailable right now.</p>';
    });
}

function sortTeams(teams) {
    return teams.slice().sort(function (a, b) {
        var ca = a.remaining === 0, cb = b.remaining === 0;
        if (ca !== cb) return ca ? 1 : -1;
        return String(a.team_name || "").localeCompare(String(b.team_name || ""));
    });
}

function monogram(name) {
    var span = document.createElement("span");
    span.className = "mono";
    span.setAttribute("aria-hidden", "true");
    span.textContent = String(name || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
    return span;
}

function renderTeams() {
    var list = el("team-list");
    list.innerHTML = "";
    if (!state.teams.length) {
        list.innerHTML = '<p class="note">No teams have played yet.</p>';
        return;
    }
    sortTeams(state.teams).forEach(function (t) {
        var complete = t.remaining === 0;
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "team-row";
        btn.disabled = complete;
        btn.setAttribute("aria-pressed", state.selectedTeam && state.selectedTeam.team_id === t.team_id ? "true" : "false");
        if (t.logo_url && /^https:\/\//.test(t.logo_url)) {
            var img = document.createElement("img");
            img.alt = "";
            img.src = t.logo_url;
            img.addEventListener("error", function () { img.replaceWith(monogram(t.team_name)); });
            btn.appendChild(img);
        } else {
            btn.appendChild(monogram(t.team_name));
        }
        var body = document.createElement("span");
        body.className = "tbody";
        body.innerHTML = '<span class="tname">' + _escHtml(t.team_name) + '</span><span class="tleft">' +
            (complete ? "Complete" : t.remaining + " left") + "</span>";
        btn.appendChild(body);
        btn.addEventListener("click", function () {
            state.selectedTeam = t;
            Array.prototype.forEach.call(list.querySelectorAll(".team-row"), function (b) { b.setAttribute("aria-pressed", "false"); });
            btn.setAttribute("aria-pressed", "true");
            renderTeamConfirm();
        });
        list.appendChild(btn);
    });
}

function renderTeamConfirm() {
    var cost = state.teamCost || 3;
    var tokens = isJoined() ? state.me.tokens || 0 : 0;
    var btn = el("btn-team-confirm");
    var t = state.selectedTeam;
    btn.textContent = t ? "Draw from " + t.team_name + " · " + cost : "Pick a team · " + cost;
    btn.disabled = !t || tokens < cost;
    el("team-note").textContent = tokens < cost ? "You need " + cost + " tokens for a team draw" : "";
}

el("btn-team-confirm").addEventListener("click", function () {
    var t = state.selectedTeam;
    if (!t) return;
    var btn = el("btn-team-confirm");
    btn.disabled = true;
    ebsPost("/twitch/draw/booster/" + encodeURIComponent(t.team_id)).then(function (card) {
        if (!card || card._status) {
            el("team-note").textContent = errorText(card, "The team draw failed. Try again in a moment.");
            renderTeamConfirm();
            return;
        }
        showReveal(card);
        showView("cards");
        return loadMe();
    }).catch(function () {
        el("team-note").textContent = "The team draw failed. Try again in a moment.";
        renderTeamConfirm();
    });
});

// ── Roster tab: slot first ──────────────────────────────────────────────────

function rosterSlots() {
    var limit = state.me.roster_limit || 5;
    var slots = new Array(limit).fill(null);
    var unplaced = [];
    (state.me.roster.active || []).forEach(function (c) {
        var i = c.slot_index;
        if (typeof i === "number" && i >= 0 && i < limit && !slots[i]) slots[i] = c;
        else unplaced.push(c);
    });
    unplaced.forEach(function (c) {
        var free = slots.indexOf(null);
        if (free >= 0) slots[free] = c;
    });
    return slots;
}

function lockText(week) {
    if (!week) return "";
    if (week.is_locked) return "Locked";
    var secs = week.start_time - Math.floor(Date.now() / 1000);
    if (secs <= 0) return "Locks now";
    var d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600), m = Math.floor((secs % 3600) / 60);
    return "Locks in " + (d > 0 ? d + "d " + h + "h" : h > 0 ? h + "h " + m + "m" : m + "m");
}

function renderRoster() {
    var me = state.me;
    var roster = me.roster || { active: [], bench: [] };
    var locked = !!me.roster_locked;
    el("roster-week").textContent = roster.week ? roster.week.label : "Roster";
    el("roster-lock").textContent = lockText(roster.week);
    el("roster-locked").hidden = !locked;
    el("roster-points").textContent = me.week_points
        ? me.week_points.label + " so far: " + fmtPts(me.week_points.points) + " pts"
        : "";
    var slots = rosterSlots();
    var list = el("roster-slots");
    list.innerHTML = slots.map(function (c, i) {
        var num = '<span class="num">' + (i + 1) + "</span>";
        if (!c) {
            return '<li class="slot">' + num + '<span class="empty">Empty slot</span>' +
                (locked ? "" : '<button type="button" class="secondary" data-slot="' + i + '">+ Add a card</button>') + "</li>";
        }
        return '<li class="slot">' + num + artHtml(c, "xs") + '<div class="grow" style="flex:1;min-width:0"><div class="title" style="font-family:var(--font-display);font-weight:700;font-size:15px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' +
            _escHtml(c.player_name) + '</div><div class="sub note" style="margin:0">' + _escHtml(c.team_name || "") + " · " + fmtPts(c.total_points) + " pts</div></div>" +
            (locked ? "" : '<button type="button" class="secondary" data-slot="' + i + '">Change</button>') + "</li>";
    }).join("");
    Array.prototype.forEach.call(list.querySelectorAll("button[data-slot]"), function (b) {
        b.addEventListener("click", function () { openPicker(Number(b.getAttribute("data-slot"))); });
    });
    var bench = roster.bench || [];
    el("bench-count").textContent = bench.length + (bench.length === 1 ? " card" : " cards") + " on the bench";
}

// ── Bench picker for one slot ───────────────────────────────────────────────

function openPicker(slot) {
    state.pickerSlot = slot;
    state.pickerFilter = "all";
    renderPicker();
    showView("picker");
}

function seasonPointsById() {
    var map = {};
    (state.me.collection || []).forEach(function (c) { map[c.id] = c.season_points || 0; });
    return map;
}

function renderPicker() {
    if (!isJoined()) return;
    var slot = state.pickerSlot;
    var current = rosterSlots()[slot];
    el("picker-title").textContent = current ? "Replace in slot " + (slot + 1) : "Pick a card for slot " + (slot + 1);
    el("picker-current").hidden = !current;
    if (current) el("picker-current-name").textContent = current.player_name;

    var pts = seasonPointsById();
    var bench = (state.me.roster.bench || []).map(function (c) {
        return { card: c, points: pts[c.id] || 0 };
    });
    var filters = el("picker-filters");
    filters.innerHTML = chipsHtml(rarityCounts(bench.map(function (b) { return b.card; })), state.pickerFilter);
    Array.prototype.forEach.call(filters.querySelectorAll(".chip"), function (chip) {
        chip.addEventListener("click", function () { state.pickerFilter = chip.getAttribute("data-filter"); renderPicker(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll("#view-picker [data-sort]"), function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-sort") === state.pickerSort ? "true" : "false");
    });

    var shown = bench.filter(function (b) { return state.pickerFilter === "all" || rarityClass(b.card.card_type) === state.pickerFilter; });
    shown.sort(function (a, b) {
        if (state.pickerSort === "rarity") return sortByRarityThenName(a.card, b.card);
        return (b.points - a.points) || sortByRarityThenName(a.card, b.card);
    });
    var list = el("picker-list");
    if (!shown.length) {
        list.innerHTML = '<p class="note">' + (bench.length ? "No bench cards match this filter." : "Your bench is empty. Draw cards in the Cards tab.") + "</p>";
        return;
    }
    list.innerHTML = shown.map(function (b) {
        var c = b.card, r = rarityClass(c.card_type);
        return '<button type="button" class="pick" data-card="' + Number(c.id) + '">' + artHtml(c, "xs") +
            '<span style="flex:1;min-width:0"><span style="display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + _escHtml(c.player_name) +
            '</span><span class="note" style="display:block;margin:0">' + _escHtml(c.team_name || "") + ' · <span class="rar ' + r + '">' + _escHtml(r) +
            '</span></span></span><span class="pts">' + fmtPts(b.points) + "</span></button>";
    }).join("");
    Array.prototype.forEach.call(list.querySelectorAll(".pick"), function (btn) {
        btn.addEventListener("click", function () { placeCard(Number(btn.getAttribute("data-card"))); });
    });
}

Array.prototype.forEach.call(document.querySelectorAll("#view-picker [data-sort]"), function (b) {
    b.addEventListener("click", function () { state.pickerSort = b.getAttribute("data-sort"); renderPicker(); });
});

function cardName(id) {
    var all = (state.me.roster.active || []).concat(state.me.roster.bench || []);
    var c = all.find(function (x) { return x.id === id; });
    return c ? c.player_name : "Card";
}

function finishRosterChange(promise, message) {
    return promise.then(function (data) {
        if (!data || data._status) {
            showView("roster");
            el("roster-confirm").textContent = "";
            showToast(errorText(data, "The roster change failed. Try again in a moment."));
            return loadMe();
        }
        showView("roster");
        return loadMe().then(function () { el("roster-confirm").textContent = message; });
    }).catch(function () {
        showView("roster");
        showToast("The roster change failed. Try again in a moment.");
    });
}

function placeCard(benchId) {
    var slot = state.pickerSlot;
    var current = rosterSlots()[slot];
    var inName = cardName(benchId);
    if (current) {
        finishRosterChange(ebsPost("/twitch/roster/swap", {
            bench_card_id: benchId, active_card_id: current.id, slot_index: slot,
        }), inName + " in, " + current.player_name + " to the bench.");
    } else {
        finishRosterChange(ebsPost("/twitch/roster/activate/" + encodeURIComponent(benchId) + "?slot=" + slot),
            inName + " in.");
    }
}

el("btn-bench-it").addEventListener("click", function () {
    var current = rosterSlots()[state.pickerSlot];
    if (!current) return;
    finishRosterChange(ebsPost("/twitch/roster/deactivate/" + encodeURIComponent(current.id)),
        current.player_name + " to the bench.");
});

// ── Settings: identity share and Leave ──────────────────────────────────────

function renderSettings() {
    var shared = isJoined() && state.me.identity_shared;
    el("share-box").hidden = !!shared;
    el("leave-text").textContent = isJoined() && state.me.website_account
        ? "Leaving disconnects this Twitch account. Your cards and tokens stay with your account."
        : "Leaving deletes your cards, tokens and roster.";
    el("leave-note").textContent = "";
    disarmLeave();
}

el("btn-share").addEventListener("click", function () {
    requestIdentityShare();
    // The next Twitch token carries the shared id; GET /twitch/me then stores it.
    setTimeout(loadMe, 3000);
});

function disarmLeave() {
    state.leaveArmed = false;
    el("btn-leave").textContent = "Leave Kana Cards";
}

el("btn-leave").addEventListener("click", function () {
    var btn = el("btn-leave");
    if (!state.leaveArmed) {
        state.leaveArmed = true;
        btn.textContent = "Press again to leave";
        return;
    }
    btn.disabled = true;
    ebsPost("/twitch/leave").then(function (data) {
        if (!data || data._status) {
            el("leave-note").textContent = errorText(data, "Leaving failed. Try again in a moment.");
            return;
        }
        state.me = null;
        stopHeartbeat();
        state.heartbeatOn = false;
        showView("live");
        renderAll();
        showToast("You left Kana Cards.");
    }).catch(function () {
        el("leave-note").textContent = "Leaving failed. Try again in a moment.";
    }).finally(function () { btn.disabled = false; disarmLeave(); });
});

// ── PubSub: MVP announcement and token drop ─────────────────────────────────

function onPubSub(msg) {
    if (!msg || msg.type !== "mvp") return;
    loadLive();
    if (msg.player_name) showToast("MVP: " + msg.player_name);
    var drop = msg.token_drop || {};
    if (isJoined() && drop.count > 0) {
        var before = state.me.tokens || 0;
        loadMe().then(function (me) {
            if (me && (me.tokens || 0) > before) showToast("+1 token from the MVP drop");
        });
    }
}

init();
