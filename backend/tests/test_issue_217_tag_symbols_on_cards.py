"""
Tests for plan-issue-217-tag-symbols-on-cards.md (resolves GitHub issue #217).

User tags move off the card image (60x60 PNG stickers composited by
`image._apply_stickers`) into an HTML overlay of tag pips down the card's left
edge, mirroring the accolade pips (#50) on the right edge. An `admin` pseudo-tag
is added for players whose Steam-verified linked user is a site admin, and
`season_winner` is never shown as a tag pip (the Fantasy Winner accolade covers it).

  Story 1: Tags Read as Symbols on Cards
  Story 2: Card Images Stop Carrying Tag Stickers
  Story 3: Tags Data Is Public but Carries No User Identity

Notes:

- Backend tests use the shared-connection `db` fixture, `_client` and `_user` from
  tests/test_issue_50_season_winners_and_holo_cards.py, so a TestClient's request
  thread sees the test's rows. A verified link is `steam_id` + `player_id` on a
  full, non-demo account (`player_links.verified_links`); a "soft" account is
  `account_type="twitch"`.
- `tags_by_player` lives in backend/accolades.py (next to `accolades_for`, which
  resolves fantasy wins through the same links).
- The admin pseudo-tag is `{"key": "admin", "label": "Admin"}` in the API; the
  frontend tooltip text is "Kana Cards admin" (from `TAG_SYMBOLS`).
- Node harness: `_escHtml`, `_ownValue` and the ACCOLADES block of app-globals.js
  (which holds the TAG SYMBOLS block), markup parsed with `html.parser`.
- Card views: the views render `.card-tag-pips` containers around `tagPipsHtml`
  output, as they do `.card-pips` around `accoladePipsHtml`; the pip markup itself
  (`card-tag-pip` and `TAG_SYMBOLS`) lives only in app-globals.js.
"""

import inspect
import json
import os
import re
from html.parser import HTMLParser

import pytest

import models  # noqa: F401  (register tables for the db fixture)
from models import Card, Player, TagDefinition, User, UserTag
from tests.test_issue_50_season_winners_and_holo_cards import (  # noqa: F401  (db fixture used by name)
    _client, _fe, _fn_body, _fn_source, _read, _rule, _run_node, _user, db,
)

_STEAM_OFFSET = 76561197960265728


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tagdef(db, key, label):
    td = db.query(TagDefinition).filter_by(key=key).first()
    if td is None:
        td = TagDefinition(key=key, label=label)
        db.add(td)
        db.commit()
    return td


def _grant(db, user, key, label=None):
    td = _tagdef(db, key, label or key.replace("_", " ").title())
    db.add(UserTag(user_id=user.id, tag_id=td.id))
    db.commit()


def _linked(db, username, n, admin=False, **fields):
    """A full, non-demo account with a Steam-verified link to player id 1000+n."""
    steam64 = str(_STEAM_OFFSET + 1000 + n)
    return _user(db, username, admin=admin, steam_id=steam64, player_id=1000 + n, **fields)


def _accolades(db):
    res = _client(db).get("/accolades")
    assert res.status_code == 200
    return res


def _tags(db):
    return _accolades(db).json()["tags"]


def _image_kwargs(db, monkeypatch, player_id):
    """Render a card of player_id with generation patched; return the generator's kwargs."""
    import image
    from routers import cards as cards_router
    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    if db.get(Player, player_id) is None:
        db.add(Player(id=player_id, name=f"P{player_id}", is_active=True))
    owner = db.query(User).filter_by(username="cardowner").first() or _user(db, "cardowner")
    card = Card(owner_id=owner.id, player_id=player_id, card_type="common",
                is_active=False, generation=1)
    db.add(card)
    db.commit()
    seen = {}

    def fake_generate(**kwargs):
        seen.update(kwargs)
        from PIL import Image
        return Image.new("RGB", (2, 2))

    monkeypatch.setattr(image, "generate_card_image", fake_generate)
    cards_router.get_card_image(card.id, db=db)
    return seen


def _globals_js():
    js = _fe("app-globals.js")
    start = js.index("// ACCOLADES (issue 50)")
    end = js.index("// END ACCOLADES (issue 50)")
    return (_fn_source(js, "_escHtml") + "\n" + _fn_source(js, "_ownValue") + "\n"
            + js[start:end])


def _tag_pips(tags_expr):
    return _run_node(_globals_js() + f"\nconsole.log(JSON.stringify(tagPipsHtml({tags_expr})));\n")


class _Pips(HTMLParser):
    """Collects each tag pip (span.card-tag-pip) with its attributes and icon."""

    def __init__(self):
        super().__init__()
        self.pips = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "span" and "card-tag-pip" in classes:
            self.pips.append({"attrs": a, "classes": classes, "icon": None})
        elif tag == "i" and self.pips and a.get("data-lucide"):
            self.pips[-1]["icon"] = a["data-lucide"]


def _parse(markup):
    p = _Pips()
    p.feed(markup)
    return p.pips


_ADMIN = {"key": "admin", "label": "Admin"}
_CASTER = {"key": "caster", "label": "Caster"}
_GENERIC = {"key": "veteran", "label": "Veteran"}


# ---------------------------------------------------------------------------
# Story 3: Tags Data Is Public but Carries No User Identity
# ---------------------------------------------------------------------------

def test_get_accolades_tags_admin_first_then_caster_then_generic(db):
    """Backend: GET /accolades `tags` maps a verified-linked player to [admin, caster, generic tag] as {key, label}, admin first, others in tag-definition order."""
    _tagdef(db, "veteran", "Veteran")       # defined before caster: caster still comes first
    _tagdef(db, "caster", "Caster")
    _tagdef(db, "zealot", "Zealot")
    u = _linked(db, "boss", 1, admin=True)
    for key in ("zealot", "caster", "veteran"):
        _grant(db, u, key)
    assert _tags(db) == {"1001": [_ADMIN, _CASTER, {"key": "veteran", "label": "Veteran"},
                                  {"key": "zealot", "label": "Zealot"}]}


def test_get_accolades_tags_admin_only_user_gets_admin_pseudo_tag(db):
    """Backend: an admin with no tags still gets [{key: "admin", label: "Admin"}] on their verified player."""
    _linked(db, "boss", 1, admin=True)
    _linked(db, "plain", 2)
    assert _tags(db) == {"1001": [_ADMIN]}


def test_get_accolades_tags_leaves_out_season_winner(db):
    """Backend: a user holding `season_winner` (plus caster) gets only caster in `tags`; a user with only `season_winner` has no `tags` entry."""
    both = _linked(db, "both", 1)
    _grant(db, both, "season_winner", "Season Winner")
    _grant(db, both, "caster", "Caster")
    winner = _linked(db, "winner", 2)
    _grant(db, winner, "season_winner")
    assert _tags(db) == {"1001": [_CASTER]}


def test_get_accolades_tags_empty_when_no_verified_link(db):
    """Backend: `tags` is present and empty ({}) when no user is verifiably linked to a player."""
    u = _user(db, "lonely", admin=True)
    _grant(db, u, "caster", "Caster")
    body = _accolades(db).json()
    assert "tags" in body and body["tags"] == {}


def test_get_accolades_tags_ignores_typed_in_or_stale_link(db):
    """Backend: a tagged admin with player_id but no steam_id (typed-in/stale link) contributes nothing to `tags`."""
    stale = _user(db, "stale", admin=True, player_id=4242)
    _grant(db, stale, "caster", "Caster")
    assert _tags(db) == {}


def test_get_accolades_tags_ignores_demo_account(db):
    """Backend: a tagged demo account with steam_id + player_id contributes nothing to `tags`."""
    demo = _linked(db, "demo", 1, admin=True, is_demo=True)
    _grant(db, demo, "caster", "Caster")
    assert _tags(db) == {}


def test_get_accolades_tags_ignores_soft_twitch_account(db):
    """Backend: a tagged soft (Twitch-only, non-full) account with steam_id + player_id contributes nothing to `tags`."""
    soft = _linked(db, "soft", 1, admin=True, account_type="twitch")
    _grant(db, soft, "caster", "Caster")
    assert _tags(db) == {}


def test_get_accolades_tags_has_no_user_ids_usernames_or_emails(db):
    """Backend: with tags present, the raw GET /accolades body contains no user id, username or email field or value."""
    u = _linked(db, "secretcaster", 1, admin=True, uid=987654)
    _grant(db, u, "caster", "Caster")
    raw = _accolades(db).text
    body = json.loads(raw)
    assert body["tags"]["1001"] == [_ADMIN, _CASTER]
    for entry in body["tags"]["1001"]:
        assert set(entry) == {"key", "label"}
    for needle in ("username", "user_id", "email", "secretcaster", "@example.com", "987654",
                   u.steam_id):
        assert needle not in raw, needle


def test_tags_by_player_returns_verified_tags_without_identity(db, monkeypatch):
    """Backend: `tags_by_player(db)` returns {player_id: [{key, label}]} with only key/label fields, built from `player_links.verified_links`."""
    import accolades
    import player_links
    a = _linked(db, "alice", 1)
    b = _linked(db, "bob", 2)
    _grant(db, a, "caster", "Caster")
    _grant(db, b, "veteran", "Veteran")
    got = accolades.tags_by_player(db)
    assert got == {1001: [_CASTER], 1002: [_GENERIC]}
    assert all(set(t) == {"key", "label"} for lst in got.values() for t in lst)
    # The links come from player_links.verified_links: dropping bob's link drops his tags.
    real = player_links.verified_links
    monkeypatch.setattr(player_links, "verified_links",
                        lambda d: {k: v for k, v in real(d).items() if k != b.id})
    assert accolades.tags_by_player(db) == {1001: [_CASTER]}


def test_get_accolades_keeps_existing_keys(db):
    """Backend: GET /accolades still returns current_season, current_season_short and players alongside the new tags field."""
    u = _linked(db, "alice", 1)
    _grant(db, u, "caster", "Caster")
    body = _accolades(db).json()
    assert {"current_season", "current_season_short", "players", "tags"} <= set(body)
    assert isinstance(body["players"], dict)


# ---------------------------------------------------------------------------
# Story 2: Card Images Stop Carrying Tag Stickers
# ---------------------------------------------------------------------------

def test_image_module_has_no_sticker_compositing():
    """Source-reading (image.py): `_apply_stickers` and the STICKER_* constants are removed."""
    import image
    src = _read("backend", "image.py")
    assert "_apply_stickers" not in src and "STICKER_" not in src
    assert "stickers" not in src.lower()
    assert not hasattr(image, "_apply_stickers")
    assert not [n for n in dir(image) if n.startswith("STICKER")]


def test_generate_card_image_has_no_tag_keys_parameter():
    """Backend: `inspect.signature(image.generate_card_image)` has no `tag_keys` parameter."""
    import image
    params = inspect.signature(image.generate_card_image).parameters
    assert "tag_keys" not in params
    assert not [p for p in params if "tag" in p]


def test_get_card_image_route_reads_no_tags():
    """Source-reading (routers/cards.py): get_card_image no longer queries UserTag/TagDefinition or passes `tag_keys`."""
    src = _read("backend", "routers", "cards.py")
    fn = src[src.index("def get_card_image("):src.index("def get_card_image_route(")]
    for needle in ("UserTag", "TagDefinition", "tag_keys", "player_links", "user_tags"):
        assert needle not in fn, needle


def test_get_card_image_for_tagged_player_calls_generator_without_tags(db, monkeypatch):
    """Backend: rendering a card of a verified caster calls generate_card_image without any tag argument (failure path: tags no longer reach the image)."""
    u = _linked(db, "caster", 1, admin=True)
    _grant(db, u, "caster", "Caster")
    kwargs = _image_kwargs(db, monkeypatch, 1001)
    assert kwargs, "the generator was called"
    assert not [k for k in kwargs if "tag" in k]
    assert "caster" not in json.dumps({k: v for k, v in kwargs.items()}, default=str).lower()


def test_tag_change_shows_on_next_accolades_load_without_image_change(db, monkeypatch):
    """Backend: granting then removing caster (and toggling is_admin) changes GET /accolades `tags` on the next call while the card image generator receives identical arguments."""
    u = _linked(db, "alice", 1)
    before_img = _image_kwargs(db, monkeypatch, 1001)
    assert _tags(db) == {}

    _grant(db, u, "caster", "Caster")
    assert _tags(db) == {"1001": [_CASTER]}
    assert _image_kwargs(db, monkeypatch, 1001) == before_img

    u.is_admin = True
    db.commit()
    assert _tags(db) == {"1001": [_ADMIN, _CASTER]}
    assert _image_kwargs(db, monkeypatch, 1001) == before_img

    db.query(UserTag).filter_by(user_id=u.id).delete()
    u.is_admin = False
    db.commit()
    assert _tags(db) == {}
    assert _image_kwargs(db, monkeypatch, 1001) == before_img


# ---------------------------------------------------------------------------
# Story 1: Tags Read as Symbols on Cards
# ---------------------------------------------------------------------------

def test_tag_symbols_registry_defines_admin_caster_and_generic():
    """Source-reading/Node harness (app-globals.js): TAG_SYMBOLS maps admin -> shield "Kana Cards admin" --tag-admin, caster -> mic "Caster" --tag-caster, with a generic tag fallback using --tag-generic."""
    out = _run_node(_globals_js() + "\nconsole.log(JSON.stringify({s: TAG_SYMBOLS, g: TAG_SYMBOL_GENERIC, h: TAG_SYMBOLS_HIDDEN}));\n")
    s, g = out["s"], out["g"]
    assert (s["admin"]["icon"], s["admin"]["tip"], s["admin"]["token"]) == ("shield", "Kana Cards admin", "--tag-admin")
    assert (s["caster"]["icon"], s["caster"]["tip"], s["caster"]["token"]) == ("mic", "Caster", "--tag-caster")
    assert (g["icon"], g["token"]) == ("tag", "--tag-generic")
    assert s["admin"]["order"] < s["caster"]["order"] < g["order"]
    assert "season_winner" in out["h"] and "season_winner" not in s


def test_tag_pips_html_orders_admin_caster_generic():
    """Node harness: tagPipsHtml([generic, caster, admin]) renders pips in admin, caster, generic order with shield, mic and tag icons."""
    pips = _parse(_tag_pips(json.dumps([_GENERIC, _CASTER, _ADMIN])))
    assert [p["icon"] for p in pips] == ["shield", "mic", "tag"]
    assert [p["attrs"]["aria-label"] for p in pips] == ["Kana Cards admin", "Caster", "Veteran"]
    assert "card-tag-pip--admin" in pips[0]["classes"] and "card-tag-pip--caster" in pips[1]["classes"]
    assert "card-tag-pip--generic" in pips[2]["classes"]
    # Two generic tags keep the order they were given (tag-definition order from the API).
    two = _parse(_tag_pips(json.dumps([{"key": "b", "label": "Bee"}, _CASTER, {"key": "a", "label": "Ay"}])))
    assert [p["attrs"]["aria-label"] for p in two] == ["Caster", "Bee", "Ay"]


def test_tag_pips_html_tooltip_uses_data_tip_and_aria_label():
    """Node harness: each tag pip carries data-tip and an identical aria-label ("Kana Cards admin", "Caster", the generic tag's label), and is focusable like accolade pips."""
    markup = _tag_pips(json.dumps([_ADMIN, _CASTER, _GENERIC]))
    pips = _parse(markup)
    assert [p["attrs"]["data-tip"] for p in pips] == ["Kana Cards admin", "Caster", "Veteran"]
    for p in pips:
        assert p["attrs"]["aria-label"] == p["attrs"]["data-tip"]
        assert p["attrs"]["tabindex"] == "0" and p["attrs"]["role"] == "listitem"
    assert 'role="list"' in markup and 'aria-label="Tags"' in markup
    # The shared tooltip (data-tip) is what accolade pips use.
    assert "[data-tip]" in _fn_body(_fe("app-globals.js"), "_accoladeTipTarget")


def test_tag_pips_html_escapes_generic_label():
    """Node harness: a generic tag label with HTML characters is escaped in data-tip and aria-label."""
    evil = '<img src=x onerror="alert(1)">&'
    markup = _tag_pips(json.dumps([{"key": "x", "label": evil}]))
    assert "<img" not in markup and '"alert(1)"' not in markup
    pips = _parse(markup)
    assert len(pips) == 1
    assert pips[0]["attrs"]["data-tip"] == evil and pips[0]["attrs"]["aria-label"] == evil


def test_tag_pips_html_never_renders_season_winner():
    """Node harness: tagPipsHtml([{key: "season_winner", ...}]) renders no pip."""
    assert _tag_pips(json.dumps([{"key": "season_winner", "label": "Season Winner"}])) == ""
    pips = _parse(_tag_pips(json.dumps([{"key": "season_winner", "label": "Season Winner"}, _CASTER])))
    assert [p["attrs"]["aria-label"] for p in pips] == ["Caster"]


def test_tag_pips_html_empty_for_no_tags():
    """Node harness: tagPipsHtml([]) / undefined, and playerTags for a player missing from /accolades tags, render no pip markup."""
    out = _run_node(_globals_js() + """
_tagsByPlayer = {"7": [{key: "caster", label: "Caster"}]};
console.log(JSON.stringify([tagPipsHtml([]), tagPipsHtml(undefined), tagPipsHtml(null),
                            tagPipsHtml(playerTags(99)), playerTags(99), playerTags("__proto__")]));
""")
    assert out == ["", "", "", "", [], []]


def test_player_tags_reads_cached_accolades_tags():
    """Node harness: playerTags(playerId) returns the list from the cached /accolades `tags` map (string player-id keys)."""
    out = _run_node("const API = '';\n" + _globals_js() + """
globalThis.fetch = () => Promise.resolve({ok: true, json: () => Promise.resolve({
  current_season: "Season 16", players: {}, tags: {"1001": [{key: "admin", label: "Admin"}, {key: "caster", label: "Caster"}]}})});
loadAccolades().then(() => {
  console.log(JSON.stringify([playerTags(1001), playerTags("1001"), playerTags(1002)]));
});
""")
    both = [_ADMIN, _CASTER]
    assert out == [both, both, []]


def test_card_views_render_tag_pips_beside_accolade_pips():
    """Source-reading: card viewer, draw reveal, My Team roster and bench, and collection each render `.card-tag-pips` via tagPipsHtml next to `.card-pips`."""
    cards = _fe("app-cards.js")
    overlay = _fn_body(cards, "_renderCardAccolades")  # the card viewer and the draw reveal
    assert "tagPipsHtml(tags)" in overlay and "playerTags(card.player_id)" in overlay
    assert 'class="card-tag-pips"' in overlay and 'class="card-pips"' in overlay
    assert "_renderCardAccolades(card, drawFx)" in _fn_body(cards, "showCard")
    slot = _fn_body(_fe("app-roster.js"), "_cardSlotHTML")  # My Team roster and bench (the collection)
    assert "tagPipsHtml(playerTags(c.player_id))" in slot
    assert 'class="card-tag-pips"' in slot and 'class="card-pips"' in slot
    # The roster re-renders when GET /accolades (which carries tags) arrives.
    load = _fn_body(_fe("app-globals.js"), "loadAccolades")
    assert "_tagsByPlayer = data.tags" in load and "_rerenderRosterPips" in load


def test_player_popup_header_shows_tag_pips_before_accolade_pips():
    """Source-reading (app-player-popup.js): the popup header renders tagPipsHtml output before accoladePipsHtml output."""
    fn = _fn_body(_fe("app-player-popup.js"), "renderPlayerAccolades")
    assert "playerTags(p.id)" in fn
    assert "pipsEl.innerHTML = tagPips + accoladePipsHtml(list)" in fn


def test_no_view_builds_tag_pip_markup_outside_helper():
    """Source-reading: no frontend module except tagPipsHtml in app-globals.js contains tag pip markup (`card-tag-pip` class strings or TAG_SYMBOLS lookups)."""
    pip_re = re.compile(r"card-tag-pip(?!s)|TAG_SYMBOL")
    frontend = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    for name in sorted(os.listdir(frontend)):
        if not name.endswith(".js"):
            continue
        src = _fe(name)
        if name == "app-globals.js":
            start = src.index("// TAG SYMBOLS (issue 217)")
            end = src.index("// END TAG SYMBOLS (issue 217)")
            src = src[:start] + src[end:]
        assert not pip_re.search(src), name
    block = _fe("app-globals.js")
    helper = _fn_body(block, "tagPipsHtml")
    assert "card-tag-pip card-tag-pip--" in helper and "TAG_SYMBOLS" in helper


def test_tag_color_tokens_identical_in_both_color_files():
    """Source-reading: --tag-admin, --tag-caster and --tag-generic are defined with identical values in frontend/colors_and_type.css and design/colors_and_type.css."""
    fe = _read("frontend", "colors_and_type.css")
    de = _read("design", "colors_and_type.css")
    for token in ("--tag-admin", "--tag-caster", "--tag-generic"):
        vals = [re.findall(rf"{token}:\s*([^;]+);", css) for css in (fe, de)]
        assert len(vals[0]) == 1 and vals[0] == vals[1], token
        assert "#" not in vals[0][0]
    assert re.search(r"--tag-admin:\s*var\(--badge-admin\)", fe)
    assert re.search(r"--tag-caster:\s*var\(--badge-caster\)", fe)


def test_card_tag_pips_css_on_left_edge_before_guided_tour():
    """Source-reading (style.css): `.card-tag-pips` is positioned on the left edge (opposite `.card-pips`) and defined before the GUIDED TOUR section."""
    css = _fe("style.css")
    tags = _rule(css, ".card-slot .card-tag-pips")
    assert tags and "position: absolute" in tags[0] and "left:" in tags[0] and "right:" not in tags[0]
    assert _rule(css, ".reveal-pips .card-tag-pips")
    accolades = _rule(css, ".card-slot .card-pips")[0]
    assert "right:" in accolades and "left:" not in accolades
    assert "flex-direction: column" in _rule(css, ".card-tag-pips .tag-pips")[0]
    pip = _rule(css, ".card-tag-pip")
    assert pip and any("var(--pip-color)" in body for body in pip)
    assert "var(--tag-admin)" in _rule(css, ".card-tag-pip--admin")[0]
    assert "var(--tag-caster)" in _rule(css, ".card-tag-pip--caster")[0]
    tour = css.index("GUIDED TOUR (issue #144)")
    assert css.index(".card-slot .card-tag-pips") < tour
    assert max(m.start() for m in re.finditer(r"card-tag-pip", css)) < tour


def test_design_readme_has_tag_symbol_table():
    """Source-reading (.claude/skills/README.md): a tag symbol table lists admin/shield, caster/mic and other/tag next to the accolade symbol table."""
    readme = _read(".claude", "skills", "README.md")
    acc = readme.index("### Accolade symbols")
    tag = readme.index("### Tag symbols")
    assert acc < tag
    nxt = readme.index("\n### ", acc + 1)
    assert readme.index("\n### ", tag + 1) > tag and nxt == tag - 1  # the section right after
    section = readme[tag:readme.index("\n### ", tag + 1)]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    assert any("Admin" in r and "`shield`" in r and "--tag-admin" in r for r in rows)
    assert any("Caster" in r and "`mic`" in r and "--tag-caster" in r for r in rows)
    assert any("other tag" in r and "`tag`" in r and "--tag-generic" in r for r in rows)
    assert "tagPipsHtml" in section and "season" in section.lower()


def test_tags_by_player_leaves_out_tester_accounts(db):
    """Security follow-up: a tester account's tags and admin flag publish no tag pips (testers never show publicly)."""
    import accolades
    from models import User, TagDefinition, UserTag
    tag = TagDefinition(key="caster", label="Caster")
    db.add(tag); db.flush()
    u = User(username="tester1", email="t@example.invalid", password_hash="x", is_admin=True,
             is_tester=True, account_type="full", is_demo=False, steam_id="76561198000000001", player_id=901)
    db.add(u); db.flush()
    db.add(UserTag(user_id=u.id, tag_id=tag.id)); db.commit()
    assert 901 not in accolades.tags_by_player(db)
    u.is_tester = False; db.commit()
    assert [t["key"] for t in accolades.tags_by_player(db)[901]] == ["admin", "caster"]
