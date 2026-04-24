// Twitch Extension — shared JS for panel, config, and live_config views.
// EBS URL is read at runtime from Twitch.ext.configuration.global
// (set once by the developer in the Twitch Extensions console).
// The dev harness stubs Twitch.ext.configuration so local dev works unchanged.

"use strict";

var ext = {
    token:     null,
    userId:    null,
    channelId: null,
    role:      null,
    ebsUrl:    null,
};

// ── Readiness gate ──────────────────────────────────────────────────────────
// onReady() fires once both the EBS URL (from Configuration Service) and the
// Twitch JWT are available. Subsequent onAuthorized refreshes (token renewal)
// also call onReady so pages can re-fetch with the new token.

var _cfgReady  = false;
var _authReady = false;

function _onCfgChanged() {
    var global = window.Twitch.ext.configuration.global;
    if (global && global.content) {
        try {
            var cfg = JSON.parse(global.content);
            if (cfg.ebs_url) {
                ext.ebsUrl = cfg.ebs_url;
                _cfgReady  = true;
                if (_authReady && typeof onReady === "function") onReady();
            }
        } catch (e) {
            console.warn("[ext] bad global config JSON", e);
        }
    }
}

function _onAuth(auth) {
    ext.token     = auth.token;
    ext.userId    = auth.userId;
    ext.channelId = auth.channelId;
    _authReady    = true;
    if (_cfgReady && typeof onReady === "function") onReady();
}

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

    window.Twitch.ext.configuration.onChanged(_onCfgChanged);

    window.Twitch.ext.onAuthorized(_onAuth);

    window.Twitch.ext.listen("broadcast", function (_target, _contentType, rawMsg) {
        try {
            var msg = JSON.parse(rawMsg);
            if (typeof onPubSub === "function") onPubSub(msg);
        } catch (e) {
            console.warn("[ext] bad PubSub message", rawMsg);
        }
    });

    // If the Configuration Service global segment never delivers an EBS URL,
    // onReady() will never fire and the panel stays blank. Surface a clear
    // message so the viewer knows setup is incomplete.
    setTimeout(function () {
        if (!_cfgReady && typeof onConfigTimeout === "function") onConfigTimeout();
    }, 8000);
}

// ── EBS helpers ─────────────────────────────────────────────────────────────

function ebsGet(path) {
    return fetch(ext.ebsUrl + path, {
        headers: { "Authorization": "Bearer " + ext.token },
    }).then(function (r) {
        return r.json().then(function (data) {
            if (!r.ok) { data._status = r.status; }
            return data;
        });
    });
}

function ebsPost(path, body) {
    return fetch(ext.ebsUrl + path, {
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

function showBanner(bannerEl, msg, isError) {
    bannerEl.textContent = msg;
    bannerEl.className   = "banner " + (isError ? "error" : "success");
    bannerEl.style.display = "block";
    setTimeout(function () { bannerEl.style.display = "none"; }, 5000);
}

function el(id) { return document.getElementById(id); }
