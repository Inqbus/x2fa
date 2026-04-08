"""Unit tests for CryptoService (app/services/crypto.py)."""

import pytest


def test_fernet_roundtrip():
    from app.src.x2fa.app.services.crypto import CryptoService

    cs = CryptoService("test-secret")
    plaintext = "JBSWY3DPEHPK3PXP"
    assert cs.decrypt(cs.encrypt(plaintext)) == plaintext


def test_fernet_different_ciphertexts():
    """Each encryption produces a different ciphertext (IV)."""
    from app.src.x2fa.app.services.crypto import CryptoService

    cs = CryptoService("test-secret")
    secret = "JBSWY3DPEHPK3PXP"
    assert cs.encrypt(secret) != cs.encrypt(secret)


def test_fernet_wrong_key_fails():
    """Decryption with the wrong key fails."""
    from app.src.x2fa.app.services.crypto import CryptoService
    from cryptography.fernet import InvalidToken

    cs1 = CryptoService("secret-one")
    cs2 = CryptoService("secret-two")
    ciphertext = cs1.encrypt("hello")
    with pytest.raises(InvalidToken):
        cs2.decrypt(ciphertext)


def test_bcrypt_verify():
    from app.src.x2fa.app.services.crypto import CryptoService

    code = "A1B2C3D4"
    h = CryptoService.hash_backup_code(code)
    assert CryptoService.verify_backup_code(code, h) is True
    assert CryptoService.verify_backup_code("WRONG123", h) is False


def test_backup_code_generation():
    from app.src.x2fa.app.services.crypto import CryptoService

    codes = CryptoService.generate_backup_codes(10)
    assert len(codes) == 10
    assert len(set(codes)) == 10  # all unique
    assert all(len(c) == 8 for c in codes)
    assert all(c == c.upper() for c in codes)
