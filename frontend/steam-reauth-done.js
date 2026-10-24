// Issue 213: the last page of the Steam re-auth popup. It reads ?steam=<key> from a
// fixed list, tells the opener the result with postMessage (targeted at this site's
// own origin, never "*"), and closes itself. The raw query value is never posted.
(function () {
  const RESULTS = {
    reauth_ok:     "ok",
    reauth_failed: "reauth_failed",
    no_session:    "no_session",
    not_linked:    "not_linked",
  };
  const key = new URLSearchParams(window.location.search).get("steam");
  const result = key !== null && Object.prototype.hasOwnProperty.call(RESULTS, key) ? RESULTS[key] : "failed";
  const opener = window.opener;
  if (opener && !opener.closed) {
    try {
      opener.postMessage({ type: "steam-reauth", result: result }, window.location.origin);
      window.close();
      return;
    } catch (e) { /* fall through to the message */ }
  }
  document.getElementById("steamReauthDoneText").textContent = result === "ok"
    ? "Confirmed with Steam. Close this window, return to the site and repeat the action."
    : "Steam did not confirm. Nothing was changed. Close this window and return to the site.";
})();
