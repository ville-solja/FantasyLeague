from auth import hash_password, verify_password


def test_hash_password_produces_bcrypt_string():
    h = hash_password("mypassword")
    assert isinstance(h, str)
    assert h.startswith("$2b$")


def test_verify_password_correct():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h) is True


def test_verify_password_wrong():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", h) is False


def test_hash_uses_unique_salt():
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2


def test_verify_uses_embedded_salt():
    # verify_password must work purely from the hash string, no separate salt param
    h = hash_password("test123")
    assert verify_password("test123", h) is True
    assert verify_password("test124", h) is False
