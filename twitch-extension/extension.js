// Twitch Extension — shared JS for panel, config, and live_config views.
// EBS URL is read at runtime from Twitch.ext.configuration.global
// (set once by the developer in the Twitch Extensions console).
// The dev harness stubs Twitch.ext.configuration so local dev works unchanged.

"use strict";

var ext = {
    token:      null,
    tokenSetAt: null,
    userId:     null,
    channelId:  null,
    role:       null,
    ebsUrl:     null,
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
    ext.token      = auth.token;
    ext.tokenSetAt = Date.now();
    ext.userId     = auth.userId;
    ext.channelId  = auth.channelId;
    _authReady     = true;
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

// Reads the response body as text and only then attempts JSON.parse, so a
// non-JSON error body (e.g. an HTML error page from a proxy/gateway in front
// of the EBS, rather than our own FastAPI JSON error) can't reject the promise
// chain with an uncaught SyntaxError — callers always get a plain object back,
// with _status set on any non-2xx response.
function _parseResponse(r) {
    return r.text().then(function (text) {
        var data;
        try {
            data = text ? JSON.parse(text) : {};
        } catch (e) {
            data = { detail: "Server returned a non-JSON response (status " + r.status + ")." };
        }
        if (!r.ok) {
            data._status = r.status;
            if (ext.tokenSetAt) {
                console.warn("[ext] EBS call failed with status " + r.status +
                    " — token age " + Math.round((Date.now() - ext.tokenSetAt) / 1000) + "s");
            }
        }
        return data;
    });
}

// Twitch.ext.configuration.global hasn't delivered ebs_url yet (most commonly:
// right after our own location.reload() in panel.js's 401 recovery, before the
// fresh frame has re-negotiated with Twitch's parent page). Without this guard,
// fetch(ext.ebsUrl + path) becomes fetch("null" + path) / fetch("undefined" + path),
// which the browser resolves *relative to the extension's own CDN origin* —
// sending a bogus request there instead of failing cleanly.
function _notConfiguredYet() {
    return Promise.resolve({
        detail: "Still connecting — please wait a moment and try again.",
        _status: 0,
    });
}

function ebsGet(path) {
    if (!ext.ebsUrl) return _notConfiguredYet();
    return fetch(ext.ebsUrl + path, {
        headers: { "Authorization": "Bearer " + ext.token },
    }).then(_parseResponse);
}

function ebsPost(path, body) {
    if (!ext.ebsUrl) return _notConfiguredYet();
    return fetch(ext.ebsUrl + path, {
        method: "POST",
        headers: {
            "Authorization": "Bearer " + ext.token,
            "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
    }).then(_parseResponse);
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

// Escapes untrusted text before it's concatenated into an innerHTML string.
// Team/player names come from OpenDota/Steam data ingested verbatim (see
// backend/ingest.py) and are not sanitized server-side, so any HTML built from
// them client-side must escape here — same helper/behaviour as frontend/app-globals.js.
function _escHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
