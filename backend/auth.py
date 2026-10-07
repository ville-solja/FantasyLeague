import os
import re

import bcrypt
from fastapi import HTTPException

# bcrypt only uses the first 72 bytes of a password (4.x truncates silently,
# 5.x raises), so password fields reject anything longer (issue #135).
PASSWORD_MAX_BYTES = 72

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_USERNAME_RE = re.compile(r"[A-Za-z0-9_-]+")
USERNAME_RULE = "Username may only contain letters A-Z and a-z, digits 0-9, underscore (_) and hyphen (-)"


def check_password_bytes(password: str) -> str:
    """Pydantic field validator body: reject passwords over 72 UTF-8 bytes."""
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes")
    return password


def check_email(email: str) -> str:
    """Pydantic field validator body: strict address shape; rejects CR/LF and spaces."""
    email = email.strip(" ")
    if not _EMAIL_RE.fullmatch(email):
        raise ValueError("Invalid email address")
    return email


def check_username(username: str) -> str:
    """Pydantic field validator body: ASCII letters, digits, _ and - only (issue #136).

    Applied to new registrations and renames only; LoginBody has no charset
    check so pre-existing names outside the pattern can still log in.
    """
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError(USERNAME_RULE)
    return username


# Issue #169: words new names may not contain, matched against normalise_username().
DEFAULT_RESERVED_WORDS = "admin,kana,liiga,support,official,staff,mod"
RESERVED_NAME_DETAIL = "This name is reserved"
_LOOKALIKE = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})


def normalise_username(name: str) -> str:
    """Lower-case, drop _ and -, and map look-alikes (0→o 1→i 3→e 4→a 5→s 7→t rn→m vv→w)."""
    s = name.lower().replace("_", "").replace("-", "").translate(_LOOKALIKE)
    return s.replace("rn", "m").replace("vv", "w")


def reserved_words() -> set[str]:
    """RESERVED_USERNAME_WORDS (comma-separated), read at call time. Entries are
    normalised like names (so `m0d` or `kana_liiga` still match). A value with no
    usable entry (unset, blank, only commas) falls back to the defaults, so the
    check can't be switched off by accident."""
    def parse(raw: str) -> set[str]:
        return {n for n in (normalise_username(w.strip()) for w in raw.split(",")) if n}
    return parse(os.getenv("RESERVED_USERNAME_WORDS", "")) or parse(DEFAULT_RESERVED_WORDS)


def is_reserved(name: str) -> bool:
    norm = normalise_username(name)
    return any(word in norm for word in reserved_words())


def check_reserved(name: str) -> None:
    """Handler-side check for new names (register, rename, Steam sign-up, demo seeding).
    Env admin seeding does not call it."""
    if is_reserved(name):
        raise HTTPException(status_code=422, detail=RESERVED_NAME_DETAIL)


def username_taken(db, name: str, exclude_user_id: int | None = None) -> bool:
    """True when another account has this name, ignoring letter case."""
    from sqlalchemy import func
    from models import User
    q = db.query(User.id).filter(func.lower(User.username) == name.lower())
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.first() is not None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False  # Twitch soft accounts (issue #157) have no password
    return bcrypt.checkpw(password.encode(), password_hash.encode())
