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
    configuredUrl: null,  // ebs_url as configured, even when refused (configuration page only)
    failReason: null,     // last reason code (issue #180), one of EXT_REASON
};

// ── Reason codes (issue #180) ───────────────────────────────────────────────
// Each failure on the way to the backend gets a short code that viewers can pass
// on; the troubleshooting table in the docs maps each code to its fix.
var EXT_REASON = {
    ORIGIN: "E-ORIGIN",  // configured backend origin is not in this package
    CONFIG: "E-CONFIG",  // no backend URL in the configuration after 8 seconds
    REACH:  "E-REACH",   // backend not reached: network, TLS or CORS
    TOKEN:  "E-TOKEN",   // backend answered 401 to the Twitch token
    SERVER: "E-SERVER",  // backend answered 5xx
};

function _originOf(url) {
    try { return new URL(url).origin; } catch (e) { return "(invalid URL)"; }
}

// Logs the code with the configured backend origin only: never the token or a path.
function setFailReason(code) {
    ext.failReason = code;
    var origin = ext.configuredUrl ? _originOf(ext.configuredUrl) : "(none)";
    console.warn("[ext] " + code + " backend origin: " + origin);
}

// " (code: E-…)" for the viewer-facing "not available" messages, or "".
function failReasonSuffix() {
    return ext.failReason ? " (code: " + ext.failReason + ")" : "";
}

// ── Readiness gate ──────────────────────────────────────────────────────────
// onReady() fires once both the EBS URL (from Configuration Service) and the
// Twitch JWT are available. Subsequent onAuthorized refreshes (token renewal)
// also call onReady so pages can re-fetch with the new token.

var _cfgReady  = false;
var _authReady = false;
var _cfgTimedOut = false;

// Calls the page's onConfigTimeout once: at once for E-ORIGIN, or after 8 seconds.
function _configTimeout() {
    if (_cfgTimedOut) return;
    _cfgTimedOut = true;
    if (typeof onConfigTimeout === "function") onConfigTimeout();
}

// The configured EBS URL is used only when its origin was baked into the package
// (ebs-origins.js, written by package.sh; issue #164). Anyone holding the
// extension secret can rewrite the configuration, but not the reviewed package.
// With no packaged origins, only the local dev harness accepts any URL.
function _ebsUrlAllowed(url) {
    var allowed = (typeof EBS_ALLOWED_ORIGINS !== "undefined" && EBS_ALLOWED_ORIGINS) || [];
    if (!allowed.length) return window.__EXT_DEV_HARNESS === true;
    var parsed;
    try { parsed = new URL(url); } catch (e) { return false; }
    return parsed.protocol === "https:" && allowed.indexOf(parsed.origin) !== -1;
}

function _onCfgChanged() {
    var global = window.Twitch.ext.configuration.global;
    if (global && global.content) {
        try {
            var cfg = JSON.parse(global.content);
            ext.configuredUrl = cfg.ebs_url || null;
            if (cfg.ebs_url && !_ebsUrlAllowed(cfg.ebs_url)) {
                // The origin was not packaged into this version: say so at once.
                setFailReason(EXT_REASON.ORIGIN);
                _configTimeout();
                return;
            }
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
        if (_cfgReady || _cfgTimedOut) return;
        setFailReason(EXT_REASON.CONFIG);
        _configTimeout();
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
            if (r.status === 401) setFailReason(EXT_REASON.TOKEN);
            else if (r.status >= 500) setFailReason(EXT_REASON.SERVER);
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

// fetch rejects when the backend can't be reached: DNS, TLS, a missing URL Fetching
// Domain or a CORS refusal. The browser does not say which, so all are E-REACH.
function _unreachable(err) {
    setFailReason(EXT_REASON.REACH);
    throw err;
}

function ebsGet(path) {
    if (!ext.ebsUrl) return _notConfiguredYet();
    return fetch(ext.ebsUrl + path, {
        headers: { "Authorization": "Bearer " + ext.token },
    }).then(_parseResponse, _unreachable);
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
    }).then(_parseResponse, _unreachable);
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
