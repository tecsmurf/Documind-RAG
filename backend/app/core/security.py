"""
Password hashing and JWT handling.

- bcrypt directly (passlib is unmaintained). Existing passlib "$2b$" hashes
  verify unchanged.
- bcrypt only uses the first 72 bytes of a password. New passwords longer than
  that are rejected at registration; verification truncates the same way
  bcrypt always has, so older hashes keep working.
- PyJWT with HS256 pinned, required claims, issuer check and a per-user token
  version so logout can revoke every outstanding token.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

BCRYPT_MAX_BYTES = 72
_ALGORITHM = "HS256"

# Used to equalise timing when the account does not exist.
_DUMMY_HASH = bcrypt.hashpw(b"documind-timing-equaliser", bcrypt.gensalt(rounds=12)).decode()


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > BCRYPT_MAX_BYTES:
        raise ValueError("Password is too long.")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    """Constant-ish time verify. Malformed or missing hashes return False."""
    candidate = plain.encode("utf-8")[:BCRYPT_MAX_BYTES]
    target = hashed or _DUMMY_HASH
    try:
        ok = bcrypt.checkpw(candidate, target.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash: still burn the same work so timing does not reveal it.
        bcrypt.checkpw(candidate, _DUMMY_HASH.encode())
        return False
    return ok and hashed is not None


def burn_password_check(plain: str) -> None:
    """Spend a bcrypt verification when the user doesn't exist (anti-enumeration)."""
    verify_password(plain, None)


def create_access_token(user_id: int, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Return the validated payload, or None for any invalid/expired/forged token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["sub", "exp", "iat", "iss", "ver", "type"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        payload["user_id"] = int(payload["sub"])
        payload["ver"] = int(payload["ver"])
    except (TypeError, ValueError):
        return None
    return payload
