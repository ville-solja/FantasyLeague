def fantasy_score(p, weights):
    return sum(weights.get(key, 0) * p.get(key, 0) for key in weights)
