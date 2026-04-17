import pytest
from auth import hash_password, verify_password


class TestPasswordHashing:
    def test_verify_correct_password(self):
        h = hash_password("secret123")
        assert verify_password("secret123", h) is True

    def test_reject_wrong_password(self):
        h = hash_password("secret123")
        assert verify_password("wrong", h) is False

    def test_hashes_are_unique(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salt makes each hash unique

    def test_verify_invalid_hash_raises(self):
        # bcrypt raises ValueError on a malformed salt — callers must use a real hash
        with pytest.raises(ValueError):
            verify_password("anything", "notahash")

    def test_empty_password_hashes_and_verifies(self):
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("nonempty", h) is False
