"""Small fixes after the #201 and #202 security reviews.

- Image URLs from ingested or admin data (player avatars, team logos) go through
  `_imgSrc()` (app-globals.js): http(s) or a same-origin "/" path, escaped; anything
  else becomes an empty src, so a quote can't add attributes and no other scheme loads.
- The admin tag definitions table escapes the tag key and label.
- `caster_tags.sync_safely()` flushes the caller's pending writes before its
  savepoint, so only sync() errors are caught and logged as a Caster sync failure.
"""
import json
import os
import re
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def _read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
        return f.read()


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _fn_src(js, name):
    m = re.search(r"function " + name + r"\(.*?\n\}\n", js, re.S)
    assert m, f"{name} not found"
    return m.group(0)


class TestImgSrc:
    def test_external_image_urls_use_img_src(self):
        for name, field in [("app-admin-players.js", "avatar_url"), ("app-leaderboard.js", "avatar_url"),
                            ("app-cards.js", "logo_url")]:
            js = _read(name)
            srcs = re.findall(r'src="\$\{([^}]*' + field + r'[^}]*)\}"', js)
            assert srcs, f"no {field} image in {name}"
            for expr in srcs:
                assert expr.startswith("_imgSrc("), f"{name}: unvalidated src {expr}"

    def test_img_src_behaviour(self):
        node = _node()
        if not node:
            pytest.skip("node not available")
        js = _read("app-globals.js")
        script = "\n".join(_fn_src(js, n) for n in ("_escHtml", "_safeUrl", "_imgSrc")) + """
const cases = ["https://a.example/x.png", "/static/logo.png", "//evil.example/x.png",
               "javascript:alert(1)", 'https://a.example/x.png" onerror="alert(1)', null, ""];
console.log(JSON.stringify(cases.map(_imgSrc)));
"""
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        assert got[0] == "https://a.example/x.png"
        assert got[1] == "/static/logo.png"
        assert got[2] == ""
        assert got[3] == ""
        assert '"' not in got[4] and "&quot;" in got[4]
        assert got[5] == "" and got[6] == ""


class TestTagDefinitionsTable:
    def test_key_and_label_escaped(self):
        js = _read("app-admin-users.js")
        assert "${_escHtml(t.key)}</code>" in js
        assert "<td>${_escHtml(t.label)}</td>" in js
        assert "<td>${t.label}</td>" not in js


class TestSyncSafelyFlush:
    def test_caller_flush_error_is_not_swallowed(self):
        import caster_tags
        db = MagicMock()
        db.flush.side_effect = RuntimeError("caller write failed")
        with pytest.raises(RuntimeError):
            caster_tags.sync_safely(db)
        db.begin_nested.assert_not_called()

    def test_sync_error_is_still_contained(self, monkeypatch):
        import caster_tags
        db = MagicMock()
        monkeypatch.setattr(caster_tags, "sync", MagicMock(side_effect=ValueError("boom")))
        assert caster_tags.sync_safely(db) == (0, 0)
