"""Integration tests for TOTP routes."""

import pyotp


def _setup_totp(client, user_id: str = "user_test") -> str:
    """Creates a verified TOTP secret in the DB and returns the plaintext value."""
    from flask import current_app
    from totp_helpers import generate_secret
    from app.services.crypto import CryptoService
    from app.models import TOTPSecret, db

    secret = generate_secret()
    with client.app_context():
        crypto = CryptoService(current_app.config["X2FA_SECRET"])
        secret_encrypted = crypto.encrypt(secret)
        totp_record = TOTPSecret.query.get(user_id)
        if totp_record:
            totp_record.secret_encrypted = secret_encrypted
            totp_record.verified = True
            totp_record.last_used_at = None
        else:
            db.session.add(TOTPSecret(
                user_id=user_id,
                secret_encrypted=secret_encrypted,
                verified=True,
            ))
        db.session.commit()
    return secret


# ---------------------------------------------------------------------------
# GET /totp/setup
# ---------------------------------------------------------------------------

def test_totp_setup_get_valid(client):
    client.set_session(setup_mode=True)
    status, headers, body = client.get("/totp/setup")
    assert status.startswith("200")
    assert b"data:image/png;base64" in body
    assert b"otpauth" not in body          # provisioning URI must not appear in plaintext
    assert "Content-Security-Policy" in headers


def test_totp_setup_get_no_session(client):
    status, _, _ = client.get("/totp/setup")
    assert status.startswith("400")


def test_totp_setup_get_stores_secret(client):
    from app.models import TOTPSecret

    client.set_session(setup_mode=True)
    client.get("/totp/setup")
    with client.app_context():
        rec = TOTPSecret.query.get("user_test")
    assert rec is not None
    assert rec.verified is False


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------

def test_totp_setup_verify_correct_code(client):
    from app.services.crypto import CryptoService
    from app.models import TOTPSecret

    client.set_session(setup_mode=True)
    client.get("/totp/setup")

    with client.app_context():
        from flask import current_app
        rec = TOTPSecret.query.get("user_test")
        crypto = CryptoService(current_app.config["X2FA_SECRET"])
        secret = crypto.decrypt(bytes(rec.secret_encrypted))
    code = pyotp.TOTP(secret).now()

    # Session persists after GET — POST directly without calling set_session() again
    status, headers, _ = client.post_form("/totp/setup/verify", {"code": code})
    assert status.startswith("302")
    assert "/authorize" in headers.get("Location", "")
    assert "error" not in headers.get("Location", "")

    with client.app_context():
        rec = TOTPSecret.query.get("user_test")
    assert rec.verified is True


def test_totp_setup_verify_wrong_code(client):
    client.set_session(setup_mode=True)
    client.get("/totp/setup")
    status, headers, _ = client.post_form("/totp/setup/verify", {"code": "000000"})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_totp_setup_verify_no_session(client):
    status, _, _ = client.post_form("/totp/setup/verify", {"code": "123456"})
    assert status.startswith("400")


# ---------------------------------------------------------------------------
# GET /totp/verify
# ---------------------------------------------------------------------------

def test_totp_verify_get_no_secret(client):
    client.set_session()
    status, headers, _ = client.get("/totp/verify")
    assert status.startswith("302")
    assert "error=access_denied" in headers.get("Location", "")


def test_totp_verify_get_unverified_secret(client):
    from totp_helpers import generate_secret
    from app.services.crypto import CryptoService
    from app.models import TOTPSecret, db

    with client.app_context():
        from flask import current_app
        crypto = CryptoService(current_app.config["X2FA_SECRET"])
        secret_encrypted = crypto.encrypt(generate_secret())
        totp_record = TOTPSecret.query.get("user_test")
        if totp_record:
            totp_record.secret_encrypted = secret_encrypted
            totp_record.verified = False
        else:
            db.session.add(TOTPSecret(
                user_id="user_test",
                secret_encrypted=secret_encrypted,
                verified=False,
            ))
        db.session.commit()

    client.set_session()
    status, headers, _ = client.get("/totp/verify")
    assert status.startswith("302")
    assert "error=access_denied" in headers.get("Location", "")


def test_totp_verify_get_valid(client):
    _setup_totp(client)
    client.set_session()
    status, _, body = client.get("/totp/verify")
    assert status.startswith("200")
    assert "Einmalcode".encode() in body


# ---------------------------------------------------------------------------
# POST /totp/verify
# ---------------------------------------------------------------------------

def test_totp_verify_correct_code(client):
    secret = _setup_totp(client)
    code = pyotp.TOTP(secret).now()

    client.set_session()
    status, headers, _ = client.post_form("/totp/verify", {"code": code})
    assert status.startswith("302")
    assert "/authorize" in headers.get("Location", "")
    assert "error" not in headers.get("Location", "")


def test_totp_verify_wrong_code(client):
    _setup_totp(client)
    client.set_session()
    status, headers, _ = client.post_form("/totp/verify", {"code": "000000"})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_totp_verify_replay(client):
    """The same code within 30 s must be rejected (replay protection)."""
    from app.models import TOTPSecret, db
    from datetime import datetime, timezone

    secret = _setup_totp(client)
    with client.app_context():
        rec = TOTPSecret.query.get("user_test")
        rec.last_used_at = datetime.now(timezone.utc)
        db.session.commit()

    code = pyotp.TOTP(secret).now()
    client.set_session()
    status, headers, _ = client.post_form("/totp/verify", {"code": code})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")
