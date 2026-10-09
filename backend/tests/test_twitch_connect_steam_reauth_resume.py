"""
Connect Twitch from an account without a password (created through Steam).

/auth/twitch/start answers reauth_required without a recent identity check. Such an
account confirms with a Steam round trip, which leaves the page; before this fix the
page came back with "Repeat the action to continue." under Steam and never reached
Twitch. The page now remembers the pending Connect Twitch in sessionStorage and resumes
it on reauth_ok.

Static checks on the frontend files, like the other frontend tests in this suite.
"""
import os
import re

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def _read(name: str) -> str:
    with open(os.path.join(_FRONTEND_DIR, name), encoding="utf-8") as f:
        return f.read()


def _function(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    nxt = re.search(r"\n(?:async )?function |\n// ---", js[start + 1:])
    return js[start: start + 1 + nxt.start()] if nxt else js[start:]


def test_twitch_reauth_prompt_names_connect_twitch_as_resumable():
    handler = _function(_read("app-profile.js"), "handleTwitchReturn")
    assert '_promptReauth("connectTwitch")' in handler


def test_steam_reauth_stores_the_pending_action_before_leaving():
    admin = _read("app-admin.js")
    assert "_reauthResume = resume || null" in _function(admin, "_promptReauth")
    start = _function(admin, "startSteamReauth")
    assert 'sessionStorage.setItem("reauthResume", _reauthResume)' in start
    # Stored before navigating away, and cleared when no action is pending.
    assert start.index("sessionStorage.setItem") < start.index("window.location.href")
    assert 'sessionStorage.removeItem("reauthResume")' in start


def test_steam_return_resumes_connect_twitch_on_reauth_ok():
    auth = _read("app-auth.js")
    assert re.search(r"_REAUTH_RESUMABLE\s*=\s*\{\s*connectTwitch:", auth)
    taker = _function(auth, "_takeReauthResume")
    # Read once and removed, so a later Steam return never replays it.
    assert 'sessionStorage.removeItem("reauthResume")' in taker
    handler = _function(auth, "handleSteamReturn")
    assert "_takeReauthResume()" in handler
    assert re.search(r'key === "reauth_ok" && resume\)\s*\{[^}]*resume\(\);', handler)


def test_only_listed_actions_can_be_resumed():
    taker = _function(_read("app-auth.js"), "_takeReauthResume")
    # Looked up in the allowlist, never evaluated or used as a URL.
    assert "_REAUTH_RESUMABLE[action]" in taker
    assert "eval(" not in taker and "location" not in taker
