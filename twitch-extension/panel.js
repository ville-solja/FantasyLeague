"use strict";

el("btn-link").addEventListener("click", doLink);
el("link-code-input").addEventListener("keydown", function(e) {
    if (e.key === "Enter") doLink();
});

function onReady() {
    startHeartbeat(55000);
    loadStatus();
}

function onConfigTimeout() {
    el("view-unlinked").innerHTML =
        '<p style="color:#aaa;font-size:12px;text-align:center;padding:16px 8px">' +
        'Extension not configured — contact the broadcaster.</p>';
    el("view-linked").style.display = "none";
}

function loadStatus() {
    ebsGet("/twitch/status").then(function(data) {
        if (data.linked) {
            el("token-count").textContent = data.tokens;
            el("linked-username").textContent = data.username;
            el("view-linked").style.display = "block";
            el("view-unlinked").style.display = "none";
        } else {
            el("view-unlinked").style.display = "block";
            el("view-linked").style.display = "none";
        }
    }).catch(function() {
        el("view-unlinked").style.display = "block";
        el("view-linked").style.display = "none";
        showBanner(el("banner"), "Could not reach FantasyLeague server.", true);
    });
}

function doLink() {
    var code = el("link-code-input").value.trim().toUpperCase();
    if (code.length !== 6) {
        el("link-status").textContent = "Enter the 6-character code from the FantasyLeague site.";
        return;
    }
    el("btn-link").disabled = true;
    el("link-status").textContent = "";
    ebsPost("/twitch/link", { code: code }).then(function(data) {
        if (data.linked) {
            loadStatus();
        } else {
            el("link-status").textContent = data.detail || "Linking failed. Check your code and try again.";
        }
    }).catch(function() {
        el("link-status").textContent = "Request failed.";
    }).finally(function() {
        el("btn-link").disabled = false;
    });
}

function onPubSub(msg) {
    if (msg.type === "winner" || msg.type === "token_drop") {
        el("winner-name").textContent = msg.winner_username || (msg.winners || []).join(", ");
        el("winner-msg").textContent = msg.type === "winner"
            ? "won a free card draw!"
            : "received a token drop!";
        el("winner-banner").style.display = "block";
        setTimeout(function() { el("winner-banner").style.display = "none"; }, 8000);
        loadStatus();
    }
    if (msg.type === "mvp") {
        showBanner(el("banner"), "MVP: " + msg.player_name, false);
    }
}

init();
