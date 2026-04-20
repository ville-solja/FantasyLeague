// Twitch Extension — shared JS for panel, config, and live_config views.
// Loaded by each HTML view. window.EBS_URL must be set before this script loads.

"use strict";

var ext = {
    token: null,
    userId: null,
    channelId: null,
    role: null,
};

// ── Initialise ──────────────────────────────────────────────────────────────

var _initAttempts = 0;

function init() {
    if (typeof window.Twitch === "undefined" || !window.Twitch.ext) {
        // Retry until available — the dev harness injects window.Twitch after page load.
        // In production Twitch iframes this resolves on the first call.
        if (_initAttempts++ < 60) {
            setTimeout(init, 100);
        } else {
            console.error("[ext] window.Twitch.ext not available after 6s — check TWITCH_LOCAL_DEV=true");
        }
        return;
    }
    _initAttempts = 0;

    window.Twitch.ext.onAuthorized(function (auth) {
        ext.token    = auth.token;
        ext.userId   = auth.userId;
        ext.channelId = auth.channelId;

        if (typeof onReady === "function") onReady();
    });

    window.Twitch.ext.listen("broadcast", function (_target, _contentType, rawMsg) {
        try {
            var msg = JSON.parse(rawMsg);
            if (typeof onPubSub === "function") onPubSub(msg);
        } catch (e) {
            console.warn("[ext] bad PubSub message", rawMsg);
        }
    });
}

// ── EBS helpers ─────────────────────────────────────────────────────────────

function ebsGet(path) {
    return fetch(window.EBS_URL + path, {
        headers: { "Authorization": "Bearer " + ext.token },
    }).then(function (r) {
        return r.json().then(function (data) {
            if (!r.ok) { data._status = r.status; }
            return data;
        });
    });
}

function ebsPost(path, body) {
    return fetch(window.EBS_URL + path, {
        method: "POST",
        headers: {
            "Authorization": "Bearer " + ext.token,
            "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
        return r.json().then(function (data) {
            if (!r.ok) { data._status = r.status; }
            return data;
        });
    });
}

// ── Heartbeat ────────────────────────────────────────────────────────────────

var _heartbeatTimer = null;

function startHeartbeat(intervalMs) {
    intervalMs = intervalMs || 60000;
    function beat() { ebsPost("/twitch/heartbeat").catch(console.warn); }
    beat();
    _heartbeatTimer = setInterval(beat, intervalMs);
}

function stopHeartbeat() {
    if (_heartbeatTimer) clearInterval(_heartbeatTimer);
}

// ── Utility ──────────────────────────────────────────────────────────────────

function showBanner(el, msg, isError) {
    el.textContent = msg;
    el.className = "banner " + (isError ? "error" : "success");
    el.style.display = "block";
    setTimeout(function () { el.style.display = "none"; }, 5000);
}

function el(id) { return document.getElementById(id); }
