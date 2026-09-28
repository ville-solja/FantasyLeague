"""Shared "does this match count for scoring?" filters.

An admin can exclude a match from scoring (Match.excluded_from_scoring), e.g. when
its replay can never be parsed. Every fantasy-points aggregation applies one of the
helpers below so the rule lives in one place. Displays that are not about points
(schedules, match lists, player match history, ingest/purge) do not filter.
"""

# Match IDs an admin has excluded from scoring.
EXCLUDED_MATCH_IDS_SQL = "SELECT match_id FROM matches WHERE excluded_from_scoring = 1"


def scored_match_sql(alias: str = "m") -> str:
    """SQL condition on a joined `matches` row: true when the match counts for scoring.
    Put it in the JOIN's ON clause for LEFT JOINs so non-scoring matches drop to NULL."""
    return f"COALESCE({alias}.excluded_from_scoring, 0) = 0"


def scored_stat_sql(match_id_col: str = "s.match_id") -> str:
    """SQL condition on a player_match_stats match_id column, for queries that do not
    join `matches`: true when the stat row's match counts for scoring."""
    return f"{match_id_col} NOT IN ({EXCLUDED_MATCH_IDS_SQL})"

