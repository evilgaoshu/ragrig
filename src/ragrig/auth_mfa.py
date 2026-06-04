"""TOTP-based MFA helpers.

Uses pyotp for RFC-6238 time-based one-time passwords.
Backup codes are single-use random hex strings stored hashed (bcrypt) in the DB.
"""

from __future__ import annotations

import base64
import io
import secrets
from typing import Any

import bcrypt

from ragrig.config import Settings

pyotp: Any | None = None
qrcode: Any | None = None


def _load_pyotp() -> Any:
    global pyotp
    if pyotp is None:
        try:
            import pyotp as pyotp_module
        except ImportError as exc:
            raise RuntimeError("MFA support requires the 'mfa' optional extra") from exc
        pyotp = pyotp_module
    return pyotp


def _load_qrcode() -> Any:
    global qrcode
    if qrcode is None:
        try:
            import qrcode as qrcode_module
        except ImportError as exc:
            raise RuntimeError("MFA QR code support requires the 'mfa' optional extra") from exc
        qrcode = qrcode_module
    return qrcode


def generate_totp_secret() -> str:
    """Return a new random base32 TOTP secret."""
    return _load_pyotp().random_base32()


def totp_provisioning_uri(secret: str, email: str, settings: Settings) -> str:
    """Return the otpauth:// URI for QR code generation."""
    totp = _load_pyotp().TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=settings.ragrig_mfa_issuer)


def totp_qr_png_b64(uri: str) -> str:
    """Return the QR code for *uri* as a base64-encoded PNG string."""
    img = _load_qrcode().make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_totp(secret: str, code: str) -> bool:
    """Return True if *code* is a valid TOTP for *secret* (±1 window)."""
    totp = _load_pyotp().TOTP(secret)
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
