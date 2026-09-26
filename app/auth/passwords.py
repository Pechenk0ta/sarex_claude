import secrets

from pwdlib import PasswordHash

MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHash.recommended()  # argon2id
# Checked when the e-mail is unknown, so a login attempt takes the same time either way.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False
    return _hasher.verify(password, password_hash)


def generate_password() -> str:
    """Temporary password an admin hands to a new user."""
    return secrets.token_urlsafe(12)
