"""Integrationstests für TOTP-Routen."""

import pyotp
from datetime import datetime, timedelta, timezone


def _setup_totp(user_id="user_test") -> str:
    """Legt ein verifiziertes TOTP-Secret an und gibt den Klartext-Secret zurück."""
    from totp_helpers import generate_secret
    from crypto import encrypt_totp_secret
    from repositories import TOTPRepo

    secret = generate_secret()
    TOTPRepo.save(user_id, encrypt_totp_secret(secret))
    TOTPRepo.set_verified(user_id)
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
    from repositories import TOTPRepo
    client.get("/totp/setup", query=f"token={setup_token}")
    rec = TOTPRepo.get("user_test")
    assert rec is not None
    assert rec.verified is False


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------

def test_totp_setup_verify_correct_code(client, setup_token):
    from repositories import TOTPRepo
    from crypto import decrypt_totp_secret

    client.get("/totp/setup", query=f"token={setup_token}")
    rec = TOTPRepo.get("user_test")
    secret = decrypt_totp_secret(bytes(rec.secret_encrypted))
    code = pyotp.TOTP(secret).now()

    status, headers, _ = client.post_form("/totp/setup/verify", {"token": setup_token, "code": code})
    assert status.startswith("302")
    assert "https://app/cb" in headers.get("Location", "")
    assert "error" not in headers.get("Location", "")

    rec = TOTPRepo.get("user_test")
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
    from crypto import encrypt_totp_secret
    from repositories import TOTPRepo

    TOTPRepo.save("user_test", encrypt_totp_secret(generate_secret()))
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
    from repositories import TOTPRepo
    secret = _setup_totp()
    # last_used_at auf jetzt setzen
    TOTPRepo.update_last_used("user_test")

    code = pyotp.TOTP(secret).now()
    status, headers, _ = client.post_form("/totp/verify", {"token": verify_token, "code": code})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_totp_verify_return_jwt_contains_amr(client, verify_token):
    from crypto import verify_jwt
    secret = _setup_totp()
    code = pyotp.TOTP(secret).now()

    _, headers, _ = client.post_form("/totp/verify", {"token": verify_token, "code": code})
    location = headers.get("Location", "")
    return_token = location.split("token=")[1]
    payload = verify_jwt(return_token)
    assert payload["amr"] == ["totp"]
    assert payload["sub"] == "user_test"
