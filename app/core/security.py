"""Password hashing and session-token primitives (Stage 5). Standard library only.

Passwords: scrypt (memory-hard KDF) with a per-password random salt. Parameters follow the
OWASP password-storage guidance (N=2^14, r=8, p=5, ~16 MiB) and are stored inside the
hash string, so they can be raised later: `needs_rehash()` flags old hashes and the login
flow transparently upgrades them.

    scrypt$<log2 N>$<r>$<p>$<salt b64>$<hash b64>

Session tokens: 256 random bits (URL-safe). Only SHA-256(token) is stored in the database,
so a leaked table cannot be replayed as bearer tokens.
"""

import base64
import hashlib
import hmac
import secrets

SCRYPT_LOG2_N = 14
SCRYPT_R = 8
SCRYPT_P = 5
SALT_BYTES = 16
KEY_BYTES = 32
_MAXMEM = 64 * 1024 * 1024
_PREFIX = "scrypt"

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**log2_n, r=r, p=p, maxmem=_MAXMEM, dklen=KEY_BYTES
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P)
    return f"{_PREFIX}${SCRYPT_LOG2_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def _parse(encoded: str) -> tuple[int, int, int, bytes, bytes] | None:
    try:
        prefix, log2_n, r, p, salt, key = encoded.split("$")
        if prefix != _PREFIX:
            return None
        return int(log2_n), int(r), int(p), base64.b64decode(salt), base64.b64decode(key)
    except (ValueError, TypeError):
        return None


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check. Malformed/unknown hashes simply fail."""
    parsed = _parse(encoded)
    if parsed is None:
        return False
    log2_n, r, p, salt, expected = parsed
    if not (1 <= log2_n <= 20 and 1 <= r <= 32 and 1 <= p <= 16):
        return False
    return hmac.compare_digest(_derive(password, salt, log2_n, r, p), expected)


def needs_rehash(encoded: str) -> bool:
    parsed = _parse(encoded)
    return parsed is None or parsed[:3] != (SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P)


# A real hash of a random password, verified against when a username does not exist so that
# unknown users and wrong passwords take the same time (no user enumeration by timing).
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def check_password_policy(password: str, *, username: str | None = None) -> None:
    """Raise ValueError when the password is unacceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    if password.strip() != password:
        raise ValueError("password cannot start or end with whitespace")
    if len(set(password)) < 5:
        raise ValueError("password is too repetitive")
    if username and username.lower() in password.lower():
        raise ValueError("password cannot contain the username")


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
