"""TOTP-based MFA helpers.

Uses pyotp for RFC-6238 time-based one-time passwords.
Backup codes are single-use random hex strings stored hashed (bcrypt) in the DB.
"""

from __future__ import annotations

import base64
import io
import secrets

import bcrypt
import pyotp
import qrcode

from ragrig.config import Settings


def generate_totp_secret() -> str:
    """Return a new random base32 TOTP secret."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str, settings: Settings) -> str:
    """Return the otpauth:// URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=settings.ragrig_mfa_issuer)


def totp_qr_png_b64(uri: str) -> str:
    """Return the QR code for *uri* as a base64-encoded PNG string."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_totp(secret: str, code: str) -> bool:
    """Return True if *code* is a valid TOTP for *secret* (±1 window)."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes(count: int) -> tuple[list[str], list[str]]:
    """Return *(plain_codes, hashed_codes)*.

    Plain codes are shown to the user once; hashed codes are stored in the DB.
    Each code is a 10-character hex string (40 bits of entropy).
    """
    plain: list[str] = [secrets.token_hex(5) for _ in range(count)]
    hashed: list[str] = [bcrypt.hashpw(c.encode(), bcrypt.gensalt()).decode() for c in plain]
    return plain, hashed


def consume_backup_code(code: str, hashed_codes: list[str]) -> list[str] | None:
    """Try to consume a backup code.

    Returns the updated hashed_codes list with the matched code removed,
    or None if no code matched.
    """
    for i, hashed in enumerate(hashed_codes):
        try:
            if bcrypt.checkpw(code.encode(), hashed.encode()):
                return hashed_codes[:i] + hashed_codes[i + 1 :]
        except Exception:
            continue
    return None
