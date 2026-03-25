def fantasy_score(p):
    return (
        3 * p.get("kills", 0) +
        2 * p.get("assists", 0) -
        1 * p.get("deaths", 0) +
        0.02 * p.get("gold_per_min", 0) +
        1 * p.get("obs_placed", 0) +
        1.5 * p.get("sen_placed", 0) +
        0.002 * p.get("tower_damage", 0)
    )