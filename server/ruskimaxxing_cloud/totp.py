"""Minimal TOTP (RFC 6238), SHA1/6-digit/30s, using only the standard library - no pyotp dependency."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

ISSUER = "RuskiMaxxing"
PERIOD = 30
DIGITS = 6
WINDOW = 1  # accept the previous, current and next 30-second step


def new_secret() -> str:
    """A random base32 secret (no padding), ready to scan into an authenticator app."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    secret = (secret or "").strip().upper().replace(" ", "")
    pad = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(secret + pad)


def _hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def step_for(for_time: float | None = None, period: int = PERIOD) -> int:
    return int((for_time if for_time is not None else time.time()) // period)


def current_code(secret: str, for_time: float | None = None) -> str:
    """For tests/tooling: the code that would be valid right now (or at for_time)."""
    return _hotp(_key(secret), step_for(for_time))


def verify(secret: str, code: str, last_step: int | None, for_time: float | None = None,
           window: int = WINDOW) -> int | None:
    """Checks a 6-digit code against the time window around now, rejecting replay of an old code.

    Returns the step number that matched (save this as the new "last used" step for that user) or
    None if the code is wrong, malformed, or was already used."""
    code = (code or "").strip()
    if not secret or not code.isdigit() or len(code) != DIGITS:
        return None
    key = _key(secret)
    now_step = step_for(for_time)
    for s in range(now_step - window, now_step + window + 1):
        if last_step is not None and s <= last_step:
            continue
        if hmac.compare_digest(_hotp(key, s), code):
            return s
    return None


def otpauth_uri(email: str, secret: str, issuer: str = ISSUER) -> str:
    label = urllib.parse.quote(f"{issuer}:{email}")
    query = urllib.parse.urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1",
                                    "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"
