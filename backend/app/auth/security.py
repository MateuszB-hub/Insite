"""Password hashing and session-token primitives.

Choices and why:

* **Argon2id** for passwords -- memory-hard, the current OWASP recommendation.
  Not bcrypt (72-byte truncation), and emphatically not a bare SHA.
* **Session tokens are random, not JWTs.** A server-side session can be
  revoked instantly; a stateless JWT cannot. For an HR portal, "log this
  person out now" has to actually work.
* Only the SHA-256 of a token is persisted. Tokens are high-entropy random
  values, so a fast hash is correct here -- the slow-hash argument applies to
  guessable secrets, not 256-bit ones.
"""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# argon2-cffi defaults track the RFC 9106 low-memory profile.
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12
SESSION_TOKEN_BYTES = 32  # 256 bits


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time verify that never raises on bad input."""
    if not password_hash:
        # Spend comparable effort anyway so a missing hash is not detectable
        # by timing (user-enumeration defence).
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def new_session_token() -> str:
    """URL-safe, 256 bits of entropy."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def password_problems(password: str) -> list[str]:
    """Validate strength. Length first -- it dominates entropy in practice."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.lower() in _COMMON:
        problems.append("is too common")
    if password and password.strip() == "":
        problems.append("cannot be only whitespace")
    return problems


#: Not a real breach list -- a tripwire for the obvious. A production build
#: should check Have I Been Pwned's k-anonymity range API instead.
_COMMON = {
    "password", "password123", "passw0rd123", "123456789012",
    "qwertyuiop12", "letmein12345", "administrator", "changeme123",
}
