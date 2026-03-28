"""Unit-Tests für crypto.py."""

import pytest
import jwt as pyjwt


def test_fernet_roundtrip():
    from crypto import encrypt_totp_secret, decrypt_totp_secret
    plaintext = "JBSWY3DPEHPK3PXP"
    assert decrypt_totp_secret(encrypt_totp_secret(plaintext)) == plaintext


def test_fernet_different_ciphertexts():
    """Jede Verschlüsselung erzeugt einen anderen Ciphertext (IV)."""
    from crypto import encrypt_totp_secret
    secret = "JBSWY3DPEHPK3PXP"
    assert encrypt_totp_secret(secret) != encrypt_totp_secret(secret)


def test_jwt_roundtrip():
    from crypto import create_jwt, verify_jwt
    payload = {"sub": "user123", "action": "setup"}
    token = create_jwt(payload, expiry_minutes=5)
    decoded = verify_jwt(token)
    assert decoded["sub"] == "user123"
    assert decoded["action"] == "setup"


def test_jwt_expired():
    from crypto import create_jwt, verify_jwt
    token = create_jwt({"sub": "x"}, expiry_minutes=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        verify_jwt(token)


def test_jwt_tampered():
    from crypto import create_jwt, verify_jwt
    token = create_jwt({"sub": "x"}, expiry_minutes=5)
    tampered = token[:-4] + "XXXX"
    with pytest.raises(Exception):
        verify_jwt(tampered)


def test_bcrypt_verify():
    from crypto import hash_backup_code, verify_backup_code
    code = "A1B2C3D4"
    h = hash_backup_code(code)
    assert verify_backup_code(code, h) is True
    assert verify_backup_code("WRONG123", h) is False


def test_backup_code_generation():
    from crypto import generate_backup_codes
    codes = generate_backup_codes(10)
    assert len(codes) == 10
    assert len(set(codes)) == 10  # alle eindeutig
    assert all(len(c) == 8 for c in codes)
    assert all(c == c.upper() for c in codes)
