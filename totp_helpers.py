"""TOTP helper functions: secret generation, QR code, validation."""

import base64
import io
from datetime import datetime, timezone

import pyotp
import qrcode


def generate_secret() -> str:
    """Generates a random Base32 TOTP secret."""
    return pyotp.random_base32()


def build_provisioning_uri(secret: str, user_id: str, issuer: str = "X2FA") -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=user_id, issuer_name=issuer)


def generate_qr_data_uri(provisioning_uri: str) -> str:
    """Returns a base64-encoded PNG data URI for the QR code."""
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_code(secret: str, code: str, last_used_at: datetime | None = None) -> bool:
    """Validates a TOTP code with replay protection.

    Returns False if:
    - Code is invalid
    - Code has already been used within the current 30-second window (replay)
    """
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return False

    # Replay protection: last_used_at must not fall within the same 30-second window
    if last_used_at is not None:
        now = datetime.now(tz=timezone.utc)
        last = last_used_at.replace(tzinfo=timezone.utc) if last_used_at.tzinfo is None else last_used_at
        delta = (now - last).total_seconds()
        if delta < 30:
            return False

    return True
