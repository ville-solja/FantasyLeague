import re

import bcrypt

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


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False  # Twitch soft accounts (issue #157) have no password
    return bcrypt.checkpw(password.encode(), password_hash.encode())
