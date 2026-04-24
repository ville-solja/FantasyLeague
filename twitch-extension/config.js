"use strict";

function onReady() {
    el("ebs-display").textContent = ext.ebsUrl || "(not configured — set ebs_url in the global config segment)";
}

init();
