"use strict";

// Issue #180: the broadcaster's step-by-step Connection check. Every value is set
// with textContent: ebs_url comes from the configuration, not from this package.

var CHECK_STEPS = [
    { key: "package",   label: "Package" },
    { key: "address",   label: "Backend address" },
    { key: "reachable", label: "Backend reachable" },
    { key: "token",     label: "Twitch token accepted" },
    { key: "mvp",       label: "MVP selection" },
];
var CHECK_STATE_TEXT = { ok: "OK", failed: "Failed", not_checked: "Not checked" };

var _checkRun = 0;
var _configTimedOut = false;

function _step(state, detail, code) {
    return { state: state, detail: detail || "", code: code || null };
}

function _notChecked(detail) {
    return _step("not_checked", detail || "An earlier step failed.");
}

function renderConnectionCheck(results) {
    var list = el("conn-check");
    while (list.firstChild) list.removeChild(list.firstChild);
    CHECK_STEPS.forEach(function (s) {
        var r = results[s.key] || _notChecked("Checking…");
        var li = document.createElement("li");
        var state = document.createElement("span");
        state.className = "conn-state conn-" + r.state.replace("_", "-");
        state.textContent = CHECK_STATE_TEXT[r.state];
        var label = document.createElement("span");
        label.textContent = s.label;
        var detail = document.createElement("span");
        detail.className = "conn-detail";
        detail.textContent = r.detail;
        li.appendChild(state);
        li.appendChild(label);
        li.appendChild(detail);
        list.appendChild(li);
    });
    // The same reason code the panel shows, for the first failed step that has one.
    var code = null;
    CHECK_STEPS.some(function (s) {
        var r = results[s.key];
        if (r && r.state === "failed" && r.code) { code = r.code; return true; }
        return false;
    });
    var codeEl = el("conn-code");
    codeEl.textContent = code ? "Reason code: " + code : "";
    codeEl.hidden = !code;
}

function checkPackage() {
    if (typeof EXT_BUILD === "undefined" || !EXT_BUILD) {
        return _step("failed", "This package has no build stamp: it was built by an older package.sh. " +
            "Its backend origins can't be shown.");
    }
    var origins = (EXT_BUILD.origins || []).join(", ");
    return _step("ok", "Version " + EXT_BUILD.version + ". Backend origins: " +
        (origins || "none (unpackaged files, local test only)") + ".");
}

function checkAddress() {
    var url = ext.configuredUrl;
    if (!url) {
        if (!_configTimedOut) return _notChecked("Waiting for the extension configuration…");
        return _step("failed", "No backend URL (ebs_url) in the extension's global configuration.",
            EXT_REASON.CONFIG);
    }
    if (!_ebsUrlAllowed(url)) {
        return _step("failed", url + " — its origin " + _originOf(url) +
            " is not one of this package's backend origins.", EXT_REASON.ORIGIN);
    }
    return _step("ok", url + " — origin packaged.");
}

function checkReachable() {
    return fetch(ext.ebsUrl + "/twitch/ping").then(function (r) {
        if (r.ok) return _step("ok", "The backend answered.");
        if (r.status >= 500) return _step("failed", "The backend answered with an error (status " + r.status + ").", EXT_REASON.SERVER);
        return _step("failed", "The backend answered status " + r.status + ": it may be an older version.", EXT_REASON.REACH);
    }, function () {
        return _step("failed", "No answer from the backend: DNS, TLS, the extension's URL Fetching Domains, " +
            "or the backend refused this extension's origin (CORS).", EXT_REASON.REACH);
    });
}

function checkToken() {
    if (!ext.token) return Promise.resolve({ token: _notChecked("Waiting for the Twitch token…"), data: null });
    return ebsGet("/twitch/check").then(function (data) {
        var status = data && data._status;
        if (!status) return { token: _step("ok", "Role: " + ((data && data.role) || "unknown") + "."), data: data };
        if (status === 401) {
            return { token: _step("failed", "The backend refused the Twitch token: its extension secret does not match this extension.", EXT_REASON.TOKEN), data: null };
        }
        if (status >= 500) {
            return { token: _step("failed", "The backend answered with an error (status " + status + ").", EXT_REASON.SERVER), data: null };
        }
        return { token: _step("failed", "The backend answered status " + status + "."), data: null };
    }, function () {
        return { token: _step("failed", "No answer from the backend.", EXT_REASON.REACH), data: null };
    });
}

function checkMvp(data) {
    if (!data) return _notChecked();
    if (data.role !== "broadcaster") return _notChecked("Only the broadcaster's token shows this.");
    if (data.approval === "approved") return _step("ok", "approved: this channel can set match MVPs.");
    if (data.approval === "rejected") return _step("failed", "rejected: this channel isn't approved to set match MVPs.");
    return _step("failed", "pending: waiting for the league's approval. Open the MVP tool once so the league sees the request.");
}

function runConnectionCheck() {
    var run = ++_checkRun;
    var results = {};
    function show() { if (run === _checkRun) renderConnectionCheck(results); }
    function failRest(from) {
        var skip = false;
        CHECK_STEPS.forEach(function (s) {
            if (s.key === from) skip = true;
            else if (skip && !results[s.key]) results[s.key] = _notChecked();
        });
    }
    ext.failReason = null;
    results["package"] = checkPackage();
    results.address = checkAddress();
    if (results.address.state !== "ok") {
        if (results.address.code) setFailReason(results.address.code);
        failRest("address");
        show();
        return Promise.resolve(results);
    }
    show();
    return checkReachable().then(function (reach) {
        results.reachable = reach;
        if (reach.state !== "ok") {
            if (reach.code) setFailReason(reach.code);
            failRest("reachable");
            return;
        }
        show();
        return checkToken().then(function (t) {
            results.token = t.token;
            results.mvp = t.token.state === "not_checked"
                ? _notChecked("Waiting for the Twitch token…") : checkMvp(t.data);
        });
    }).then(function () {
        show();
        return results;
    });
}

function onReady() {
    el("ebs-display").textContent = ext.ebsUrl || "(not configured — set ebs_url in the global config segment)";
    runConnectionCheck();
}

function onConfigTimeout() {
    _configTimedOut = true;
    el("ebs-display").textContent = ext.configuredUrl || "(not configured — set ebs_url in the global config segment)";
    runConnectionCheck();
}

el("btn-check-again").addEventListener("click", runConnectionCheck);
renderConnectionCheck({});

init();
