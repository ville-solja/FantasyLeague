"""The one rule for "this account is this league player" (issue #209).

A player link exists only when a full, non-demo account has both a steam_id and a
player_id: Steam sign-in and Link Steam (steam_openid.py) set player_id from the
verified Steam id, and unlinking Steam clears it. Every reader of users.player_id goes
through this module; tests/test_issue_209_steam_verified_player_links.py has a guard
test that fails when backend code elsewhere reads the column.
"""
from sqlalchemy import func

from models import User


def _verified_filter(query):
    # NULL account_type counts as "full" and NULL is_demo as not demo, exactly as in
    # verified_player_id(), so the Python and SQL checks never disagree.
    return query.filter(User.player_id.isnot(None), User.steam_id.isnot(None),
                        func.coalesce(User.account_type, "full") == "full",
                        func.coalesce(User.is_demo, False) == False)  # noqa: E712


def verified_player_id(user: User | None) -> int | None:
    """The league player id this account is verifiably, or None."""
    if user is None or not user.steam_id or not user.player_id:
        return None
    if user.is_demo or (user.account_type or "full") != "full":
        return None
    return user.player_id


def verified_users_for_player(db, player_id: int | None) -> list[User]:
    """The accounts verifiably linked to player_id, lowest user id first."""
    if player_id is None:
        return []
    return (_verified_filter(db.query(User))
            .filter(User.player_id == player_id).order_by(User.id).all())


def verified_links(db) -> dict[int, int]:
    """{user_id: player_id} for every verified link."""
    return {r.id: r.player_id
            for r in _verified_filter(db.query(User.id, User.player_id)).all()}
