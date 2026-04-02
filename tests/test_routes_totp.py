"""Integrationstests für TOTP-Routen."""

import pyotp
from datetime import datetime, timedelta, timezone


def _setup_totp(user_id="user_test") -> str:
    """Legt ein verifiziertes TOTP-Secret an und gibt den Klartext-Secret zurück."""
    from totp_helpers import generate_secret
    from app.services.crypto import CryptoService
    from app.models import TOTPSecret, db
    
    secret = generate_secret()
    crypto = CryptoService(TEST_SECRET)
    secret_encrypted = crypto.encrypt(secret)
    
    totp_record = TOTPSecret.query.get(user_id)
    if totp_record:
        totp_record.secret_encrypted = secret_encrypted
        totp_record.verified = True
    else:
        db.session.add(TOTPSecret(
            user_id=user_id,
            secret_encrypted=secret_encrypted,
            verified=True
        ))
    db.session.commit()
    return secret


# ---------------------------------------------------------------------------
# GET /totp/setup
# ---------------------------------------------------------------------------

def test_totp_setup_get_valid(client, setup_token):
    status, headers, body = client.get("/totp/setup", query=f"token={setup_token}")
    assert status.startswith("200")
    assert b"data:image/png;base64" in body
    assert b"otpauth" not in body  # URI nicht im Klartext
    assert "Content-Security-Policy" in headers


def test_totp_setup_get_no_token(client):
    status, _, _ = client.get("/totp/setup")
    assert status.startswith("400")


def test_totp_setup_get_stores_secret(client, setup_token):
    from app.models import TOTPSecret
    client.get("/totp/setup", query=f"token={setup_token}")
    rec = TOTPSecret.query.get("user_test")
    assert rec is not None
    assert rec.verified is False


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------

def test_totp_setup_verify_correct_code(client, setup_token):
    from app.models import TOTPSecret
    from app.services.crypto import CryptoService

    client.get("/totp/setup", query=f"token={setup_token}")
    rec = TOTPSecret.query.get("user_test")
    crypto = CryptoService(TEST_SECRET)
    secret = crypto.decrypt(bytes(rec.secret_encrypted))
    code = pyotp.TOTP(secret).now()

    status, headers, _ = client.post_form("/totp/setup/verify", {"token": setup_token, "code": code})
    assert status.startswith("302")
    assert "https://app/cb" in headers.get("Location", "")
    assert "error" not in headers.get("Location", "")

    rec = TOTPSecret.query.get("user_test")
    assert rec.verified is True


def test_totp_setup_verify_wrong_code(client, setup_token):
    client.get("/totp/setup", query=f"token={setup_token}")
    status, headers, _ = client.post_form("/totp/setup/verify", {"token": setup_token, "code": "000000"})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_totp_setup_verify_invalid_token(client):
    status, _, _ = client.post_form("/totp/setup/verify", {"token": "BAD", "code": "123456"})
    assert status.startswith("400")


# ---------------------------------------------------------------------------
# GET /totp/verify
# ---------------------------------------------------------------------------

def test_totp_verify_get_no_secret(client, verify_token):
    status, _, _ = client.get("/totp/verify", query=f"token={verify_token}")
    assert status.startswith("400")


def test_totp_verify_get_unverified_secret(client, verify_token):
    from totp_helpers import generate_secret
    from app.services.crypto import CryptoService
    from app.models import TOTPSecret, db
    
    crypto = CryptoService(TEST_SECRET)
    secret_encrypted = crypto.encrypt(generate_secret())
    
    totp_record = TOTPSecret.query.get("user_test")
    if totp_record:
        totp_record.secret_encrypted = secret_encrypted
        totp_record.verified = False
    else:
        db.session.add(TOTPSecret(
            user_id="user_test",
            secret_encrypted=secret_encrypted,
            verified=False
        ))
    db.session.commit()
    
    # verified bleibt False
    status, _, _ = client.get("/totp/verify", query=f"token={verify_token}")
    assert status.startswith("400")


def test_totp_verify_get_valid(client, verify_token):
    _setup_totp()
    status, _, body = client.get("/totp/verify", query=f"token={verify_token}")
    assert status.startswith("200")
    assert b"Einmalcode" in body


# ---------------------------------------------------------------------------
# POST /totp/verify
# ---------------------------------------------------------------------------

def test_totp_verify_correct_code(client, verify_token):
    secret = _setup_totp()
    code = pyotp.TOTP(secret).now()

    status, headers, _ = client.post_form("/totp/verify", {"token": verify_token, "code": code})
    assert status.startswith("302")
    assert "https://app/cb" in headers.get("Location", "")


def test_totp_verify_wrong_code(client, verify_token):
    _setup_totp()
    status, headers, _ = client.post_form("/totp/verify", {"token": verify_token, "code": "000000"})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_totp_verify_replay(client, verify_token):
    """Gleicher Code innerhalb 30s muss abgelehnt werden."""
    from app.models import TOTPSecret, db
    from datetime import datetime, timezone
    
    secret = _setup_totp()
    # last_used_at auf jetzt setzen
    rec = TOTPSecret.query.get("user_test")
    rec.last_used_at = datetime.now(timezone.utc)
    db.session.commit()

    code = pyotp.TOTP(secret).now()
    status, headers, _ = client.post_form("/totp/verify", {"token": verify_token, "code": code})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_totp_verify_return_jwt_contains_amr(client, verify_token):
    import jwt
    from app.services.crypto import CryptoService
    
    secret = _setup_totp()
    code = pyotp.TOTP(secret).now()

    _, headers, _ = client.post_form("/totp/verify", {"token": verify_token, "code": code})
    location = headers.get("Location", "")
    return_token = location.split("token=")[1]
    
    crypto = CryptoService(TEST_SECRET)
    payload = jwt.decode(return_token, crypto.get_fernet()._key.decode(), algorithms=["HS256"])
    assert payload["amr"] == ["totp"]
    assert payload["sub"] == "user_test"
