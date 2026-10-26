"""
Tests for backend/scripts/season_history.py: past seasons' participants and the
winner inferred from each league's last match. OpenDota is always mocked.
"""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ingest  # noqa: E402

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "season_history.py")


def _mod():
    spec = importlib.util.spec_from_file_location("season_history", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _match(start, radiant_win, rad=("Alpha", 1, [11, 12, 13, 14, 15]), dire=("Beta", 2, [21, 22, 23, 24, 25])):
    players = [{"account_id": a, "personaname": f"p{a}", "player_slot": i} for i, a in enumerate(rad[2])]
    players += [{"account_id": a, "personaname": f"p{a}", "player_slot": 128 + i} for i, a in enumerate(dire[2])]
    return {"start_time": start, "radiant_win": radiant_win, "players": players,
            "radiant_team": {"team_id": rad[1], "name": rad[0]}, "dire_team": {"team_id": dire[1], "name": dire[0]}}


def _run(mod, tmp_path, monkeypatch, leagues, matches, seasons=None, max_calls=900):
    lf = tmp_path / "leagues.json"
    lf.write_text(json.dumps({"seasons": [{"season": n, "leagues": ids} for n, ids in leagues.items()]}))
    monkeypatch.setattr(ingest, "get_league_matches", lambda lid: [m for m, (l, _) in matches.items() if l == lid])
    monkeypatch.setattr(mod, "fetch_match", lambda mid: matches[mid][1])
    lines = []
    out = tmp_path / "out.json"
    code = mod.run(seasons, cache_path=str(tmp_path / "cache.json"), out_path=str(out), pause=0,
                   max_calls=max_calls, league_file=str(lf), sleep=lambda s: None, out=lines.append)
    return code, json.loads(out.read_text()), lines


def test_winner_is_the_last_match_winner_with_its_five_players(tmp_path, monkeypatch):
    mod = _mod()
    matches = {
        101: (500, _match(1000, True)),     # Alpha wins early
        102: (500, _match(3000, False)),    # grand final: Beta (dire) wins
        103: (500, _match(2000, True)),
    }
    code, rep, lines = _run(mod, tmp_path, monkeypatch, {7: [500]}, matches)
    assert code == 0 and rep["complete"]
    d = rep["seasons"][0]["divisions"][0]
    w = d["winner"]
    assert w["final_match_id"] == 102 and w["team"]["name"] == "Beta"
    assert w["account_ids"] == [21, 22, 23, 24, 25]
    assert w["runner_up"]["name"] == "Alpha" and w["runner_up_account_ids"] == [11, 12, 13, 14, 15]
    assert any("winner: Beta over Alpha" in l for l in lines)


def test_participants_union_across_divisions_and_anonymous_skipped(tmp_path, monkeypatch):
    mod = _mod()
    m2 = _match(1000, True, rad=("Gamma", 3, [31, 32, 33, 34, None]), dire=("Beta", 2, [21, 41, 42, 43, 44]))
    matches = {201: (600, _match(1000, True)), 202: (601, m2)}
    code, rep, _ = _run(mod, tmp_path, monkeypatch, {8: [600, 601]}, matches)
    s = rep["seasons"][0]
    assert code == 0
    assert s["players"] == 10 + 8  # 21 counted once; one anonymous slot
    assert s["divisions"][1]["anonymous_slots"] == 1
    p21 = next(p for p in s["divisions"][0]["participants"] if p["account_id"] == 21)
    assert p21["games"] == 1 and p21["teams"] == ["Beta"]


def test_no_decided_match_gives_unknown_winner(tmp_path, monkeypatch):
    mod = _mod()
    code, rep, lines = _run(mod, tmp_path, monkeypatch, {9: [700]}, {301: (700, _match(1000, None))})
    assert code == 0 and rep["seasons"][0]["divisions"][0]["winner"] is None
    assert any("winner: unknown" in l for l in lines)


def test_budget_stop_writes_partial_report_and_rerun_uses_cache(tmp_path, monkeypatch):
    mod = _mod()
    matches = {401: (800, _match(1000, True)), 402: (801, _match(2000, False))}
    code, rep, _ = _run(mod, tmp_path, monkeypatch, {10: [800], 11: [801]}, matches, max_calls=2)
    assert code == 2 and not rep["complete"] and [s["season"] for s in rep["seasons"]] == [10]
    code, rep, _ = _run(mod, tmp_path, monkeypatch, {10: [800], 11: [801]}, matches, max_calls=3)
    assert code == 0 and [s["season"] for s in rep["seasons"]] == [10, 11]


def test_unknown_season_is_refused(tmp_path, monkeypatch):
    mod = _mod()
    lines = []
    lf = tmp_path / "l.json"
    lf.write_text(json.dumps({"seasons": [{"season": 4, "leagues": [1]}]}))
    code = mod.run([99], cache_path=str(tmp_path / "c.json"), out_path=str(tmp_path / "o.json"),
                   league_file=str(lf), sleep=lambda s: None, out=lines.append)
    assert code == 1 and "Season 99" in lines[0]
    assert not (tmp_path / "o.json").exists()


def test_main_requires_all_or_season():
    import pytest
    mod = _mod()
    with pytest.raises(SystemExit):
        mod.main([])
    with pytest.raises(SystemExit):
        mod.main(["--all", "--season", "4"])
