"""Integration tests for TOTP routes."""

import pyotp


def _setup_totp(client, user_id: str = "user_test") -> str:
    """Creates a verified TOTP secret in the DB and returns the plaintext value."""
    from flask import current_app
    from x2fa.helpers.totp_helpers import generate_secret
    from x2fa.services.crypto import CryptoService
    from x2fa.models import TOTPSecret
    from x2fa.constants import NEVER_USED
    from x2fa.init_app.database import SessionFactory

    secret = generate_secret()
    with client.app_context():
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        secret_encrypted = crypto.encrypt(secret)
        db_session = SessionFactory()
        totp_record = db_session.get(TOTPSecret, user_id)
        if totp_record:
            totp_record.secret_encrypted = secret_encrypted
            totp_record.verified = True
            totp_record.last_used_at = NEVER_USED
        else:
            db_session.add(
                TOTPSecret(
                    user_id=user_id,
                    secret_encrypted=secret_encrypted,
                    verified=True,
                )
            )
        db_session.commit()
        db_session.close()
    return secret


# ---------------------------------------------------------------------------
# GET /totp/setup
# ---------------------------------------------------------------------------


def test_totp_setup_get_valid(client):
    client.set_session(setup_mode=True)
    status, headers, body = client.get("/totp/setup")
    assert status.startswith("200")
    assert b"data:image/png;base64" in body
    assert b"otpauth" not in body  # provisioning URI must not appear in plaintext
    assert "Content-Security-Policy" in headers


def test_totp_setup_get_no_session(client):
    status, _, _ = client.get("/totp/setup")
    assert status.startswith("400")


def test_totp_setup_get_stores_secret(client):
    from x2fa.models import TOTPSecret
    from x2fa.init_app.database import SessionFactory

    client.set_session(setup_mode=True)
    client.get("/totp/setup")
    with client.app_context():
        db_session = SessionFactory()
        rec = db_session.get(TOTPSecret, "user_test")
        db_session.close()
    assert rec is not None
    assert rec.verified is False


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------


def test_totp_setup_verify_correct_code(client):
    from x2fa.services.crypto import CryptoService
    from x2fa.models import TOTPSecret
    from x2fa.init_app.database import SessionFactory

    client.set_session(setup_mode=True)
    client.get("/totp/setup")

    with client.app_context():
        from flask import current_app

        db_session = SessionFactory()
        rec = db_session.get(TOTPSecret, "user_test")
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        secret = crypto.decrypt(bytes(rec.secret_encrypted))
        db_session.close()
    code = pyotp.TOTP(secret).now()

    # Session persists after GET — POST directly without calling set_session() again
    status, headers, _ = client.post_form("/totp/setup/verify", {"code": code})
    assert status.startswith("302")
    assert "/setup/done" in headers.get("Location", "")
    assert "error" not in headers.get("Location", "")

    with client.app_context():
        db_session = SessionFactory()
        rec = db_session.get(TOTPSecret, "user_test")
        db_session.close()
    assert rec.verified is True


def test_totp_setup_verify_generates_backup_codes(client):
    from sqlalchemy import select
    from x2fa.services.crypto import CryptoService
    from x2fa.models import BackupCode, TOTPSecret
    from x2fa.constants import NEVER_USED
    from x2fa.init_app.database import SessionFactory

    client.set_session(setup_mode=True)
    client.get("/totp/setup")

    with client.app_context():
        from flask import current_app

        db_session = SessionFactory()
        rec = db_session.get(TOTPSecret, "user_test")
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        secret = crypto.decrypt(bytes(rec.secret_encrypted))
        db_session.close()
    code = pyotp.TOTP(secret).now()

    client.post_form("/totp/setup/verify", {"code": code})

    with client.app_context():
        db_session = SessionFactory()
        codes = db_session.execute(
            select(BackupCode).where(BackupCode.user_id == "user_test")
        ).scalars().all()
        db_session.close()
    assert len(codes) == 10
    assert all(c.used_at == NEVER_USED for c in codes)


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
    from x2fa.helpers.totp_helpers import generate_secret
    from x2fa.services.crypto import CryptoService
    from x2fa.models import TOTPSecret
    from x2fa.init_app.database import SessionFactory

    with client.app_context():
        from flask import current_app

        db_session = SessionFactory()
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        secret_encrypted = crypto.encrypt(generate_secret())
        totp_record = db_session.get(TOTPSecret, "user_test")
        if totp_record:
            totp_record.secret_encrypted = secret_encrypted
            totp_record.verified = False
        else:
            db_session.add(
                TOTPSecret(
                    user_id="user_test",
                    secret_encrypted=secret_encrypted,
                    verified=False,
                )
            )
        db_session.commit()
        db_session.close()

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
    from x2fa.models import TOTPSecret
    from x2fa.init_app.database import SessionFactory
    from datetime import datetime, timezone

    secret = _setup_totp(client)
    with client.app_context():
        db_session = SessionFactory()
        rec = db_session.get(TOTPSecret, "user_test")
        rec.last_used_at = datetime.now(timezone.utc)
        db_session.commit()
        db_session.close()

    code = pyotp.TOTP(secret).now()
    client.set_session()
    status, headers, _ = client.post_form("/totp/verify", {"code": code})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")
