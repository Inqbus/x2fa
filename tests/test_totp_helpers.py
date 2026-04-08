"""Unit tests for totp_helpers.py."""

from datetime import datetime, timedelta, timezone

import pyotp

from app.src.x2fa.app import NEVER_USED


def test_generate_secret():
    from app.src.x2fa.app import generate_secret

    secret = generate_secret()
    assert len(secret) >= 16
    # Valid Base32
    import base64

    base64.b32decode(secret)


def test_provisioning_uri():
    from app.src.x2fa.app import build_provisioning_uri

    uri = build_provisioning_uri("JBSWY3DPEHPK3PXP", "alice", "X2FA")
    assert uri.startswith("otpauth://totp/")
    assert "alice" in uri
    assert "X2FA" in uri


def test_qr_data_uri():
    from app.src.x2fa.app import generate_qr_data_uri

    uri = generate_qr_data_uri("otpauth://totp/test?secret=ABC")
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 100


def test_verify_code_valid():
    from app.src.x2fa.app import verify_code

    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    assert verify_code(secret, code, last_used_at=NEVER_USED) is True


def test_verify_code_invalid():
    from app.src.x2fa.app import verify_code

    secret = pyotp.random_base32()
    assert verify_code(secret, "000000", last_used_at=NEVER_USED) is False


def test_verify_code_replay_protection():
    """The same code within 30s is rejected."""
    from app.src.x2fa.app import verify_code

    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    recent = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
    assert verify_code(secret, code, last_used_at=recent) is False


def test_verify_code_replay_after_window():
    """Code is accepted when last_used_at is more than 30s in the past."""
    from app.src.x2fa.app import verify_code

    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    old = datetime.now(tz=timezone.utc) - timedelta(seconds=35)
    assert verify_code(secret, code, last_used_at=old) is True
