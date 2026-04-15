"""Unit tests for totp_helpers.py."""

from datetime import datetime, timedelta, timezone

import pyotp

from x2fa.constants import NEVER_USED
from x2fa.helpers.totp_helpers import (
    build_provisioning_uri,
    generate_qr_data_uri,
    generate_secret,
    verify_code,
)


def test_generate_secret():
    secret = generate_secret()
    assert len(secret) >= 16
    import base64
    base64.b32decode(secret)


def test_provisioning_uri():
    uri = build_provisioning_uri("JBSWY3DPEHPK3PXP", "alice", "X2FA")
    assert uri.startswith("otpauth://totp/")
    assert "alice" in uri
    assert "X2FA" in uri


def test_qr_data_uri():
    uri = generate_qr_data_uri("otpauth://totp/test?secret=ABC")
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 100


def test_verify_code_valid():
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    assert verify_code(secret, code, last_used_at=NEVER_USED) is True


def test_verify_code_invalid():
    secret = pyotp.random_base32()
    assert verify_code(secret, "000000", last_used_at=NEVER_USED) is False


def test_verify_code_replay_protection():
    """The same code within 30s is rejected."""
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    recent = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
    assert verify_code(secret, code, last_used_at=recent) is False


def test_verify_code_replay_after_window():
    """Code is accepted when last_used_at is more than 30s in the past."""
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    old = datetime.now(tz=timezone.utc) - timedelta(seconds=35)
    assert verify_code(secret, code, last_used_at=old) is True
